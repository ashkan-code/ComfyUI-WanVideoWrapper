"""MCP tools for volume profile, VWAP analysis, and divergence detection."""

from __future__ import annotations

import logging

from signals.engine import SignalEngine
from volume.divergence import detect_volume_divergence as _detect_div
from volume.profile import compute_volume_profile
from volume.vwap import compute_vwap
from xt_mcp.exceptions import XTMCPError

logger = logging.getLogger(__name__)


def _error(exc: Exception) -> dict:
    logger.error("%s: %s", type(exc).__name__, exc)
    return {"error": True, "code": type(exc).__name__, "message": str(exc)}


async def get_volume_profile(
    symbol: str,
    interval: str = "1h",
    market: str = "spot",
    lookback: int = 200,
    bins: int = 50,
) -> dict:
    """
    Compute a volume-at-price profile (market profile) for a symbol.

    Identifies:
    - POC  (Point of Control): price level with the highest traded volume.
    - VAH  (Value Area High) : upper bound of the 70 % value area.
    - VAL  (Value Area Low)  : lower bound of the 70 % value area.

    Price near the POC is a high-interest zone; breaks above VAH / below VAL
    often signal directional moves.

    Args:
        symbol:  Trading pair e.g. 'btc_usdt'.
        interval: Candle interval (default '1h').
        market:  'spot' or 'futures'.
        lookback: Historical bars to include (default 200).
        bins:    Number of price buckets in the histogram (default 50).

    Returns:
        POC, VAH, VAL, total_volume, value_area_pct, top_bins by volume.
    """
    try:
        if bins < 2:
            raise ValueError("bins must be >= 2")
        engine = SignalEngine()
        _, df = await engine.run_with_df(
            symbol=symbol, interval=interval,
            strategy_name="rsi_reversal", market=market,
            lookback=min(lookback, 1000),
        )
        result = compute_volume_profile(df, bins=bins)
        return {
            "error":    False,
            "symbol":   symbol,
            "interval": interval,
            "market":   market,
            "lookback": lookback,
            **result.to_dict(),
        }
    except ValueError as exc:
        return _error(exc)
    except XTMCPError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("get_volume_profile failed")
        return _error(exc)


async def get_vwap_analysis(
    symbol: str,
    interval: str = "1h",
    market: str = "spot",
    lookback: int = 200,
    std_multiplier: float = 2.0,
) -> dict:
    """
    Compute cumulative VWAP with volume-weighted standard-deviation bands.

    VWAP is anchored at the start of the lookback window. Bands:
    - ±1σ : normal trading range.
    - ±std_multiplier σ : extended / overextended territory.

    Price above upper band 2 → overextended long; below lower band 2 → oversold.

    Args:
        symbol:         Trading pair e.g. 'btc_usdt'.
        interval:       Candle interval (default '1h').
        market:         'spot' or 'futures'.
        lookback:       Historical bars (default 200).
        std_multiplier: Outer band width in standard deviations (default 2.0).

    Returns:
        Current VWAP, band levels, and price position relative to bands.
    """
    try:
        engine = SignalEngine()
        _, df = await engine.run_with_df(
            symbol=symbol, interval=interval,
            strategy_name="rsi_reversal", market=market,
            lookback=min(lookback, 1000),
        )
        result = compute_vwap(df, std_multiplier=std_multiplier)
        return {
            "error":    False,
            "symbol":   symbol,
            "interval": interval,
            "market":   market,
            "lookback": lookback,
            **result.to_dict(),
        }
    except XTMCPError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("get_vwap_analysis failed")
        return _error(exc)


async def detect_volume_divergence(
    symbol: str,
    interval: str = "1h",
    market: str = "spot",
    lookback: int = 300,
    window: int = 14,
    price_thresh: float = 2.0,
    vol_decline_thresh: float = 15.0,
) -> dict:
    """
    Detect bars where price direction and volume trend diverge.

    Two divergence types:
    - BEARISH           : price rising but volume declining → distribution, trend
                          may be weakening, potential reversal down.
    - BULLISH_EXHAUSTION: price falling but volume declining → selling drying up,
                          potential reversal up.

    Args:
        symbol:              Trading pair e.g. 'btc_usdt'.
        interval:            Candle interval (default '1h').
        market:              'spot' or 'futures'.
        lookback:            Historical bars (default 300).
        window:              Bars for price ROC and volume comparison (default 14).
        price_thresh:        Minimum price move % to qualify (default 2.0).
        vol_decline_thresh:  Volume must be this many % below baseline (default 15.0).

    Returns:
        List of divergence signals with timestamps, types, and magnitudes.
    """
    try:
        engine = SignalEngine()
        _, df = await engine.run_with_df(
            symbol=symbol, interval=interval,
            strategy_name="rsi_reversal", market=market,
            lookback=min(lookback, 1000),
        )
        signals = _detect_div(
            df,
            window=window,
            price_thresh=price_thresh / 100.0,
            vol_decline_thresh=vol_decline_thresh / 100.0,
        )
        return {
            "error":    False,
            "symbol":   symbol,
            "interval": interval,
            "market":   market,
            "window":   window,
            "total":    len(signals),
            "signals":  [s.to_dict() for s in signals[-30:]],
        }
    except XTMCPError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("detect_volume_divergence failed")
        return _error(exc)
