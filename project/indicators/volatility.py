"""Volatility indicators: Bollinger Bands, ATR."""

from __future__ import annotations

import pandas as pd


def bollinger_bands(
    series: pd.Series,
    period: int = 20,
    std: float = 2.0,
) -> pd.DataFrame:
    """Bollinger Bands — upper, middle (SMA), lower."""
    middle = series.rolling(window=period, min_periods=period).mean()
    std_dev = series.rolling(window=period, min_periods=period).std(ddof=1)
    return pd.DataFrame(
        {
            "bb_upper": middle + std * std_dev,
            "bb_middle": middle,
            "bb_lower": middle - std * std_dev,
        },
        index=series.index,
    )


def atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Average True Range using Wilder's smoothing."""
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()
