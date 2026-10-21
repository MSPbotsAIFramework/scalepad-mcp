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
"""Async client for the ScalePad APIs (one API key, several products)."""

import asyncio
import base64
import logging
import time
from dataclasses import dataclass
from http.cookiejar import CookieJar, DefaultCookiePolicy
from typing import Any

import httpx

from ._json import error_envelope
from .config import DEFAULT_REGION, PRODUCT_NAMES, PRODUCT_PREFIX, PRODUCT_REGIONS, REGION_HOSTS

logger = logging.getLogger("scalepad_mcp.api")

_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=30.0, pool=5.0)
_MAX_RETRIES = 2
_MAX_BACKOFF_SECONDS = 30.0
# Whole-call budget including retries; the gateway times a tool call out at 120s.
_CALL_BUDGET_SECONDS = 100.0
_INLINE_BINARY_LIMIT = 12_000

# One connection pool for the process. It never holds credentials: the
# x-api-key header is set per request from the caller's own key, so sharing
# the pool across tenants is safe.
_shared_http_client: httpx.AsyncClient | None = None


class _RejectAllCookies(DefaultCookiePolicy):
    """Never store or send a cookie: the HTTP client is shared by every tenant."""

    def set_ok(self, cookie, request) -> bool:  # noqa: ANN001 - stdlib signature
        return False

    def return_ok(self, cookie, request) -> bool:  # noqa: ANN001 - stdlib signature
        return False


def _no_cookies() -> CookieJar:
    # A plain CookieJar: httpx uses it as is (an httpx.Cookies would be copied into a default jar).
    return CookieJar(policy=_RejectAllCookies())


def _get_shared_http_client() -> httpx.AsyncClient:
    global _shared_http_client
    if _shared_http_client is None:
        _shared_http_client = httpx.AsyncClient(cookies=_no_cookies(), timeout=_TIMEOUT)
    return _shared_http_client


# status_code -> (error code, retryable). 0 means no HTTP response at all
# (connection error or timeout). 402 = the account has no subscription for
# that product.
_STATUS_TO_CODE: dict[int, tuple[str, bool]] = {
    0: ("upstream_error", True),
    400: ("invalid_argument", False),
    401: ("unauthorized", False),
    402: ("unauthorized", False),
    403: ("unauthorized", False),
    404: ("not_found", False),
    409: ("invalid_argument", False),
    422: ("invalid_argument", False),
    429: ("rate_limited", True),
}


def classify_status(status_code: int) -> tuple[str, bool]:
    if status_code in _STATUS_TO_CODE:
        return _STATUS_TO_CODE[status_code]
    if status_code >= 500:
        return "upstream_error", True
    if status_code >= 400:
        return "invalid_argument", False
    return "upstream_error", True


class ScalePadError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"ScalePad API error {status_code}: {message}")

    def to_envelope(self) -> str:
        code, retryable = classify_status(self.status_code)
        return error_envelope(code, self.message, retryable)


@dataclass(frozen=True)
class ScalePadCredentials:
    api_key: str
    region: str = DEFAULT_REGION
    # Set when a header value is malformed: tools then return invalid_argument
    # instead of calling ScalePad, while tools/list still works.
    header_error: str | None = None

    def __repr__(self) -> str:  # never leak the key into logs or tracebacks
        return f"ScalePadCredentials(region={self.region!r}, api_key=<redacted>)"


class ScalePadClient:
    """ScalePad API wrapper for one caller's API key and region."""

    def __init__(self, credentials: ScalePadCredentials, http_client: httpx.AsyncClient | None = None):
        self._credentials = credentials
        self._http = http_client
        self.header_error = credentials.header_error

    @property
    def region(self) -> str:
        return self._credentials.region

    def _client(self) -> httpx.AsyncClient:
        return self._http or _get_shared_http_client()

    def base_url(self, product: str) -> str:
        regions = PRODUCT_REGIONS[product]
        region = self._credentials.region
        if region not in regions:
            if regions == ("us",):
                # US-only products answer only on the US edge, whatever the tenant region.
                region = "us"
            else:
                raise ScalePadError(
                    400, f"{PRODUCT_NAMES[product]} is not available in region {region} (available: {', '.join(regions)})"
                )
        return REGION_HOSTS[region] + PRODUCT_PREFIX.get(product, "")

    async def request(
        self,
        method: str,
        product: str,
        path: str,
        query: list[tuple[str, str]] | None = None,
        json_body: Any = None,
        files: dict[str, tuple[str, bytes]] | None = None,
    ) -> Any:
        url = self.base_url(product) + path
        headers = {"x-api-key": self._credentials.api_key, "Accept": "application/json"}
        started = time.monotonic()
        attempt = 0
        while True:
            t0 = time.monotonic()
            resp: httpx.Response | None = None
            error: ScalePadError | None = None
            try:
                kwargs: dict[str, Any] = {"params": query or None, "headers": headers}
                if files is not None:
                    kwargs["files"] = files
                elif json_body is not None:
                    kwargs["json"] = json_body
                resp = await self._client().request(method, url, **kwargs)
                status = resp.status_code
            except httpx.TimeoutException:
                status, error = 0, ScalePadError(0, f"Timed out calling ScalePad ({method} {path})")
            except httpx.RequestError as e:
                status = 0
                error = ScalePadError(0, f"Network error calling ScalePad ({method} {path}): {type(e).__name__}")

            logger.info(
                "scalepad_api method=%s product=%s path=%s status=%s ms=%d attempt=%d",
                method, product, path, status, (time.monotonic() - t0) * 1000, attempt,
            )

            # 429 is refused before processing, so any method may retry it; other
            # failures are retried only for reads, so a write never runs twice.
            retryable = status == 429 or (method == "GET" and (status == 0 or status >= 500))
            if retryable and attempt < _MAX_RETRIES:
                delay = _retry_delay(resp, attempt)
                if time.monotonic() - started + delay < _CALL_BUDGET_SECONDS:
                    attempt += 1
                    await asyncio.sleep(delay)
                    continue
            if error is not None:
                raise error
            assert resp is not None
            if resp.status_code >= 400:
                raise ScalePadError(resp.status_code, _error_message(resp, path))
            return _parse_body(resp)


def _retry_delay(resp: httpx.Response | None, attempt: int) -> float:
    if resp is not None:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, min(float(retry_after), _MAX_BACKOFF_SECONDS))
            except ValueError:
                pass
    return min(float(2**attempt), _MAX_BACKOFF_SECONDS)


def _parse_body(resp: httpx.Response) -> Any:
    if not resp.content or not resp.content.strip():
        return None
    content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type.endswith("json") or not content_type:
        try:
            return resp.json()
        except ValueError:
            pass
    if content_type.startswith("text/") or content_type in ("application/csv", "text/csv"):
        return {"content_type": content_type, "text": resp.text}
    # Files (PDF, XLSX, ...): small ones inline as base64, larger ones described.
    disposition = resp.headers.get("content-disposition")
    result: dict[str, Any] = {"content_type": content_type, "size_bytes": len(resp.content)}
    if disposition:
        result["content_disposition"] = disposition
    if len(resp.content) <= _INLINE_BINARY_LIMIT:
        result["base64"] = base64.b64encode(resp.content).decode()
    else:
        result["note"] = "Binary file not included in the response because of its size."
    return result


def _error_message(resp: httpx.Response, path: str) -> str:
    """Message from ScalePad's {"errors": [{code, title, detail}]} envelope."""
    fallback = f"ScalePad returned HTTP {resp.status_code} for {path}"
    try:
        payload = resp.json()
    except ValueError:
        text = resp.text.strip()
        return f"{fallback}: {text[:300]}" if text else fallback
    parts: list[str] = []
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if isinstance(errors, list):
        for err in errors[:5]:
            if isinstance(err, dict):
                bits = [str(err[k]) for k in ("code", "title", "detail") if err.get(k)]
                if bits:
                    parts.append(" ".join(bits))
    elif isinstance(payload, dict):
        for key in ("message", "detail", "title", "error"):
            if isinstance(payload.get(key), str) and payload[key]:
                parts.append(payload[key])
                break
    return f"{fallback}: {' | '.join(parts)[:500]}" if parts else fallback
