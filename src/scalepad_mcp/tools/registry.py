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

An argument may also carry a 'compat' flag so callers of the previous contract keep working:
  open_enum      -> the documented values are advertised, but any string is accepted; a
                    case-insensitive match is normalized, anything else is sent unchanged
  string_or_list -> a single string is sent as a one-item list
  object_or_list -> a single object is sent as a one-item list
  discount       -> a string like "10%" or "25.00" becomes the line-item discount object
  address        -> a string becomes the address object (address_line_1)
"""

import asyncio
import base64
import binascii
import enum
import inspect
import json
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal
from urllib.parse import quote

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .._json import compact
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

# The API reference marks client_id optional for these, but the live API answers
# 422 "The client id is required" without it, so the call is refused locally.
CLIENT_ID_REQUIRED = frozenset(
    {
        "scalepad_lm_opportunities_list",
        "scalepad_lm_warranty_pricing_list",
        "scalepad_lm_opportunity_create_fields_get",
        "scalepad_lm_ticket_create_fields_get",
    }
)
CLIENT_ID_REQUIRED_MESSAGE = (
    "client_id is required by the ScalePad API for this tool; "
    "get it from scalepad_lm_clients_list (client.client_id)."
)
# Documented in the API reference, yet some accounts answer 404 (feature not enabled).
HARDWARE_REPLACEMENT_SETTINGS = "scalepad_lm_hardware_replacement_settings_get"
HARDWARE_REPLACEMENT_SETTINGS_404 = (
    "The endpoint GET /lifecycle-manager/v1/assets/hardware-replacement/settings is documented "
    "in the ScalePad API reference but returned 404 for this account, so the hardware replacement "
    "feature may not be enabled for it."
)
_OFFSET_DESCRIPTION = "Record position to start from (0-based); pass next_offset from the previous result."
_LIMIT_DESCRIPTION = "Records to return (default: as many as fit the response size limit)."


_COMPAT_TYPES: dict[str, Any] = {
    "string_or_list": str | list[Any],
    "object_or_list": dict[str, Any] | list[Any],
    "discount": str | dict[str, Any],
    "address": str | dict[str, Any],
}
_COMPAT_NOTES = {
    "string_or_list": " A single string is also accepted (sent as a one-item list).",
    "object_or_list": " A single object is also accepted (sent as a one-item list).",
    "discount": (
        ' Object {"input_type": "amount" | "percentage", "input_decimal": "10.00"}, or a string:'
        ' "10%" -> percentage 10, "10" or "$10" -> amount 10.'
    ),
    "address": (
        " Object with address_line_1, address_line_2, city, state_prov_code, postal_code,"
        " country_code (ISO alpha-2), or a plain string, sent as address_line_1."
    ),
}


def _open_enum_type(arg: dict) -> Any:
    """Documented values as a named enum (advertised in the schema) or any other string."""
    title = "".join(part.capitalize() for part in arg["name"].split("_")) or "Value"
    values = enum.Enum(title, [(v, v) for v in arg["enum"]], type=str)
    return values | str


def python_type(arg: dict) -> Any:
    compat = arg.get("compat")
    if compat == "open_enum":
        return _open_enum_type(arg)
    if compat in _COMPAT_TYPES:
        return _COMPAT_TYPES[compat]
    if arg.get("enum"):
        return Literal[tuple(arg["enum"])]
    if arg.get("wrap_id"):
        return dict[str, Any] | str
    if arg.get("join_list"):
        return str | list[str]
    return _TYPES.get(arg.get("type"), Any)


def describe_arg(arg: dict) -> str:
    text = arg.get("description") or arg["name"]
    compat = arg.get("compat")
    if compat == "open_enum":
        values = ", ".join(arg["enum"])
        return f"{text} One of: {values} (case-insensitive); other values are sent to ScalePad as-is."
    return text + _COMPAT_NOTES.get(compat, "")


def _open_enum_value(arg: dict, value: Any) -> Any:
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, str):
        canonical = {v.lower(): v for v in arg["enum"]}
        return canonical.get(value.strip().lower(), value)
    return value


def _json_object(text: str) -> dict | None:
    if not text.startswith("{"):
        return None
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _discount_value(name: str, value: Any) -> Any:
    """Previous contract: a free string such as "10%" (percentage) or "10" (amount)."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    parsed = _json_object(text)
    if parsed is not None:
        return parsed
    percentage = text.endswith("%")
    number = text.rstrip("%").strip().lstrip("$").strip()
    try:
        amount = Decimal(number)
    except InvalidOperation:
        amount = None
    if amount is None or not amount.is_finite() or amount < 0:
        raise ValueError(f'{name} must be a non-negative number such as "25.00" (amount) or "10%" (percentage).')
    return {"input_type": "percentage" if percentage else "amount", "input_decimal": number}


def _address_value(name: str, value: Any) -> Any:
    """Previous contract: a free-text address string, sent as the first address line."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        raise ValueError(f"{name} must not be blank.")
    parsed = _json_object(text)
    return parsed if parsed is not None else {"address_line_1": text}


def compat_value(arg: dict, value: Any) -> Any:
    """Convert a value in the previous contract's form into what the ScalePad API expects."""
    compat = arg.get("compat")
    if compat == "open_enum":
        return _open_enum_value(arg, value)
    if compat in ("string_or_list", "object_or_list"):
        return value if isinstance(value, list) else [value]
    if compat == "discount":
        return _discount_value(arg["name"], value)
    if compat == "address":
        return _address_value(arg["name"], value)
    return value


def is_whole_list(entry: dict) -> bool:
    """A read tool whose API returns the whole list at once (no paging parameters)."""
    return entry["kind"] == "read" and not entry.get("paged") and entry["name"].endswith("_list")


def page_whole_list(data: Any, offset: int | None, limit: int | None) -> Any:
    """Slice a whole-list result locally so it can be walked with offset / next_offset.

    The list is the bare result or the largest list value of an object. The output
    carries count, total, offset, has_more and next_offset, plus ``_resume`` so a
    result cut by the size limit continues right after the last record returned.
    """
    if isinstance(data, list):
        key, items, rest = "items", data, {}
    elif isinstance(data, dict):
        list_keys = [k for k, v in data.items() if isinstance(v, list)]
        if not list_keys:
            return data
        key = max(list_keys, key=lambda k: len(compact(data[k])))
        items, rest = data[key], data
    else:
        return data
    start = offset or 0
    end = len(items) if limit is None else min(start + limit, len(items))
    end = max(end, start)
    page = items[start:end]
    has_more = end < len(items)
    result: dict[str, Any] = {key: page, "count": len(page), "total": len(items), "offset": start, "has_more": has_more}
    if has_more:
        result["next_offset"] = end
    for k, v in rest.items():
        result.setdefault(k, v)
    result["_resume"] = {"key": "next_offset", "start": start}
    return result


def describe(entry: dict) -> str:
    """Tool description: what it does, then paging / safety notes."""
    lines = [entry["summary"]]
    if entry.get("detail"):
        lines.append(entry["detail"])
    if entry["name"] in CLIENT_ID_REQUIRED:
        lines.append("client_id is required by the API (get it from scalepad_lm_clients_list).")
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
        value = compat_value(arg, value)
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

    whole_list = is_whole_list(entry)

    async def tool(**kwargs: Any) -> str:
        offset = kwargs.pop("offset", None) if whole_list else None
        limit = kwargs.pop("limit", None) if whole_list else None

        async def action(client: ScalePadClient) -> Any:
            special = entry.get("special")
            if special == "unsupported":
                raise ValueError(entry.get("detail") or "Not available in the ScalePad API.")
            if special == "client_groups_for_client":
                return await client_groups_for_client(client, str(kwargs.get("client_key") or ""))
            if name in CLIENT_ID_REQUIRED and not str(kwargs.get("client_id") or "").strip():
                raise ValueError(CLIENT_ID_REQUIRED_MESSAGE)
            request = build_request(entry, kwargs)
            try:
                result = await client.request(
                    request["method"],
                    entry["product"],
                    request["path"],
                    query=request["query"],
                    json_body=request.get("json_body"),
                    files=request.get("files"),
                )
            except ScalePadError as e:
                if name == HARDWARE_REPLACEMENT_SETTINGS and e.status_code == 404:
                    raise ScalePadError(404, HARDWARE_REPLACEMENT_SETTINGS_404) from e
                raise
            return page_whole_list(result, offset, limit) if whole_list else result

        return await run_tool(name, client_factory, action)

    params = []
    for arg in sorted(entry["args"], key=lambda a: not a["required"]):
        annotation = Annotated[python_type(arg), Field(description=describe_arg(arg))]
        if not arg["required"]:
            annotation = Annotated[python_type(arg) | None, Field(description=describe_arg(arg))]
        params.append(
            inspect.Parameter(
                arg["name"],
                inspect.Parameter.KEYWORD_ONLY,
                default=inspect.Parameter.empty if arg["required"] else None,
                annotation=annotation,
            )
        )
    if whole_list:
        for arg_name, minimum, text in (("offset", 0, _OFFSET_DESCRIPTION), ("limit", 1, _LIMIT_DESCRIPTION)):
            params.append(
                inspect.Parameter(
                    arg_name,
                    inspect.Parameter.KEYWORD_ONLY,
                    default=None,
                    annotation=Annotated[int | None, Field(ge=minimum, description=text)],
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
