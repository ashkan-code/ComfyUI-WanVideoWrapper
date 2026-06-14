"""Tests for Pydantic model parsing, aliases, and validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from xt_mcp.models.common import Interval, Market
from xt_mcp.models.futures import (
    FundingRateRecord,
    FundingRateResponse,
    FuturesKlineBar,
    FuturesKlineResponse,
    OpenInterestResponse,
)
from xt_mcp.models.spot import (
    SpotDepthResponse,
    SpotKlineBar,
    SpotKlineResponse,
    SpotSymbol,
    SpotSymbolListResponse,
    SpotTicker,
    SpotTickerResponse,
)


# --- Market enum ---

def test_market_enum_spot():
    assert Market("spot") == Market.SPOT


def test_market_enum_futures():
    assert Market("futures") == Market.FUTURES


def test_interval_enum_values():
    assert Interval.H1 == "1h"
    assert Interval.D1 == "1d"


# --- Spot models ---

def test_spot_symbol_alias_parsing():
    raw = {
        "symbol": "btc_usdt",
        "state": "ONLINE",
        "baseCurrency": "btc",
        "quoteCurrency": "usdt",
        "pricePrecision": 2,
        "quantityPrecision": 6,
    }
    sym = SpotSymbol.model_validate(raw)
    assert sym.symbol == "btc_usdt"
    assert sym.base_currency == "btc"
    assert sym.quote_currency == "usdt"
    assert sym.price_precision == 2


def test_spot_ticker_alias_parsing():
    raw = {
        "s": "btc_usdt",
        "p": "67234.50",
        "o": "65000.00",
        "h": "68000.00",
        "l": "64500.00",
        "v": "12345.678",
        "a": "823456789.00",
        "cr": "3.44",
        "t": 1700000000000,
    }
    ticker = SpotTicker.model_validate(raw)
    assert ticker.symbol == "btc_usdt"
    assert ticker.last_price == "67234.50"
    assert ticker.high_price == "68000.00"
    assert ticker.timestamp == 1700000000000


def test_spot_kline_bar_alias_parsing():
    raw = {
        "t": 1700000000000,
        "o": "67000.00",
        "h": "67500.00",
        "l": "66800.00",
        "c": "67234.50",
        "v": "123.456",
        "a": "8234567.00",
        "T": 1700003600000,
    }
    bar = SpotKlineBar.model_validate(raw)
    assert bar.open_time == 1700000000000
    assert bar.open == "67000.00"
    assert bar.close == "67234.50"
    assert bar.volume == "123.456"


def test_spot_depth_response():
    raw = {
        "rc": "0",
        "result": {
            "bids": [["67230.00", "0.5"]],
            "asks": [["67235.00", "0.8"]],
            "t": 1700000000000,
        },
    }
    resp = SpotDepthResponse.model_validate(raw)
    assert resp.result.bids[0] == ["67230.00", "0.5"]


def test_spot_symbol_list_response():
    raw = {
        "rc": "0",
        "result": [
            {"symbol": "btc_usdt", "state": "ONLINE", "baseCurrency": "btc",
             "quoteCurrency": "usdt", "pricePrecision": 2, "quantityPrecision": 6}
        ],
    }
    resp = SpotSymbolListResponse.model_validate(raw)
    assert len(resp.result) == 1
    assert resp.result[0].symbol == "btc_usdt"


# --- Futures models ---

def test_futures_kline_bar_alias_parsing():
    raw = {
        "t": 1700000000000,
        "o": "67000.0",
        "h": "67500.0",
        "l": "66800.0",
        "c": "67300.0",
        "v": "456.78",
        "a": "30654321.0",
    }
    bar = FuturesKlineBar.model_validate(raw)
    assert bar.open_time == 1700000000000
    assert bar.close == "67300.0"


def test_funding_rate_alias_parsing():
    raw = {
        "symbol": "btc_usdt",
        "fundingRate": "0.0001",
        "settleTime": 1700000000000,
        "collectionInternal": 28800,
    }
    record = FundingRateRecord.model_validate(raw)
    assert record.funding_rate == "0.0001"
    assert record.settle_time == 1700000000000


def test_funding_rate_response():
    raw = {
        "returnCode": 0,
        "result": [
            {"symbol": "btc_usdt", "fundingRate": "0.0001",
             "settleTime": 1700000000000, "collectionInternal": 28800}
        ],
    }
    resp = FundingRateResponse.model_validate(raw)
    assert len(resp.result) == 1
    assert resp.result[0].funding_rate == "0.0001"


def test_open_interest_response():
    raw = {
        "returnCode": 0,
        "result": {
            "symbol": "btc_usdt",
            "openInterest": "12345.678",
            "openInterestUsd": "830000000.00",
            "time": 1700000000000,
        },
    }
    resp = OpenInterestResponse.model_validate(raw)
    assert resp.result.open_interest == "12345.678"
    assert resp.result.timestamp == 1700000000000
