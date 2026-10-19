# Copyright 2026 MSPbots.ai
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Registers every tool of the declarative catalog and turns calls into requests.

Each catalog argument says where its value goes:
  path      -> substituted into the URL template
  query     -> query parameter (lists repeat the key)
  filter    -> {key: value} expanded to filter[key]=value
  body      -> field of the JSON object body
  body_array-> the value is the whole JSON array body
  item      -> field of the single object sent as a one-element array body
  file / filename -> multipart upload (file is base64)
  text_json -> plain text converted to a rich-text (ProseMirror) JSON string
"""

import asyncio
import base64
import binascii
import inspect
import json
from typing import Annotated, Any, Literal
from urllib.parse import quote

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import ScalePadClient, ScalePadError
from ..catalog import TOOLS
from ._common import DESTRUCTIVE, READ_ONLY, WRITES, WRITES_IDEMPOTENT, ClientFactory, run_tool

_TYPES: dict[str | None, Any] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": dict[str, Any],
    "array": list[Any],
    None: Any,
}
_GROUP_SCAN_LIMIT = 50
_GROUP_CONCURRENCY = 4


def python_type(arg: dict) -> Any:
    if arg.get("enum"):
        return Literal[tuple(arg["enum"])]
    if arg.get("wrap_id"):
        return dict[str, Any] | str
    if arg.get("join_list"):
        return str | list[str]
    return _TYPES.get(arg.get("type"), Any)


def describe(entry: dict) -> str:
    """Tool description: what it does, then paging / safety notes."""
    lines = [entry["summary"]]
    if entry.get("detail"):
        lines.append(entry["detail"])
    if entry.get("paged"):
        lines.append("Cursor-paginated: page_size 1-200; pass next_cursor from the response as cursor.")
    if entry["kind"] == "destructive":
        lines.append("Cannot be undone: only when the user explicitly asks for this exact record.")
    elif entry["kind"] == "write":
        lines.append("Changes live data: only when the user explicitly asks.")
    text = lines[0] + ("\n\n" + " ".join(lines[1:]) if len(lines) > 1 else "")
    return text[:500]


def annotations_for(entry: dict):
    if entry["kind"] == "read":
        return READ_ONLY
    if entry["kind"] == "destructive":
        return DESTRUCTIVE
    return WRITES_IDEMPOTENT if entry.get("method") in ("PUT", "PATCH") else WRITES


def prosemirror(text: str) -> str:
    """Plain text as a minimal ProseMirror document (one paragraph per line)."""
    paragraphs = [
        {"type": "paragraph", "content": [{"type": "text", "text": line}]} if line else {"type": "paragraph"}
        for line in text.split("\n")
    ]
    return json.dumps({"type": "doc", "content": paragraphs}, ensure_ascii=False)


def _query_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"))
    return str(value)


def build_request(entry: dict, values: dict[str, Any]) -> dict[str, Any]:
    """Method, path, query, JSON body and files for one call of a catalog tool."""
    path = entry["path"]
    query: list[tuple[str, str]] = []
    body: dict[str, Any] = {}
    item: dict[str, Any] = {}
    whole_body: Any = None
    file_b64 = file_name = None
    for arg in entry["args"]:
        value = values.get(arg["name"])
        if value is None:
            continue
        if arg.get("wrap_id") and isinstance(value, str):
            value = {"id": value.strip()}
        if arg.get("join_list") and isinstance(value, list):
            value = ",".join(str(v) for v in value)
        kind, wire = (arg.get("to") or [None, None])[:2]
        if kind == "path":
            text = str(value).strip()
            if not text:
                raise ValueError(f"{arg['name']} must not be blank.")
            path = path.replace("{" + wire + "}", quote(text, safe=""))
        elif kind == "query":
            items = value if isinstance(value, list) else [value]
            query.extend((wire, _query_value(v)) for v in items)
        elif kind == "filter":
            if not isinstance(value, dict):
                raise ValueError("filter must be an object of {field: value}.")
            for key, val in value.items():
                if val is not None:
                    query.append((f"filter[{key}]", _query_value(val)))
        elif kind == "body":
            body[wire] = value
        elif kind == "text_json":
            body.setdefault(wire, prosemirror(str(value)))
        elif kind == "body_array":
            whole_body = value
        elif kind == "item":
            item[wire] = value
        elif kind == "file":
            file_b64 = value
        elif kind == "filename":
            file_name = value
    unresolved = [p for p in _placeholders(path)]
    if unresolved:
        raise ValueError(f"Missing path value(s): {', '.join(unresolved)}.")
    request: dict[str, Any] = {"method": entry["method"], "path": path, "query": query}
    special = entry.get("special")
    if special == "multipart":
        try:
            content = base64.b64decode(file_b64 or "", validate=True)
        except (binascii.Error, ValueError) as e:
            raise ValueError("file must be base64-encoded content.") from e
        request["files"] = {"file": (file_name or "upload.bin", content)}
    elif special == "array_of_one":
        request["json_body"] = [item]
    elif whole_body is not None:
        request["json_body"] = whole_body
    elif entry.get("body"):
        # Only operations that define a request body get one (even if empty).
        request["json_body"] = body
    return request


def _placeholders(path: str) -> list[str]:
    out, start = [], path.find("{")
    while start >= 0:
        end = path.find("}", start)
        out.append(path[start + 1 : end])
        start = path.find("{", end)
    return out


async def client_groups_for_client(client: ScalePadClient, client_key: str) -> dict:
    """Client groups whose member list contains the client (no direct API for this)."""
    wanted = client_key.strip()
    if not wanted:
        raise ValueError("client_key must not be blank.")
    listing = await client.request("GET", "lm", "/lifecycle-manager/v1/client-groups") or {}
    groups = [g for g in listing.get("data") or [] if isinstance(g, dict) and g.get("client_group_id")]
    scanned = groups[:_GROUP_SCAN_LIMIT]
    semaphore = asyncio.Semaphore(_GROUP_CONCURRENCY)

    async def detail(group: dict) -> dict | None:
        async with semaphore:
            gid = quote(str(group["client_group_id"]), safe="")
            payload = await client.request("GET", "lm", f"/lifecycle-manager/v1/client-groups/{gid}") or {}
        full = payload.get("client_group") if isinstance(payload, dict) else None
        if not isinstance(full, dict):
            return None
        clients = [c for c in full.get("clients") or [] if isinstance(c, dict)]
        if any(str(c.get("id")) == wanted for c in clients):
            return {"client_group_id": full.get("client_group_id"), "name": full.get("name"), "client_count": len(clients)}
        return None

    matches = [g for g in await asyncio.gather(*(detail(g) for g in scanned)) if g]
    result: dict[str, Any] = {"client_key": wanted, "client_groups": matches, "count": len(matches)}
    if len(groups) > len(scanned):
        result["note"] = f"Only the first {_GROUP_SCAN_LIMIT} of {len(groups)} client groups were checked."
    return result


def make_tool(entry: dict, client_factory: ClientFactory):
    name = entry["name"]

    async def tool(**kwargs: Any) -> str:
        async def action(client: ScalePadClient) -> Any:
            special = entry.get("special")
            if special == "unsupported":
                raise ValueError(entry.get("detail") or "Not available in the ScalePad API.")
            if special == "client_groups_for_client":
                return await client_groups_for_client(client, str(kwargs.get("client_key") or ""))
            request = build_request(entry, kwargs)
            return await client.request(
                request["method"],
                entry["product"],
                request["path"],
                query=request["query"],
                json_body=request.get("json_body"),
                files=request.get("files"),
            )

        return await run_tool(name, client_factory, action)

    params = []
    for arg in sorted(entry["args"], key=lambda a: not a["required"]):
        annotation = Annotated[python_type(arg), Field(description=arg.get("description") or arg["name"])]
        if not arg["required"]:
            annotation = Annotated[python_type(arg) | None, Field(description=arg.get("description") or arg["name"])]
        params.append(
            inspect.Parameter(
                arg["name"],
                inspect.Parameter.KEYWORD_ONLY,
                default=inspect.Parameter.empty if arg["required"] else None,
                annotation=annotation,
            )
        )
    tool.__name__ = name
    tool.__doc__ = describe(entry)
    tool.__signature__ = inspect.Signature(params, return_annotation=str)
    return tool


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    for entry in TOOLS:
        fn = make_tool(entry, client_factory)
        mcp.tool(name=entry["name"], description=describe(entry), annotations=annotations_for(entry))(fn)


__all__ = ["register", "build_request", "prosemirror", "ScalePadError"]
