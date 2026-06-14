"""MCP tools for technical indicator computation."""

from __future__ import annotations

import logging
import math
from typing import Any

import pandas as pd

from indicators.registry import compute, list_indicators
from xt_mcp.clients.futures import XTFuturesClient
from xt_mcp.clients.spot import XTSpotClient
from xt_mcp.exceptions import XTMCPError

logger = logging.getLogger(__name__)

_spot: XTSpotClient | None = None
_futures: XTFuturesClient | None = None


def _get_spot() -> XTSpotClient:
    global _spot
    if _spot is None:
        _spot = XTSpotClient()
    return _spot


def _get_futures() -> XTFuturesClient:
    global _futures
    if _futures is None:
        _futures = XTFuturesClient()
    return _futures


def _error(exc: Exception) -> dict:
    logger.error("%s: %s", type(exc).__name__, exc)
    return {"error": True, "code": type(exc).__name__, "message": str(exc)}


def _clean(val: Any) -> Any:
    """Replace NaN/Inf with None so JSON serialization never fails."""
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return val


def _bars_to_df(bars: list, market: str) -> pd.DataFrame:
    rows = []
    for b in bars:
        rows.append(
            {
                "open_time": b.open_time,
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": float(b.volume),
            }
        )
    return pd.DataFrame(rows)


async def get_indicators(
    symbol: str,
    interval: str = "1h",
    indicators: list[str] | None = None,
    limit: int = 200,
    market: str = "spot",
) -> dict:
    """
    Compute technical indicators on the latest OHLCV candles from XT Exchange.

    Args:
        symbol:     Trading pair e.g. 'btc_usdt'
        interval:   Candle interval — '1m','5m','15m','1h','4h','1d'
        indicators: List of indicator specs. Each spec is 'name' or 'name:p1:p2'.
                    Defaults to ['rsi', 'macd', 'bb'].
                    Available: sma, ema, dema, wma, rsi, macd, stoch, bb, atr, obv, vwap
                    Examples: 'sma:50', 'rsi:7', 'bb:20:2', 'macd:12:26:9'
        limit:      Number of candles to fetch from the API (max 1500). More bars
                    improve indicator accuracy — use ≥200 for best results.
        market:     'spot' or 'futures'

    Returns:
        Dict with 'latest' (most recent bar + indicators) and 'bars' (last 20 bars),
        or an error envelope on failure.
    """
    if indicators is None:
        indicators = ["rsi", "macd", "bb"]

    try:
        # ── 1. Fetch candles ──────────────────────────────────────────────────
        if market == "spot":
            resp = await _get_spot().get_kline(symbol, interval, limit)
            bars = resp.result
        elif market == "futures":
            resp = await _get_futures().get_kline(symbol, interval, limit)
            bars = resp.result
        else:
            return _error(ValueError(f"Unknown market: {market!r}"))

        if not bars:
            return {
                "error": False,
                "symbol": symbol,
                "interval": interval,
                "market": market,
                "bars": [],
                "latest": {},
                "warnings": ["No candle data returned by API"],
            }

        df = _bars_to_df(bars, market)

        # ── 2. Compute indicators ─────────────────────────────────────────────
        result_df = df.copy()
        warnings: list[str] = []

        for spec in indicators:
            try:
                cols = compute(spec, df)
                for col_name, series in cols.items():
                    result_df[col_name] = series.values
            except ValueError as exc:
                warnings.append(str(exc))
                logger.warning("Indicator %r failed: %s", spec, exc)

        # ── 3. Serialise last 20 rows ─────────────────────────────────────────
        tail = result_df.tail(20)
        bars_out = [
            {k: _clean(v) for k, v in row.items()}
            for row in tail.to_dict(orient="records")
        ]

        return {
            "error": False,
            "symbol": symbol,
            "interval": interval,
            "market": market,
            "candles_fetched": len(bars),
            "bars_returned": len(bars_out),
            "indicators": indicators,
            "latest": bars_out[-1] if bars_out else {},
            "bars": bars_out,
            "warnings": warnings,
        }

    except XTMCPError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("Unexpected error in get_indicators")
        return _error(exc)


async def list_available_indicators() -> dict:
    """
    List all available technical indicators supported by get_indicators.

    Returns:
        Dict with 'indicators' list and usage examples.
    """
    return {
        "indicators": list_indicators(),
        "usage": (
            "Pass indicator specs as strings in the 'indicators' list. "
            "Format: 'name' (default params) or 'name:p1:p2' (custom params). "
            "Examples: 'sma:50', 'rsi:7', 'macd:12:26:9', 'bb:20:2', 'atr:14'"
        ),
        "examples": {
            "sma:50": "Simple Moving Average, period=50",
            "ema:20": "Exponential Moving Average, period=20",
            "rsi:14": "RSI, period=14",
            "macd:12:26:9": "MACD, fast=12, slow=26, signal=9",
            "bb:20:2": "Bollinger Bands, period=20, std=2.0",
            "atr:14": "Average True Range, period=14",
            "stoch:14:3": "Stochastic Oscillator, K=14, D=3",
            "obv": "On-Balance Volume",
            "vwap": "Volume-Weighted Average Price",
        },
    }
