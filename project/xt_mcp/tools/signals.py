"""MCP tools for signal generation."""

from __future__ import annotations

import logging

from signals.engine import SignalEngine
from signals.registry import list_strategies
from xt_mcp.exceptions import XTMCPError

logger = logging.getLogger(__name__)


def _error(exc: Exception) -> dict:
    logger.error("%s: %s", type(exc).__name__, exc)
    return {"error": True, "code": type(exc).__name__, "message": str(exc)}


async def run_strategy(
    symbol: str,
    strategy: str = "rsi_reversal",
    interval: str = "1h",
    market: str = "spot",
    lookback: int = 500,
) -> dict:
    """
    Run a signal generation strategy on recent OHLCV candles from XT Exchange.

    Fetches the latest candles, applies the selected strategy's rules, and
    returns the signals generated (BUY / SELL events).

    Args:
        symbol:   Trading pair e.g. 'btc_usdt'
        strategy: Strategy name — call list_strategies to see all options.
                  Built-in: rsi_reversal, ema_cross, macd_cross, bb_mean_revert,
                  volume_spike, combined_momentum, combined_full, rsi_aggressive,
                  ema_cross_50_200
        interval: Candle interval — '1m','5m','15m','1h','4h','1d'
        market:   'spot' or 'futures'
        lookback: Number of historical bars to analyse (max 1000).
                  More bars → more context for indicators. Recommended ≥ 200.

    Returns:
        Dict with 'signals' list (most recent 30), total count, and strategy info.
    """
    try:
        engine = SignalEngine()
        all_signals = await engine.run(
            symbol=symbol,
            interval=interval,
            strategy_name=strategy,
            market=market,
            lookback=lookback,
        )

        recent = all_signals[-30:] if len(all_signals) > 30 else all_signals
        latest = recent[-1].to_dict() if recent else None

        return {
            "error": False,
            "symbol": symbol,
            "interval": interval,
            "market": market,
            "strategy": strategy,
            "candles_analysed": lookback,
            "total_signals": len(all_signals),
            "latest_signal": latest,
            "signals": [s.to_dict() for s in recent],
        }

    except ValueError as exc:
        return _error(exc)
    except XTMCPError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("run_strategy failed")
        return _error(exc)


async def list_signal_strategies() -> dict:
    """
    List all available signal generation strategies.

    Returns:
        Dict with strategy names and descriptions.
    """
    descriptions = {
        "rsi_reversal":      "RSI(14) < 30 → BUY, > 70 → SELL (classic oversold/overbought)",
        "rsi_aggressive":    "RSI(14) < 40 → BUY, > 60 → SELL (tighter thresholds)",
        "ema_cross":         "EMA(9) crosses EMA(21) — golden/death cross",
        "ema_cross_50_200":  "EMA(50) crosses EMA(200) — major trend reversal",
        "macd_cross":        "MACD histogram sign change — momentum shift",
        "bb_mean_revert":    "Price breaks Bollinger Band(20,2) — mean reversion entry",
        "volume_spike":      "Volume > 2× average + price direction — breakout confirmation",
        "combined_momentum": "RSI + MACD + EMA cross — majority vote (3 rules)",
        "combined_full":     "All 5 rules — highest confidence, fewest signals",
    }
    names = list_strategies()
    return {
        "strategies": names,
        "descriptions": {n: descriptions.get(n, "") for n in names},
        "tip": (
            "Use 'combined_momentum' or 'combined_full' for higher-confidence signals. "
            "Use single-rule strategies for more frequent signals."
        ),
    }
