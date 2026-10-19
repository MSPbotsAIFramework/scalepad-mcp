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
"""FastMCP factory and the per-request credential middleware."""

import contextvars
import re
import uuid
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .api_client import ScalePadClient, ScalePadCredentials
from .config import DEFAULT_REGION, REGION_HOSTS, Settings

HEADER_API_KEY = "X-ScalePad-Api-Key"
HEADER_REGION = "X-ScalePad-Region"
# Accepted for compatibility and ignored: Quoter is reached through the
# ScalePad API with the ScalePad key.
HEADER_QUOTER_CLIENT_ID = "X-Quoter-Client-Id"
HEADER_QUOTER_CLIENT_SECRET = "X-Quoter-Client-Secret"

_PLACEHOLDER = re.compile(r"^\$\{.*\}$")

# Per-request isolation: the middleware sets these for the duration of one
# HTTP request and resets them in `finally`. Nothing credential-related is
# ever stored at module level.
_credentials_var: contextvars.ContextVar[ScalePadCredentials | None] = contextvars.ContextVar(
    "scalepad_credentials", default=None
)
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("scalepad_request_id", default="-")

INSTRUCTIONS = (
    "ScalePad is an MSP platform. One API key reaches five products; tool "
    "names carry the product: scalepad_core_* (unified client, contact, asset, "
    "contract and ticket data, read-only), scalepad_lm_* (Lifecycle Manager: "
    "initiatives, goals, meetings, action items, assessments, deliverables, "
    "budgets, contracts, hardware lifecycle), scalepad_cm_* (ControlMap "
    "compliance: risks, controls, evidence, policies, procedures, assessments), "
    "scalepad_br_* (Backup Radar backup health) and scalepad_quoter_* (quotes "
    "and catalog).\n"
    "Usage:\n"
    "- scalepad_navigate(domain) lists one product's tools; scalepad_status checks "
    "the key and region.\n"
    "- Most ids are strings. Find a client with scalepad_core_clients_list "
    "(filter by name) or scalepad_lm_clients_lookup(search).\n"
    "- Lists are cursor-paginated: page_size 1-200 and the next_cursor from the "
    "previous response as cursor. filter takes {field: value} pairs.\n"
    "- A 402 error means the account has no subscription for that product.\n"
    "Tools that create, update, attach, publish or delete change live records "
    "(deletes cannot be undone): call them only when the user explicitly asks, "
    "with the exact values given."
)


def get_client_from_context() -> ScalePadClient | None:
    """The client for the current request, or None outside a request."""
    credentials = _credentials_var.get()
    if credentials is None:
        return None
    return ScalePadClient(credentials)


def _clean(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text or _PLACEHOLDER.match(text):
        return None
    return text


class GatewayCredentialsMiddleware:
    """Reads X-ScalePad-Api-Key (and the optional region) on /mcp requests; 401 without a key."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        api_key = _clean(request.headers.get(HEADER_API_KEY))
        if not api_key:
            await JSONResponse(
                {
                    "error": "Missing credentials",
                    "message": f"Missing header: {HEADER_API_KEY}",
                    "required_headers": [HEADER_API_KEY],
                    "optional_headers": [HEADER_REGION, HEADER_QUOTER_CLIENT_ID, HEADER_QUOTER_CLIENT_SECRET],
                },
                status_code=401,
            )(scope, receive, send)
            return
        region = (_clean(request.headers.get(HEADER_REGION)) or DEFAULT_REGION).lower()
        if region not in REGION_HOSTS:
            await JSONResponse(
                {"error": "Invalid header", "message": f"{HEADER_REGION} must be one of: {', '.join(REGION_HOSTS)}"},
                status_code=400,
            )(scope, receive, send)
            return

        request_id = (request.headers.get("x-request-id") or "").strip()[:64] or uuid.uuid4().hex[:12]
        creds_token = _credentials_var.set(ScalePadCredentials(api_key=api_key, region=region))
        rid_token = request_id_var.set(request_id)
        try:
            await self.app(scope, receive, send)
        finally:
            _credentials_var.reset(creds_token)
            request_id_var.reset(rid_token)


def create_mcp_server(settings: Settings | None = None) -> FastMCP:
    """Build the FastMCP server and register every tool."""
    mcp = FastMCP(
        name="scalepad-mcp",
        instructions=INSTRUCTIONS,
        # The service sits behind the gateway, so Host is never localhost;
        # DNS-rebinding protection would reject those requests with 421.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        stateless_http=True,
    )

    client_factory: Callable[[], ScalePadClient | None] = get_client_from_context

    from .tools import navigation, registry

    navigation.register(mcp, client_factory)
    registry.register(mcp, client_factory)
    return mcp
