"""MCP tools for realized volatility metrics and volatility cone."""

from __future__ import annotations

import logging

from signals.engine import SignalEngine
from volatility.metrics import (
    atr_percentile,
    current_hv,
    volatility_cone,
    volatility_regime,
)
from xt_mcp.exceptions import XTMCPError

logger = logging.getLogger(__name__)


def _error(exc: Exception) -> dict:
    logger.error("%s: %s", type(exc).__name__, exc)
    return {"error": True, "code": type(exc).__name__, "message": str(exc)}


async def get_volatility_metrics(
    symbol: str,
    interval: str = "1h",
    market: str = "spot",
    lookback: int = 300,
    atr_period: int = 14,
) -> dict:
    """
    Compute realized volatility and ATR-based volatility metrics for a symbol.

    Returns:
    - Realized HV (annualised %) at 7-bar, 14-bar, 30-bar, and 60-bar windows.
    - Current ATR percentile rank within its own lookback history.
    - Volatility regime: CALM / NORMAL / ELEVATED / HIGH.

    Args:
        symbol:     Trading pair e.g. 'btc_usdt'.
        interval:   Candle interval (default '1h').
        market:     'spot' or 'futures'.
        lookback:   Historical bars (min 100, default 300).
        atr_period: ATR smoothing period (default 14).

    Returns:
        Multi-window realized volatility, ATR percentile, and regime label.
    """
    try:
        engine = SignalEngine()
        _, df = await engine.run_with_df(
            symbol=symbol, interval=interval,
            strategy_name="rsi_reversal", market=market,
            lookback=min(lookback, 1000),
        )
        close = df["close"]

        hv: dict[str, float | None] = {}
        for w in (7, 14, 30, 60):
            v = current_hv(close, w, interval)
            hv[f"{w}bar"] = round(v, 2) if v is not None else None

        atr_pct   = atr_percentile(df, period=atr_period)
        regime    = volatility_regime(atr_pct)

        return {
            "error":         False,
            "symbol":        symbol,
            "interval":      interval,
            "market":        market,
            "realized_hv":   hv,
            "atr_percentile": round(atr_pct, 1),
            "volatility_regime": regime,
        }
    except XTMCPError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("get_volatility_metrics failed")
        return _error(exc)


async def get_volatility_cone(
    symbol: str,
    interval: str = "1h",
    market: str = "spot",
    lookback: int = 500,
) -> dict:
    """
    Compute a volatility cone: percentile distribution of realized HV at multiple horizons.

    For each window [5, 10, 21, 42, 63 bars], shows whether current volatility
    is historically low (< p25), normal (p25–p75), or high (> p75).

    Args:
        symbol:   Trading pair e.g. 'btc_usdt'.
        interval: Candle interval (default '1h').
        market:   'spot' or 'futures'.
        lookback: Historical bars (default 500, min 200 recommended).

    Returns:
        Per-window cone: min, p25, p50, p75, max, current, percentile.
    """
    try:
        engine = SignalEngine()
        _, df = await engine.run_with_df(
            symbol=symbol, interval=interval,
            strategy_name="rsi_reversal", market=market,
            lookback=min(lookback, 1000),
        )
        cone = volatility_cone(df["close"], interval=interval)
        return {
            "error":    False,
            "symbol":   symbol,
            "interval": interval,
            "market":   market,
            "cone":     cone,
        }
    except XTMCPError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("get_volatility_cone failed")
        return _error(exc)
