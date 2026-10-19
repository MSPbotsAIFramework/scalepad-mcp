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
"""Routing, retries, errors and request building against a mocked ScalePad API."""

import json

import httpx
import pytest

from scalepad_mcp import api_client
from scalepad_mcp.api_client import ScalePadClient, ScalePadCredentials, ScalePadError
from scalepad_mcp.catalog import TOOLS
from scalepad_mcp.server import _credentials_var, create_mcp_server
from scalepad_mcp.tools.registry import build_request, prosemirror

CATALOG = {e["name"]: e for e in TOOLS}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr(api_client.asyncio, "sleep", instant)


class Recorder:
    def __init__(self, routes=None):
        self.requests: list[httpx.Request] = []
        self.routes = routes or {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reply = self.routes.get(f"{request.method} {request.url.path}", {"data": []})
        if callable(reply):
            return reply(request)
        return httpx.Response(200, json=reply)


async def _call(monkeypatch, recorder: Recorder, tool: str, args: dict, region: str = "us"):
    http = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    monkeypatch.setattr(api_client, "_get_shared_http_client", lambda: http)
    ctx = _credentials_var.set(ScalePadCredentials(api_key="key-123", region=region))
    try:
        content, _ = await create_mcp_server().call_tool(tool, args)
    finally:
        _credentials_var.reset(ctx)
    return json.loads(content[0].text)


def _client(recorder: Recorder, region: str = "us") -> ScalePadClient:
    return ScalePadClient(ScalePadCredentials("key-123", region), httpx.AsyncClient(transport=httpx.MockTransport(recorder)))


# ---- routing ---------------------------------------------------------------


@pytest.mark.parametrize(
    "region,product,expected",
    [
        ("us", "core", "https://api.scalepad.com"),
        ("eu", "core", "https://api.scalepad.com"),
        ("eu", "lm", "https://api.scalepad.com"),
        ("eu", "cm", "https://eu.api.scalepad.com"),
        ("au", "cm", "https://au.api.scalepad.com"),
        ("eu", "br", "https://eu.api.scalepad.com"),
        ("us", "quoter", "https://api.scalepad.com/quoter"),
    ],
)
def test_base_url_per_product_and_region(region, product, expected):
    assert _client(Recorder(), region).base_url(product) == expected


def test_backup_radar_is_not_in_ca_or_au():
    with pytest.raises(ScalePadError) as err:
        _client(Recorder(), "ca").base_url("br")
    assert err.value.status_code == 400


async def test_api_key_header_and_quoter_prefix():
    rec = Recorder()
    await _client(rec).request("GET", "quoter", "/v1/quotes", query=[("page_size", "5")])
    request = rec.requests[0]
    assert request.headers["x-api-key"] == "key-123"
    assert str(request.url) == "https://api.scalepad.com/quoter/v1/quotes?page_size=5"


# ---- retries and errors ----------------------------------------------------


async def test_get_retries_5xx_but_post_does_not():
    replies = iter([httpx.Response(503), httpx.Response(200, json={"data": []})])
    rec = Recorder({"GET /core/v1/clients": lambda r: next(replies), "POST /core/v1/contacts": lambda r: httpx.Response(500)})
    client = _client(rec)
    assert await client.request("GET", "core", "/core/v1/clients") == {"data": []}
    with pytest.raises(ScalePadError):
        await client.request("POST", "core", "/core/v1/contacts", json_body={})
    assert [r.method for r in rec.requests] == ["GET", "GET", "POST"]


async def test_429_is_retried_for_writes():
    replies = iter([httpx.Response(429, headers={"Retry-After": "2"}), httpx.Response(200, json={"ok": True})])
    rec = Recorder({"DELETE /lifecycle-manager/v1/notes/n1": lambda r: next(replies)})
    assert await _client(rec).request("DELETE", "lm", "/lifecycle-manager/v1/notes/n1") == {"ok": True}
    assert len(rec.requests) == 2


async def test_error_envelope_message_and_subscription_error(monkeypatch):
    payload = {"errors": [{"code": "PRODUCT_SUBSCRIPTION_REQUIRED", "title": "Lifecycle Manager subscription required", "detail": "A paid subscription is required."}]}
    rec = Recorder({"GET /lifecycle-manager/v1/contacts": lambda r: httpx.Response(402, json=payload)})
    result = await _call(monkeypatch, rec, "scalepad_lm_contacts_list", {})
    assert result["error"]["code"] == "unauthorized"
    assert "PRODUCT_SUBSCRIPTION_REQUIRED" in result["error"]["message"]
    assert "key-123" not in json.dumps(result)


async def test_binary_and_text_responses():
    rec = Recorder(
        {
            "GET /a": lambda r: httpx.Response(200, content=b"%PDF-1.7", headers={"content-type": "application/pdf"}),
            "GET /b": lambda r: httpx.Response(200, content=b"x" * 20000, headers={"content-type": "application/pdf"}),
            "GET /c": lambda r: httpx.Response(200, content=b"a,b\n1,2", headers={"content-type": "text/csv"}),
        }
    )
    client = _client(rec)
    small = await client.request("GET", "core", "/a")
    assert small["content_type"] == "application/pdf" and small["base64"] == "JVBERi0xLjc="
    big = await client.request("GET", "core", "/b")
    assert big["size_bytes"] == 20000 and "base64" not in big
    assert (await client.request("GET", "core", "/c"))["text"] == "a,b\n1,2"


# ---- request building ------------------------------------------------------


def test_list_with_filter_sort_and_cursor():
    request = build_request(
        CATALOG["scalepad_core_clients_list"],
        {"filter": {"name": "Example", "lifecycle": "active"}, "sort": "-record_updated_at", "page_size": 10, "cursor": "abc"},
    )
    assert request["method"] == "GET" and request["path"] == "/core/v1/clients"
    assert ("filter[name]", "Example") in request["query"]
    assert ("filter[lifecycle]", "active") in request["query"]
    assert ("page_size", "10") in request["query"] and ("cursor", "abc") in request["query"]
    assert "json_body" not in request


def test_path_values_are_escaped():
    request = build_request(CATALOG["scalepad_cm_risks_get"], {"client_id": "a/b c", "risk_id": 7})
    assert request["path"] == "/controlmap/v1/clients/a%2Fb%20c/risks/7"


def test_blank_path_value_is_rejected():
    with pytest.raises(ValueError):
        build_request(CATALOG["scalepad_cm_risks_get"], {"client_id": " ", "risk_id": "r1"})


def test_body_fields_and_bodyless_post():
    hidden = build_request(CATALOG["scalepad_lm_contacts_hidden_status_update"], {"contact_id": "c1", "is_hidden": True})
    assert hidden["method"] == "PUT" and hidden["path"] == "/lifecycle-manager/v1/contacts/c1/hidden-status"
    assert hidden["json_body"] == {"is_hidden": True}
    publish = build_request(CATALOG["scalepad_quoter_quotes_publish"], {"quote_id": "q1"})
    assert publish["method"] == "POST" and "json_body" not in publish


def test_array_of_one_body():
    request = build_request(
        CATALOG["scalepad_cm_action_items_generate_signed_urls"],
        {"client_id": "c1", "action_item_id": "a1", "file_name": "report.pdf", "file_size_bytes": 2048},
    )
    assert request["json_body"] == [{"file_name": "report.pdf", "file_size_bytes": 2048}]
    section = build_request(CATALOG["scalepad_quoter_quotes_create_section"], {"quote_id": "q1", "name": "Hardware"})
    assert section["json_body"] == [{"name": "Hardware"}]


def test_multipart_upload():
    request = build_request(
        CATALOG["scalepad_cm_action_items_upload_document"],
        {"client_id": "c1", "action_item_id": "a1", "file": "aGVsbG8=", "file_name": "note.txt"},
    )
    assert request["files"] == {"file": ("note.txt", b"hello")}
    with pytest.raises(ValueError):
        build_request(CATALOG["scalepad_cm_action_items_upload_document"], {"client_id": "c", "action_item_id": "a", "file": "not base64!"})


def test_plain_text_becomes_rich_text_on_updated_endpoints():
    request = build_request(CATALOG["scalepad_lm_initiatives_update"], {"id": "i1", "name": "Refresh", "executive_summary": "Line 1\nLine 2"})
    assert request["method"] == "PATCH" and request["path"] == "/lifecycle-manager/v1/initiatives/i1"
    doc = json.loads(request["json_body"]["executive_summary_json"])
    assert [p["content"][0]["text"] for p in doc["content"]] == ["Line 1", "Line 2"]
    assert request["json_body"]["name"] == "Refresh"
    explicit = build_request(CATALOG["scalepad_lm_goals_update"], {"id": "g1", "description": "x", "description_json": '{"type":"doc"}'})
    assert explicit["json_body"]["description_json"] == '{"type":"doc"}'


def test_prosemirror_blank_lines():
    assert json.loads(prosemirror("a\n\nb"))["content"][1] == {"type": "paragraph"}


def test_rerouted_tools_use_official_endpoints():
    contacts = build_request(CATALOG["scalepad_lm_client_contacts_lookup"], {"client_id": "c1", "search": "jo"})
    assert contacts["path"] == "/lifecycle-manager/v1/contacts"
    assert ("filter[client_id]", "c1") in contacts["query"] and ("search", "jo") in contacts["query"]
    assert build_request(CATALOG["scalepad_lm_active_users_list"], {})["path"] == "/lifecycle-manager/v1/users"


def test_list_query_values_repeat_the_key():
    request = build_request(CATALOG["scalepad_quoter_quotes_list"], {"filter_stage": ["draft", "won"]})
    assert [v for k, v in request["query"] if k == "filter[stage]"] == ["draft", "won"]


# ---- tools end to end --------------------------------------------------------


async def test_tool_call_hits_the_mapped_endpoint(monkeypatch):
    rec = Recorder({"GET /controlmap/v1/clients/c1/risks/42": {"data": {"id": 42}}})
    # risk_id is an integer in the API; numeric strings are accepted too.
    result = await _call(monkeypatch, rec, "scalepad_cm_risks_get", {"client_id": "c1", "risk_id": "42"}, region="eu")
    assert result == {"data": {"id": 42}}
    assert rec.requests[0].url.host == "eu.api.scalepad.com"


async def test_delete_returns_success_note(monkeypatch):
    rec = Recorder({"DELETE /lifecycle-manager/v1/notes/n1": lambda r: httpx.Response(204)})
    result = await _call(monkeypatch, rec, "scalepad_lm_notes_delete", {"id": "n1"})
    assert result["result"] is None and "succeeded" in result["note"]


@pytest.mark.parametrize(
    "tool,args",
    [
        ("scalepad_lm_user_identity_get", {}),
        ("scalepad_lm_user_ui_state_get", {"state_key": "k"}),
        ("scalepad_quoter_auth_refresh", {"refresh_token": "r"}),
    ],
)
async def test_unsupported_tools_explain_and_make_no_call(monkeypatch, tool, args):
    rec = Recorder()
    result = await _call(monkeypatch, rec, tool, args)
    assert result["error"]["code"] == "invalid_argument"
    assert rec.requests == []


async def test_client_groups_lookup_scans_groups(monkeypatch):
    rec = Recorder(
        {
            "GET /lifecycle-manager/v1/client-groups": {"data": [{"client_group_id": "g1"}, {"client_group_id": "g2"}]},
            "GET /lifecycle-manager/v1/client-groups/g1": {"client_group": {"client_group_id": "g1", "name": "Gold", "clients": [{"id": "c1", "label": "Example"}]}},
            "GET /lifecycle-manager/v1/client-groups/g2": {"client_group": {"client_group_id": "g2", "name": "Silver", "clients": []}},
        }
    )
    result = await _call(monkeypatch, rec, "scalepad_lm_client_groups_lookup", {"client_key": "c1"})
    assert result == {"client_key": "c1", "client_groups": [{"client_group_id": "g1", "name": "Gold", "client_count": 1}], "count": 1}


async def test_status_reports_products(monkeypatch):
    rec = Recorder({"GET /lifecycle-manager/v1/client-groups": lambda r: httpx.Response(402, json={"errors": [{"code": "PRODUCT_SUBSCRIPTION_REQUIRED"}]})})
    result = await _call(monkeypatch, rec, "scalepad_status", {})
    assert result["products"]["Core"] == {"reachable": True}
    assert result["products"]["Lifecycle Manager"]["status"] == 402


def test_reference_objects_accept_a_bare_id():
    entry = CATALOG["scalepad_lm_notes_create"]
    args = {a["name"]: "x" for a in entry["args"] if a["required"]}
    args["client_key"] = "c-123"
    assert build_request(entry, args)["json_body"]["client_key"] == {"id": "c-123"}
    args["client_key"] = {"name": "Example Co"}
    assert build_request(entry, args)["json_body"]["client_key"] == {"name": "Example Co"}


def test_field_lists_are_joined():
    entry = CATALOG["scalepad_cm_risks_search"]
    args = {a["name"]: "x" for a in entry["args"] if a["required"]}
    args["fields"] = ["id", "name"]
    assert build_request(entry, args)["json_body"]["fields"] == "id,name"
