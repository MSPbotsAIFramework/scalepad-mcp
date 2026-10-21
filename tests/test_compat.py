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
"""Previous-contract parameter forms keep working: widened types and their conversion."""

import asyncio
import json

import httpx
import pytest

from scalepad_mcp import api_client
from scalepad_mcp.catalog import TOOLS
from scalepad_mcp.server import _credentials_var, create_mcp_server
from scalepad_mcp.api_client import ScalePadCredentials

CATALOG = {e["name"]: e for e in TOOLS}
OPEN_ENUMS = [(e["name"], a["name"]) for e in TOOLS for a in e["args"] if a.get("compat") == "open_enum"]

# (tool, base args, param, previous-contract value, value sent, current-contract value)
BREAK_CASES = [
    ("scalepad_cm_controls_create", {"client_id": "c1", "name": "MFA"}, "tag", "security", ["security"], ["a", "b"]),
    (
        "scalepad_cm_assessments_search_questions",
        {"client_id": "c1"},
        "rules",
        {"field": "x", "value": 1},
        [{"field": "x", "value": 1}],
        [{"field": "x"}, {"field": "y"}],
    ),
    ("scalepad_quoter_quotes_list", {}, "filter_stage", "won", ["won"], ["won", "lost"]),
    (
        "scalepad_quoter_quotes_create_section_line_item",
        {"quote_id": "q1", "section_id": "s1", "name": "Laptop"},
        "discount",
        "10%",
        {"input_type": "percentage", "input_decimal": "10"},
        {"input_type": "amount", "input_decimal": "5.00"},
    ),
    (
        "scalepad_quoter_quotes_update_line_item",
        {"quote_id": "q1", "section_id": "s1", "line_item_id": "l1"},
        "discount",
        "$25.50",
        {"input_type": "amount", "input_decimal": "25.50"},
        {"input_type": "percentage", "input_decimal": "5"},
    ),
]
for _tool, _base in (
    ("scalepad_quoter_contacts_create", {}),
    ("scalepad_quoter_contacts_update", {"id": "k1"}),
):
    for _param in ("billing_address", "shipping_address"):
        BREAK_CASES.append(
            (
                _tool,
                _base,
                _param,
                "1 Main St",
                {"address_line_1": "1 Main St"},
                {"address_line_1": "1 Main St", "city": "Austin", "country_code": "US"},
            )
        )


class Recorder:
    def __init__(self):
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json={"data": []})


async def _call(monkeypatch, tool: str, args: dict) -> tuple[dict, httpx.Request | None]:
    recorder = Recorder()
    http = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    monkeypatch.setattr(api_client, "_get_shared_http_client", lambda: http)
    ctx = _credentials_var.set(ScalePadCredentials(api_key="key-123", region="us"))
    try:
        content, _ = await create_mcp_server().call_tool(tool, args)
    finally:
        _credentials_var.reset(ctx)
    return json.loads(content[0].text), (recorder.requests[-1] if recorder.requests else None)


def _sent(request: httpx.Request, entry: dict, param: str):
    arg = next(a for a in entry["args"] if a["name"] == param)
    kind, wire = arg["to"]
    if kind == "query":
        return request.url.params.get_list(wire)
    body = json.loads(request.content)
    return body[0][wire] if kind == "item" else body[wire]


@pytest.fixture(scope="module")
def tools():
    return {t.name: t for t in asyncio.run(create_mcp_server().list_tools())}


def test_every_flagged_param_is_covered():
    flagged = {(e["name"], a["name"]) for e in TOOLS for a in e["args"] if a.get("compat") not in (None, "open_enum")}
    assert flagged == {(c[0], c[2]) for c in BREAK_CASES}
    assert len(OPEN_ENUMS) == 24


@pytest.mark.parametrize("tool,base,param,old,converted,new", BREAK_CASES)
async def test_break_param_accepts_old_and_new_form(monkeypatch, tool, base, param, old, converted, new):
    result, request = await _call(monkeypatch, tool, {**base, param: old})
    assert "error" not in result, result
    assert _sent(request, CATALOG[tool], param) == converted
    result, request = await _call(monkeypatch, tool, {**base, param: new})
    assert "error" not in result, result
    assert _sent(request, CATALOG[tool], param) == new


@pytest.mark.parametrize(
    "text,expected",
    [
        ("10%", {"input_type": "percentage", "input_decimal": "10"}),
        (" 12.5 % ", {"input_type": "percentage", "input_decimal": "12.5"}),
        ("10", {"input_type": "amount", "input_decimal": "10"}),
        ('{"input_type": "amount", "input_decimal": "3"}', {"input_type": "amount", "input_decimal": "3"}),
    ],
)
async def test_discount_strings(monkeypatch, text, expected):
    tool = "scalepad_quoter_quotes_update_line_item"
    _, request = await _call(monkeypatch, tool, {"quote_id": "q", "section_id": "s", "line_item_id": "l", "discount": text})
    assert _sent(request, CATALOG[tool], "discount") == expected


@pytest.mark.parametrize("text", ["ten percent", "-5", "1,000"])
async def test_unreadable_discount_is_invalid_argument(monkeypatch, text):
    tool = "scalepad_quoter_quotes_update_line_item"
    result, request = await _call(monkeypatch, tool, {"quote_id": "q", "section_id": "s", "line_item_id": "l", "discount": text})
    assert result["error"]["code"] == "invalid_argument" and request is None


async def test_blank_address_is_invalid_argument(monkeypatch):
    result, request = await _call(monkeypatch, "scalepad_quoter_contacts_update", {"id": "k1", "billing_address": "  "})
    assert result["error"]["code"] == "invalid_argument" and request is None


@pytest.mark.parametrize("tool,param", OPEN_ENUMS)
async def test_open_enum_normalizes_case_and_passes_unknown_values(monkeypatch, tool, param):
    entry = CATALOG[tool]
    arg = next(a for a in entry["args"] if a["name"] == param)
    samples = {"integer": 1, "number": 1, "boolean": True, "array": ["x1"], "object": {"id": "x1"}}
    base = {a["name"]: samples.get(a["type"], "x1") for a in entry["args"] if a["required"] and a["name"] != param}
    canonical = arg["enum"][-1]
    for given, expected in ((canonical, canonical), (canonical.swapcase(), canonical), ("Something Else", "Something Else")):
        result, request = await _call(monkeypatch, tool, {**base, param: given})
        assert "error" not in result, result
        sent = _sent(request, entry, param)
        assert (sent[0] if isinstance(sent, list) else sent) == expected


def test_tools_list_advertises_widened_types(tools):
    for name, _, param, _, _, _ in BREAK_CASES:
        prop = tools[name].inputSchema["properties"][param]
        kinds = {o.get("type") for o in prop["anyOf"]} - {"null"}
        compat = next(a for a in CATALOG[name]["args"] if a["name"] == param)["compat"]
        expected = {"string_or_list": {"string", "array"}, "object_or_list": {"object", "array"}}.get(compat, {"string", "object"})
        assert kinds == expected, (name, param, kinds)
    for name, param in OPEN_ENUMS:
        schema = tools[name].inputSchema
        options = schema["properties"][param]["anyOf"]
        assert {"type": "string"} in options, (name, param)
        refs = [o["$ref"].rsplit("/", 1)[-1] for o in options if "$ref" in o]
        arg = next(a for a in CATALOG[name]["args"] if a["name"] == param)
        assert len(refs) == 1 and schema["$defs"][refs[0]]["enum"] == arg["enum"], (name, param)
