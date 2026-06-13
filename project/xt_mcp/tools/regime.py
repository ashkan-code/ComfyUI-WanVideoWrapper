"""MCP tools for market regime detection."""

from __future__ import annotations

import logging

from regime.classifier import RegimeClassifier
from regime.models import Regime
from signals.engine import SignalEngine
from signals.registry import get_strategy
from xt_mcp.exceptions import XTMCPError

logger = logging.getLogger(__name__)


def _error(exc: Exception) -> dict:
    logger.error("%s: %s", type(exc).__name__, exc)
    return {"error": True, "code": type(exc).__name__, "message": str(exc)}


async def detect_regime(
    symbol: str,
    interval: str = "1h",
    market: str = "spot",
    lookback: int = 300,
    adx_period: int = 14,
    trend_threshold: float = 25.0,
    range_threshold: float = 20.0,
    vol_spike_threshold: float = 1.5,
    history_bars: int = 20,
) -> dict:
    """
    Detect the current market regime for a symbol using ADX and ATR volatility ratio.

    Classifies each bar into one of four regimes:
    - TRENDING_UP   : ADX > trend_threshold AND DI+ > DI-  → momentum strategies
    - TRENDING_DOWN : ADX > trend_threshold AND DI- > DI+  → avoid longs
    - RANGING       : ADX < range_threshold → mean-reversion strategies
    - VOLATILE      : short-term ATR > vol_spike_threshold × long-term ATR → reduce size
    - UNKNOWN       : transitional zone

    Args:
        symbol:              Trading pair e.g. 'btc_usdt'
        interval:            Candle interval: '1m','5m','15m','1h','4h','1d'
        market:              'spot' or 'futures'
        lookback:            Historical bars (min ~100, recommended 300+).
        adx_period:          ADX smoothing period (default 14).
        trend_threshold:     ADX level above which market is trending (default 25).
        range_threshold:     ADX level below which market is ranging (default 20).
        vol_spike_threshold: ATR ratio above which market is volatile (default 1.5).
        history_bars:        Recent bars to include in the response (default 20).

    Returns:
        Current regime with ADX/DI+/DI- values, dominant regime over lookback,
        distribution across all regimes, and recent bar history.
    """
    try:
        engine = SignalEngine()
        _, df = await engine.run_with_df(
            symbol=symbol,
            interval=interval,
            strategy_name="rsi_reversal",
            market=market,
            lookback=lookback,
        )

        classifier = RegimeClassifier(
            adx_period=adx_period,
            trend_threshold=trend_threshold,
            range_threshold=range_threshold,
            vol_spike_threshold=vol_spike_threshold,
        )
        result = classifier.classify(df, symbol=symbol, interval=interval, market=market)

        return {"error": False, **result.to_dict(history_bars=history_bars)}

    except ValueError as exc:
        return _error(exc)
    except XTMCPError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("detect_regime failed")
        return _error(exc)


async def regime_filtered_signals(
    symbol: str,
    strategy: str = "rsi_reversal",
    interval: str = "1h",
    market: str = "spot",
    lookback: int = 500,
    allowed_regimes: list[str] | None = None,
    adx_period: int = 14,
    trend_threshold: float = 25.0,
    range_threshold: float = 20.0,
    vol_spike_threshold: float = 1.5,
) -> dict:
    """
    Generate signals filtered to only those occurring in favourable market regimes.

    Combines signal generation and regime detection: signals are discarded when
    the market regime at that bar is not in *allowed_regimes*.

    Default allowed regimes per strategy type:
    - Trend-following (ema_cross, macd_cross): TRENDING_UP, TRENDING_DOWN
    - Mean-reversion (rsi_reversal, bb_mean_revert): RANGING
    - Combined: all except VOLATILE

    Args:
        symbol:          Trading pair e.g. 'btc_usdt'
        strategy:        Strategy name — see list_signal_strategies.
        interval:        Candle interval.
        market:          'spot' or 'futures'
        lookback:        Historical bars (max 1000).
        allowed_regimes: List of regime names to keep signals from.
                         e.g. ["TRENDING_UP", "TRENDING_DOWN"]
                         If None, uses sensible defaults per strategy.
        adx_period:      ADX period (default 14).
        trend_threshold: ADX trending threshold (default 25).
        range_threshold: ADX ranging threshold (default 20).
        vol_spike_threshold: ATR ratio volatile threshold (default 1.5).

    Returns:
        Filtered signals, regime at each signal bar, total vs filtered counts.
    """
    try:
        get_strategy(strategy)   # validate early

        if allowed_regimes is None:
            allowed_regimes = _default_regimes(strategy)

        allowed = {Regime(r) for r in allowed_regimes}

        engine = SignalEngine()
        signals, df = await engine.run_with_df(
            symbol=symbol,
            interval=interval,
            strategy_name=strategy,
            market=market,
            lookback=lookback,
        )

        classifier = RegimeClassifier(
            adx_period=adx_period,
            trend_threshold=trend_threshold,
            range_threshold=range_threshold,
            vol_spike_threshold=vol_spike_threshold,
        )

        try:
            regime_result = classifier.classify(df, symbol=symbol, interval=interval, market=market)
        except ValueError:
            # Not enough bars for regime — return unfiltered
            return {
                "error": False,
                "symbol": symbol, "strategy": strategy,
                "interval": interval, "market": market,
                "total_signals": len(signals),
                "filtered_signals": len(signals),
                "regime_filter_applied": False,
                "signals": [s.to_dict() for s in signals[-30:]],
            }

        regime_map = {b.open_time: b.regime for b in regime_result.history}

        filtered = [
            s for s in signals
            if regime_map.get(s.timestamp, Regime.UNKNOWN) in allowed
        ]

        enriched = []
        for s in filtered[-30:]:
            d = s.to_dict()
            d["regime"] = regime_map.get(s.timestamp, Regime.UNKNOWN).value
            enriched.append(d)

        return {
            "error": False,
            "symbol": symbol,
            "strategy": strategy,
            "interval": interval,
            "market": market,
            "allowed_regimes": [r.value for r in allowed],
            "current_regime": regime_result.current_regime.value,
            "total_signals": len(signals),
            "filtered_signals": len(filtered),
            "regime_filter_applied": True,
            "signals": enriched,
        }

    except ValueError as exc:
        return _error(exc)
    except XTMCPError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("regime_filtered_signals failed")
        return _error(exc)


_TREND_FOLLOWING   = {"ema_cross", "ema_cross_50_200", "macd_cross"}
_MEAN_REVERSION    = {"rsi_reversal", "rsi_aggressive", "bb_mean_revert"}


def _default_regimes(strategy: str) -> list[str]:
    if strategy in _TREND_FOLLOWING:
        return ["TRENDING_UP", "TRENDING_DOWN"]
    if strategy in _MEAN_REVERSION:
        return ["RANGING"]
    return ["TRENDING_UP", "TRENDING_DOWN", "RANGING", "UNKNOWN"]
