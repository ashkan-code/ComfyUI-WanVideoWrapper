"""Tests for XTFuturesClient — mocking _get() with AsyncMock."""

from __future__ import annotations

import json
import pathlib
from unittest.mock import AsyncMock

import pytest

from xt_mcp.clients.futures import XTFuturesClient
from xt_mcp.exceptions import XTNotFoundError, XTServerError
from xt_mcp.rate_limiter import RateLimiter

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class _NoopLimiter(RateLimiter):
    def __init__(self):
        pass

    async def acquire(self) -> None:
        pass


def _make_client(get_return=None, get_side_effect=None) -> XTFuturesClient:
    client = XTFuturesClient.__new__(XTFuturesClient)
    client._limiter = _NoopLimiter()
    if get_side_effect is not None:
        client._get = AsyncMock(side_effect=get_side_effect)
    else:
        client._get = AsyncMock(return_value=get_return)
    return client


async def test_get_symbols_success():
    client = _make_client(get_return=_fixture("futures_symbols.json"))
    result = await client.get_symbols()
    client._get.assert_called_once_with("/future/market/v1/public/symbol/detail")
    assert len(result.result) == 1
    assert result.result[0].symbol == "btc_usdt"


async def test_get_ticker_success():
    client = _make_client(get_return=_fixture("futures_ticker.json"))
    result = await client.get_ticker("btc_usdt")
    client._get.assert_called_once_with(
        "/future/market/v1/public/q/tickers", params={"symbol": "btc_usdt"}
    )
    assert result.return_code == 0


async def test_get_kline_success():
    client = _make_client(get_return=_fixture("futures_kline.json"))
    result = await client.get_kline("btc_usdt", "1h", 1)
    client._get.assert_called_once_with(
        "/future/market/v1/public/q/kline",
        params={"symbol": "btc_usdt", "interval": "1h", "limit": 1},
    )
    assert len(result.result) == 1
    assert result.result[0].close == "67300.0"


async def test_get_funding_rate_success():
    client = _make_client(get_return=_fixture("futures_funding.json"))
    result = await client.get_funding_rate("btc_usdt", limit=2)
    client._get.assert_called_once_with(
        "/future/market/v1/public/q/funding-rate-record",
        params={"symbol": "btc_usdt", "limit": 2},
    )
    assert len(result.result) == 2
    assert result.result[0].funding_rate == "0.0001"


async def test_get_open_interest_success():
    client = _make_client(get_return=_fixture("futures_oi.json"))
    result = await client.get_open_interest("btc_usdt")
    client._get.assert_called_once_with(
        "/future/market/v1/public/contract/open-interest",
        params={"symbol": "btc_usdt"},
    )
    assert result.result.open_interest == "12345.678"
    assert result.result.open_interest_usd == "830000000.00"


async def test_get_ticker_404_raises():
    client = _make_client(get_side_effect=XTNotFoundError(404, "Not found"))
    with pytest.raises(XTNotFoundError):
        await client.get_ticker("fake_usdt")


async def test_get_open_interest_500_raises():
    client = _make_client(get_side_effect=XTServerError(500, "Server error"))
    with pytest.raises(XTServerError):
        await client.get_open_interest("btc_usdt")
