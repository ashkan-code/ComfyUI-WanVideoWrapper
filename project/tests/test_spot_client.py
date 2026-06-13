"""Tests for XTSpotClient — mocking _get() with AsyncMock.

Testing philosophy: _get() is tested separately (test_retry.py).
Here we verify that each client method calls _get() with the correct path
and params, and that Pydantic validation works on the fixture responses.
"""

from __future__ import annotations

import json
import pathlib
from unittest.mock import AsyncMock

import pytest

from xt_mcp.clients.spot import XTSpotClient
from xt_mcp.exceptions import XTNotFoundError, XTRateLimitError, XTServerError
from xt_mcp.rate_limiter import RateLimiter

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class _NoopLimiter(RateLimiter):
    def __init__(self):
        pass

    async def acquire(self) -> None:
        pass


def _make_client(get_return=None, get_side_effect=None) -> XTSpotClient:
    """Create a spot client with a mocked _get method."""
    client = XTSpotClient.__new__(XTSpotClient)
    client._limiter = _NoopLimiter()
    if get_side_effect is not None:
        client._get = AsyncMock(side_effect=get_side_effect)
    else:
        client._get = AsyncMock(return_value=get_return)
    return client


async def test_get_symbols_success():
    client = _make_client(get_return=_fixture("spot_symbols.json"))
    result = await client.get_symbols()
    client._get.assert_called_once_with("/v4/public/symbol")
    assert len(result.result) == 2
    assert result.result[0].symbol == "btc_usdt"


async def test_get_ticker_success():
    client = _make_client(get_return=_fixture("spot_ticker.json"))
    result = await client.get_ticker("btc_usdt")
    client._get.assert_called_once_with("/v4/public/ticker", params={"symbol": "btc_usdt"})
    assert result.rc == "0"


async def test_get_depth_success():
    client = _make_client(get_return=_fixture("spot_depth.json"))
    result = await client.get_depth("btc_usdt", limit=2)
    client._get.assert_called_once_with(
        "/v4/public/depth", params={"symbol": "btc_usdt", "limit": 2}
    )
    assert len(result.result.bids) == 2


async def test_get_kline_success():
    client = _make_client(get_return=_fixture("spot_kline.json"))
    result = await client.get_kline("btc_usdt", "1h", 1)
    client._get.assert_called_once_with(
        "/v4/public/kline",
        params={"symbol": "btc_usdt", "interval": "1h", "limit": 1},
    )
    assert len(result.result) == 1
    assert result.result[0].open == "67000.00"


async def test_get_ticker_404_raises_not_found():
    client = _make_client(get_side_effect=XTNotFoundError(404, "Not found"))
    with pytest.raises(XTNotFoundError):
        await client.get_ticker("nonexistent_usdt")


async def test_get_ticker_500_raises_server_error():
    client = _make_client(get_side_effect=XTServerError(500, "Server error"))
    with pytest.raises(XTServerError):
        await client.get_ticker("btc_usdt")


async def test_get_ticker_429_raises_rate_limit():
    client = _make_client(get_side_effect=XTRateLimitError(429, "Rate limit exceeded"))
    with pytest.raises(XTRateLimitError):
        await client.get_ticker("btc_usdt")
