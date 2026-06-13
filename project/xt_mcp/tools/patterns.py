"""MCP tool for candlestick pattern detection."""

from __future__ import annotations

import logging

from patterns.detector import PATTERN_BIAS, detect_all
from patterns.models import PatternOccurrence, PatternResult
from signals.engine import SignalEngine
from xt_mcp.exceptions import XTMCPError

logger = logging.getLogger(__name__)


def _error(exc: Exception) -> dict:
    logger.error("%s: %s", type(exc).__name__, exc)
    return {"error": True, "code": type(exc).__name__, "message": str(exc)}


async def detect_patterns(
    symbol: str,
    interval: str = "1h",
    market: str = "spot",
    lookback: int = 200,
    recent_bars: int = 30,
) -> dict:
    """
    Detect classic candlestick patterns in OHLCV data.

    Patterns detected:
    - doji              : body < 10 % of range (indecision)
    - hammer            : long lower shadow, small body (bullish reversal)
    - shooting_star     : long upper shadow, small body (bearish reversal)
    - bullish_engulfing : green body engulfs prior red body (bullish reversal)
    - bearish_engulfing : red body engulfs prior green body (bearish reversal)
    - morning_star      : three-bar bullish reversal (red → indecision → green)
    - evening_star      : three-bar bearish reversal (green → indecision → red)

    Args:
        symbol:      Trading pair e.g. 'btc_usdt'.
        interval:    Candle interval (default '1h').
        market:      'spot' or 'futures' (default 'spot').
        lookback:    Historical bars to analyse (default 200).
        recent_bars: Number of most-recent bars to include in occurrence list (default 30).

    Returns:
        Pattern counts over the full lookback plus occurrences in recent_bars.
    """
    try:
        engine = SignalEngine()
        _, df = await engine.run_with_df(
            symbol=symbol, interval=interval, strategy_name="rsi_reversal",
            market=market, lookback=min(lookback, 1000),
        )

        masks = detect_all(df)
        counts = {name: int(mask.sum()) for name, mask in masks.items()}

        # Collect occurrences in the most-recent window
        window = df.tail(recent_bars).reset_index(drop=True)
        occurrences: list[PatternOccurrence] = []
        for name, mask in masks.items():
            window_mask = mask[-len(window):]
            for i in range(len(window)):
                if window_mask[i]:
                    occurrences.append(PatternOccurrence(
                        open_time=int(window["open_time"].iloc[i]),
                        pattern=name,
                        close=float(window["close"].iloc[i]),
                        signal_bias=PATTERN_BIAS[name],
                    ))

        occurrences.sort(key=lambda x: x.open_time)

        result = PatternResult(
            symbol=symbol,
            interval=interval,
            market=market,
            lookback_bars=lookback,
            total_bars=len(df),
            patterns_found=counts,
            recent_occurrences=occurrences,
        )
        return {"error": False, **result.to_dict()}

    except XTMCPError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("detect_patterns failed")
        return _error(exc)
