"""MCP tool for multi-timeframe analysis."""

from __future__ import annotations

import logging

from mtf.analyzer import MTFAnalyzer
from xt_mcp.exceptions import XTMCPError

logger = logging.getLogger(__name__)

_DEFAULT_TIMEFRAMES = ["15m", "1h", "4h", "1d"]


def _error(exc: Exception) -> dict:
    logger.error("%s: %s", type(exc).__name__, exc)
    return {"error": True, "code": type(exc).__name__, "message": str(exc)}


async def analyze_multi_timeframe(
    symbol: str,
    timeframes: list[str] | None = None,
    strategy: str = "rsi_reversal",
    market: str = "spot",
) -> dict:
    """
    Analyse market regime and signals across multiple timeframes simultaneously.

    Computes a confluence score (0–100) measuring how unanimously the chosen
    timeframes agree on market direction:
    - BULLISH_ALIGNED   : all timeframes trending up (score = 100).
    - BEARISH_ALIGNED   : all timeframes trending down (score = 100).
    - BULLISH_MAJORITY  : ≥ 50 % of timeframes trending up.
    - BEARISH_MAJORITY  : ≥ 50 % of timeframes trending down.
    - RANGING           : no timeframe shows a trend.
    - MIXED             : conflicting signals.

    Args:
        symbol:     Trading pair e.g. 'btc_usdt'.
        timeframes: List of intervals to scan (default ['15m','1h','4h','1d']).
        strategy:   Signal strategy to run on each timeframe (default 'rsi_reversal').
        market:     'spot' or 'futures' (default 'spot').

    Returns:
        Per-timeframe snapshots plus confluence_score, trend_alignment, and recommendation.
    """
    try:
        tfs = timeframes if timeframes is not None else _DEFAULT_TIMEFRAMES
        if not tfs:
            raise ValueError("timeframes must be a non-empty list")

        analyzer = MTFAnalyzer()
        result = await analyzer.analyze(symbol, tfs, strategy=strategy, market=market)
        return {"error": False, **result.to_dict()}

    except ValueError as exc:
        return _error(exc)
    except XTMCPError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("analyze_multi_timeframe failed")
        return _error(exc)
