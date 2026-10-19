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
"""Credential middleware: 401/400 on bad headers, per-request isolation."""

import asyncio

import pytest
from starlette.testclient import TestClient

from scalepad_mcp.__main__ import build_http_app
from scalepad_mcp.server import GatewayCredentialsMiddleware, _credentials_var, create_mcp_server, get_client_from_context

MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}


@pytest.fixture(scope="module")
def http():
    with TestClient(build_http_app(create_mcp_server())) as client:
        yield client


def test_health_is_local(http):
    resp = http.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.parametrize("headers", [{}, {"X-ScalePad-Api-Key": "  "}, {"X-ScalePad-Api-Key": "${SCALEPAD_KEY}"}])
def test_missing_key_returns_401(http, headers):
    resp = http.post("/mcp", json=LIST_TOOLS, headers=MCP_HEADERS | headers)
    assert resp.status_code == 401
    assert resp.json()["required_headers"] == ["X-ScalePad-Api-Key"]


def test_unknown_region_returns_400(http):
    resp = http.post("/mcp", json=LIST_TOOLS, headers=MCP_HEADERS | {"X-ScalePad-Api-Key": "k", "X-ScalePad-Region": "mars"})
    assert resp.status_code == 400


def test_tools_list_over_http_with_quoter_headers_ignored(http):
    headers = MCP_HEADERS | {"X-ScalePad-Api-Key": "k", "X-Quoter-Client-Id": "id", "X-Quoter-Client-Secret": "secret"}
    resp = http.post("/mcp", json=LIST_TOOLS, headers=headers)
    assert resp.status_code == 200
    for name in ("scalepad_navigate", "scalepad_core_clients_list", "scalepad_cm_risks_delete", "scalepad_quoter_quotes_publish"):
        assert name in resp.text


def _run_middleware(headers: list[tuple[bytes, bytes]]) -> dict:
    seen: dict = {}

    async def app(scope, receive, send):
        seen["credentials"] = _credentials_var.get()
        seen["client"] = get_client_from_context()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message):
        return None

    asyncio.run(GatewayCredentialsMiddleware(app)({"type": "http", "path": "/mcp", "headers": headers}, receive, send))
    return seen


def test_headers_reach_request_context_and_are_reset():
    seen = _run_middleware([(b"x-scalepad-api-key", b" key-1 "), (b"x-scalepad-region", b"EU")])
    assert (seen["credentials"].api_key, seen["credentials"].region) == ("key-1", "eu")
    assert seen["client"].region == "eu"
    assert _credentials_var.get() is None


def test_region_defaults_to_us():
    assert _run_middleware([(b"x-scalepad-api-key", b"k")])["credentials"].region == "us"


def test_concurrent_requests_do_not_share_credentials():
    observed: list[tuple[str, str]] = []

    async def app(scope, receive, send):
        before = _credentials_var.get().api_key
        await asyncio.sleep(0.01)
        observed.append((before, _credentials_var.get().api_key))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message):
        return None

    middleware = GatewayCredentialsMiddleware(app)

    def scope(key: bytes) -> dict:
        return {"type": "http", "path": "/mcp", "headers": [(b"x-scalepad-api-key", key)]}

    async def both():
        await asyncio.gather(middleware(scope(b"tenant-a"), receive, send), middleware(scope(b"tenant-b"), receive, send))

    asyncio.run(both())
    assert sorted(observed) == [("tenant-a", "tenant-a"), ("tenant-b", "tenant-b")]


def test_credentials_repr_hides_key():
    seen = _run_middleware([(b"x-scalepad-api-key", b"very-secret-key")])
    assert "very-secret-key" not in repr(seen["credentials"])
