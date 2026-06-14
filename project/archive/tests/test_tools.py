"""Integration tests for MCP tool functions.

Clients are injected with AsyncMock-backed _get methods.
This tests the tool → client → Pydantic model → dict serialization pipeline.
"""

from __future__ import annotations

import json
import pathlib
from unittest.mock import AsyncMock

import pytest

import xt_mcp.tools.market as market_module
import xt_mcp.tools.derivatives as derivatives_module
from xt_mcp.clients.spot import XTSpotClient
from xt_mcp.clients.futures import XTFuturesClient
from xt_mcp.exceptions import XTNotFoundError
from xt_mcp.rate_limiter import RateLimiter

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class _NoopLimiter(RateLimiter):
    def __init__(self):
        pass

    async def acquire(self) -> None:
        pass


def _mock_spot(fixture_name: str) -> XTSpotClient:
    c = XTSpotClient.__new__(XTSpotClient)
    c._limiter = _NoopLimiter()
    c._get = AsyncMock(return_value=_fixture(fixture_name))
    return c


def _mock_futures(fixture_name: str) -> XTFuturesClient:
    c = XTFuturesClient.__new__(XTFuturesClient)
    c._limiter = _NoopLimiter()
    c._get = AsyncMock(return_value=_fixture(fixture_name))
    return c


def _mock_spot_error(exc: Exception) -> XTSpotClient:
    c = XTSpotClient.__new__(XTSpotClient)
    c._limiter = _NoopLimiter()
    c._get = AsyncMock(side_effect=exc)
    return c


def _inject(spot=None, futures=None):
    if spot is not None:
        market_module._spot = spot
    if futures is not None:
        market_module._futures = futures
        derivatives_module._futures = futures


@pytest.fixture(autouse=True)
def reset_clients():
    """Reset tool module singletons before and after each test."""
    market_module._spot = None
    market_module._futures = None
    derivatives_module._futures = None
    yield
    market_module._spot = None
    market_module._futures = None
    derivatives_module._futures = None


async def test_get_symbols_spot():
    _inject(spot=_mock_spot("spot_symbols.json"))
    result = await market_module.get_symbols("spot")
    assert "result" in result
    assert len(result["result"]) == 2


async def test_get_symbols_futures():
    _inject(futures=_mock_futures("futures_symbols.json"))
    result = await market_module.get_symbols("futures")
    assert "result" in result


async def test_get_ticker_spot():
    _inject(spot=_mock_spot("spot_ticker.json"))
    result = await market_module.get_ticker("btc_usdt", "spot")
    assert result.get("rc") == "0"
    assert "error" not in result


async def test_get_ticker_futures():
    _inject(futures=_mock_futures("futures_ticker.json"))
    result = await market_module.get_ticker("btc_usdt", "futures")
    assert result.get("return_code") == 0


async def test_get_orderbook():
    _inject(spot=_mock_spot("spot_depth.json"))
    result = await market_module.get_orderbook("btc_usdt", 2)
    assert "result" in result


async def test_get_ohlcv_spot():
    _inject(spot=_mock_spot("spot_kline.json"))
    result = await market_module.get_ohlcv("btc_usdt", "1h", 1, "spot")
    assert "result" in result
    assert len(result["result"]) == 1


async def test_get_ohlcv_futures():
    _inject(futures=_mock_futures("futures_kline.json"))
    result = await market_module.get_ohlcv("btc_usdt", "1h", 1, "futures")
    assert "result" in result


async def test_get_market_info_found():
    _inject(spot=_mock_spot("spot_symbols.json"))
    result = await market_module.get_market_info("btc_usdt", "spot")
    assert result["symbol"] == "btc_usdt"
    assert result["info"] is not None


async def test_get_market_info_not_found_returns_none():
    _inject(spot=_mock_spot("spot_symbols.json"))
    result = await market_module.get_market_info("xyz_usdt", "spot")
    assert result["info"] is None


async def test_get_funding_rates():
    _inject(futures=_mock_futures("futures_funding.json"))
    result = await derivatives_module.get_funding_rates("btc_usdt", 2)
    assert "result" in result
    assert len(result["result"]) == 2


async def test_get_open_interest():
    _inject(futures=_mock_futures("futures_oi.json"))
    result = await derivatives_module.get_open_interest("btc_usdt")
    assert "result" in result


async def test_tool_error_returns_error_dict():
    """XTNotFoundError from client is caught and returned as error envelope."""
    _inject(spot=_mock_spot_error(XTNotFoundError(404, "Symbol not found")))
    result = await market_module.get_ticker("fake_usdt", "spot")
    assert result.get("error") is True
    assert result.get("code") == "XTNotFoundError"
    assert "message" in result
