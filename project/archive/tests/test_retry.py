"""Tests for retry decorator and XTBaseClient._handle_response.

_handle_response: pure sync unit tests, no HTTP.
Retry integration: custom AsyncTransport (no external mock library needed).
"""

from __future__ import annotations

import json

import httpx
import pytest

from xt_mcp.clients.base import XTBaseClient
from xt_mcp.exceptions import (
    XTAPIError,
    XTNotFoundError,
    XTRateLimitError,
    XTServerError,
)

SPOT_URL = "https://sapi.xt.com"


class _NoopLimiter:
    async def acquire(self) -> None:
        pass


def _make_response(status_code: int, body: dict | None = None) -> httpx.Response:
    content = json.dumps(body or {}).encode()
    return httpx.Response(
        status_code,
        content=content,
        request=httpx.Request("GET", f"{SPOT_URL}/test"),
    )


# --- _handle_response unit tests (pure sync, no network) ---

def test_handle_response_200_returns_body():
    client = XTBaseClient.__new__(XTBaseClient)
    resp = _make_response(200, {"rc": "0", "result": "ok"})
    data = client._handle_response(resp)
    assert data["rc"] == "0"


def test_handle_response_429_raises_rate_limit():
    client = XTBaseClient.__new__(XTBaseClient)
    with pytest.raises(XTRateLimitError):
        client._handle_response(_make_response(429))


def test_handle_response_404_raises_not_found():
    client = XTBaseClient.__new__(XTBaseClient)
    with pytest.raises(XTNotFoundError):
        client._handle_response(_make_response(404))


def test_handle_response_500_raises_server_error():
    client = XTBaseClient.__new__(XTBaseClient)
    with pytest.raises(XTServerError):
        client._handle_response(_make_response(500))


def test_handle_response_400_raises_api_error():
    client = XTBaseClient.__new__(XTBaseClient)
    with pytest.raises(XTAPIError):
        client._handle_response(_make_response(400, {"message": "Bad request"}))


# --- Retry integration tests using a custom transport ---

class _ScriptedTransport(httpx.AsyncBaseTransport):
    """Serves a scripted sequence of responses; raises after exhaustion."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = list(responses)
        self.call_count = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.call_count += 1
        resp = self._responses.pop(0)
        # httpx requires the request to be attached to the response
        return httpx.Response(
            resp.status_code,
            content=resp.content,
            request=request,
        )


async def test_retry_on_rate_limit_then_success():
    """Client retries on 429 and succeeds on the subsequent attempt."""
    success_body = json.dumps({"rc": "0", "result": "ok"}).encode()
    transport = _ScriptedTransport([
        httpx.Response(429),
        httpx.Response(200, content=success_body),
    ])

    http = httpx.AsyncClient(base_url=SPOT_URL, transport=transport)
    client = XTBaseClient(http=http, limiter=_NoopLimiter())

    result = await client._get("/test")
    assert result["rc"] == "0"
    assert transport.call_count == 2
    await http.aclose()


async def test_no_retry_on_not_found():
    """Client does NOT retry on 404 — fails immediately on first call."""
    transport = _ScriptedTransport([httpx.Response(404)])

    http = httpx.AsyncClient(base_url=SPOT_URL, transport=transport)
    client = XTBaseClient(http=http, limiter=_NoopLimiter())

    with pytest.raises(XTNotFoundError):
        await client._get("/missing")

    assert transport.call_count == 1  # no retry occurred
    await http.aclose()


async def test_exhausted_retry_reraises():
    """After max retry attempts, the original exception is reraised."""
    # 3 consecutive 429s (default retry_max_attempts=3)
    transport = _ScriptedTransport([
        httpx.Response(429),
        httpx.Response(429),
        httpx.Response(429),
    ])

    http = httpx.AsyncClient(base_url=SPOT_URL, transport=transport)
    client = XTBaseClient(http=http, limiter=_NoopLimiter())

    with pytest.raises(XTRateLimitError):
        await client._get("/test")

    assert transport.call_count == 3  # tried exactly max_attempts times
    await http.aclose()
