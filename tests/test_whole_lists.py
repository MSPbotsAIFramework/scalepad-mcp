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
"""Whole lists paged by offset (PRD-21126), required client_id and the documented 404
(PRD-21127), and the status check of all five products (PRD-21128). Mocked API only."""

import asyncio
import json

import httpx
import pytest

from scalepad_mcp import api_client
from scalepad_mcp._json import MAX_CHARS, dump_json_capped
from scalepad_mcp.api_client import ScalePadCredentials
from scalepad_mcp.catalog import TOOLS
from scalepad_mcp.server import _credentials_var, create_mcp_server
from scalepad_mcp.tools.registry import CLIENT_ID_REQUIRED, is_whole_list

CATALOG = {e["name"]: e for e in TOOLS}
WHOLE_LISTS = sorted(e["name"] for e in TOOLS if is_whole_list(e))
_SERVER = create_mcp_server()


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr(api_client.asyncio, "sleep", instant)


class Recorder:
    def __init__(self, reply=None, routes=None):
        self.requests: list[httpx.Request] = []
        self.reply = reply if reply is not None else {"data": []}
        self.routes = routes or {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reply = self.routes.get(f"{request.method} {request.url.path}", self.reply)
        if callable(reply):
            return reply(request)
        return httpx.Response(200, json=reply)


async def _call(monkeypatch, recorder: Recorder, tool: str, args: dict) -> dict:
    http = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    monkeypatch.setattr(api_client, "_get_shared_http_client", lambda: http)
    ctx = _credentials_var.set(ScalePadCredentials(api_key="key-123", region="us"))
    try:
        content, _ = await _SERVER.call_tool(tool, args)
    finally:
        _credentials_var.reset(ctx)
    text = content[0].text
    assert len(text) <= MAX_CHARS
    return json.loads(text)


def _required(tool: str) -> dict:
    return {a["name"]: 1 if a["type"] == "integer" else "x" for a in CATALOG[tool]["args"] if a["required"]}


def _big_records(n: int) -> list[dict]:
    # Many short fields: shortening long values cannot make these fit, so the list is cut.
    return [{"id": i, **{f"f{j}": f"value-{j:04d}" for j in range(60)}} for i in range(n)]


async def _walk(monkeypatch, tool: str, reply, base: dict) -> tuple[list[int], list[dict]]:
    rec = Recorder(reply)
    seen, results, offset = [], [], None
    for _ in range(50):
        args = dict(base) | ({"offset": offset} if offset is not None else {})
        out = await _call(monkeypatch, rec, tool, args)
        results.append(out)
        key = "items" if isinstance(reply, list) else "data"
        seen.extend(r["id"] for r in out[key])
        offset = out.get("next_offset")
        if offset is None:
            break
    return seen, results


# ---- PRD-21126: whole lists walked by offset / next_offset ------------------


def test_every_unpaged_list_tool_gets_optional_offset_and_limit():
    tools = {t.name: t for t in asyncio.run(_SERVER.list_tools())}
    assert len(WHOLE_LISTS) == 25
    for name in WHOLE_LISTS:
        schema = tools[name].inputSchema
        assert {"offset", "limit"} <= set(schema["properties"]), name
        assert "offset" not in schema.get("required", []) and "limit" not in schema.get("required", [])
    paged = next(e["name"] for e in TOOLS if e.get("paged"))
    assert "offset" not in tools[paged].inputSchema["properties"]


@pytest.mark.parametrize(
    "tool,total,shape",
    [
        ("scalepad_lm_goal_templates_list", 47, "data"),
        ("scalepad_lm_deliverable_templates_catalog_components_list", 33, "data"),
        ("scalepad_lm_goal_templates_list", 47, "bare"),
        ("scalepad_lm_deliverable_templates_catalog_components_list", 33, "bare"),
    ],
)
async def test_qa_lists_walked_by_next_offset_return_every_record_once(monkeypatch, tool, total, shape):
    records = _big_records(total)
    reply = {"data": records, "meta": {"source": "lm"}} if shape == "data" else records
    seen, results = await _walk(monkeypatch, tool, reply, {})
    assert seen == list(range(total))
    assert len(results) > 1  # the first result really was cut
    for out in results:
        assert "retry_page_size" not in out
        assert out["total"] == total
        if out.get("truncated"):
            assert "next_offset" in out
    assert results[-1]["has_more"] is False and "next_offset" not in results[-1]


@pytest.mark.parametrize("tool", WHOLE_LISTS[::3])
async def test_sample_of_unpaged_lists_walk_without_gaps(monkeypatch, tool):
    seen, results = await _walk(monkeypatch, tool, {"data": _big_records(40)}, _required(tool) | ({"client_id": "c1"} if tool in CLIENT_ID_REQUIRED else {}))
    assert seen == list(range(40)) and len(results) > 1
    assert all("retry_page_size" not in out for out in results)


async def test_offset_and_limit_slice_the_list(monkeypatch):
    tool = "scalepad_lm_meeting_types_list"
    reply = {"data": [{"id": i} for i in range(10)], "note_from_api": "kept"}
    rec = Recorder(reply)

    before = await _call(monkeypatch, rec, tool, {})
    assert [r["id"] for r in before["data"]] == list(range(10))
    assert (before["count"], before["total"], before["offset"], before["has_more"]) == (10, 10, 0, False)
    assert "next_offset" not in before and before["note_from_api"] == "kept"

    inside = await _call(monkeypatch, rec, tool, {"offset": 4})
    assert [r["id"] for r in inside["data"]] == list(range(4, 10)) and inside["has_more"] is False

    window = await _call(monkeypatch, rec, tool, {"offset": 2, "limit": 3})
    assert [r["id"] for r in window["data"]] == [2, 3, 4]
    assert (window["count"], window["offset"], window["has_more"], window["next_offset"]) == (3, 2, True, 5)

    past = await _call(monkeypatch, rec, tool, {"offset": 25})
    assert past["data"] == [] and past["count"] == 0 and past["has_more"] is False
    assert "next_offset" not in past

    # offset / limit never reach the ScalePad API.
    assert all("offset" not in r.url.params and "limit" not in r.url.params for r in rec.requests)


async def test_bare_list_result_is_wrapped_as_items(monkeypatch):
    out = await _call(monkeypatch, Recorder([{"id": i} for i in range(5)]), "scalepad_lm_insights_list", {"limit": 2})
    assert [r["id"] for r in out["items"]] == [0, 1] and out["next_offset"] == 2 and out["total"] == 5


async def test_negative_offset_and_zero_limit_are_rejected(monkeypatch):
    rec = Recorder({"data": [{"id": 1}]})
    for args in ({"offset": -1}, {"limit": 0}):
        with pytest.raises(Exception):  # noqa: B017 - FastMCP reports the schema violation
            await _call(monkeypatch, rec, "scalepad_lm_insights_list", args)
    assert rec.requests == []


def test_exact_continuation_carries_no_retry_hint():
    rows = _big_records(30)
    out = json.loads(dump_json_capped({"items": rows, "count": 30, "_resume": {"key": "next_offset", "start": 10}}))
    assert 0 < len(out["items"]) < 30
    assert out["next_offset"] == 10 + len(out["items"]) and "retry_page_size" not in out
    plain = json.loads(dump_json_capped({"items": rows, "count": 30}))
    assert plain["retry_page_size"] == len(plain["items"]) and "next_offset" not in plain


# ---- PRD-21127: client_id the live API requires, and the documented 404 -----


@pytest.mark.parametrize("tool", sorted(CLIENT_ID_REQUIRED))
@pytest.mark.parametrize("client_id", [None, "", "   "])
async def test_missing_client_id_is_refused_without_a_request(monkeypatch, tool, client_id):
    rec = Recorder()
    args = {} if client_id is None else {"client_id": client_id}
    out = await _call(monkeypatch, rec, tool, args)
    assert out["error"]["code"] == "invalid_argument"
    assert "client_id is required" in out["error"]["message"] and "scalepad_lm_clients_list" in out["error"]["message"]
    assert rec.requests == []


@pytest.mark.parametrize("tool", sorted(CLIENT_ID_REQUIRED))
async def test_client_id_is_sent_as_before(monkeypatch, tool):
    rec = Recorder()
    out = await _call(monkeypatch, rec, tool, {"client_id": "c-42"})
    assert "error" not in out
    assert len(rec.requests) == 1
    assert rec.requests[0].url.path == CATALOG[tool]["path"] and rec.requests[0].url.params["client_id"] == "c-42"


def test_client_id_tools_say_so_and_keep_it_optional():
    tools = {t.name: t for t in asyncio.run(_SERVER.list_tools())}
    for name in CLIENT_ID_REQUIRED:
        assert "client_id is required" in tools[name].description
        assert "client_id" not in tools[name].inputSchema.get("required", [])


async def test_hardware_replacement_settings_404_is_explained(monkeypatch):
    rec = Recorder(lambda r: httpx.Response(404, json={"message": "Not Found"}))
    out = await _call(monkeypatch, rec, "scalepad_lm_hardware_replacement_settings_get", {})
    assert out["error"]["code"] == "not_found"
    message = out["error"]["message"]
    assert "GET /lifecycle-manager/v1/assets/hardware-replacement/settings" in message
    assert "documented" in message and "may not be enabled" in message


async def test_other_404s_are_unchanged(monkeypatch):
    rec = Recorder(lambda r: httpx.Response(404, json={"message": "Not Found"}))
    out = await _call(monkeypatch, rec, "scalepad_lm_initiatives_get", {"id": "i1"})
    assert out["error"]["code"] == "not_found"
    assert "documented" not in out["error"]["message"]


# ---- PRD-21128: status covers all five products -----------------------------


async def test_status_reports_all_five_products(monkeypatch):
    rec = Recorder(
        routes={
            "GET /quoter/v1/manufacturers": lambda r: httpx.Response(401, json={"message": "Unauthorized"}),
        }
    )
    out = await _call(monkeypatch, rec, "scalepad_status", {})
    products = out["products"]
    assert set(products) == {"Core", "Lifecycle Manager", "ControlMap", "Backup Radar", "Quoter"}
    assert products["Backup Radar"] == {"reachable": True}
    assert products["Quoter"]["reachable"] is False and products["Quoter"]["status"] == 401
    assert products["Quoter"]["error"]
    paths = {r.url.path: r.url.params.get("page_size") for r in rec.requests}
    assert paths["/backup-radar/v3/clients/devices"] == "1"
    assert paths["/quoter/v1/manufacturers"] == "1"
    assert "Backup Radar" in out["note"]


async def test_walk_continues_past_a_record_too_large_on_its_own(monkeypatch):
    # INT: deliverable catalog component 6 of 33 is ~320k characters of nested objects on its own;
    # the walk stopped there with "Result too large". It is now returned alone, trimmed, and the
    # walk reaches all 33.
    rows = _big_records(33)
    rows[5] = {"id": 5, "configuration": {f"k{i}": {f"n{j}": "v" * 30 for j in range(30)} for i in range(300)}}
    seen, results = await _walk(
        monkeypatch, "scalepad_lm_deliverable_templates_catalog_components_list", {"data": rows}, {}
    )
    assert seen == list(range(33))
    trimmed = next(r for r in results if r["data"] and r["data"][0]["id"] == 5)
    assert trimmed["fields_truncated"] is True and len(trimmed["data"]) == 1
