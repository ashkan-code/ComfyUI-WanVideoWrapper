"""Trend-following indicators: SMA, EMA, DEMA, WMA."""

from __future__ import annotations

import pandas as pd


def sma(series: pd.Series, period: int = 20) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int = 20) -> pd.Series:
    """Exponential Moving Average (Wilder / standard EMA, adjust=False)."""
    return series.ewm(span=period, adjust=False).mean()


def dema(series: pd.Series, period: int = 20) -> pd.Series:
    """Double Exponential Moving Average: 2*EMA(n) - EMA(EMA(n))."""
    e = ema(series, period)
    return 2 * e - ema(e, period)


def wma(series: pd.Series, period: int = 20) -> pd.Series:
    """Weighted Moving Average — linearly weighted, most recent bar has highest weight."""
    weights = list(range(1, period + 1))
    w_sum = sum(weights)

    def _apply(window: "pd.Series") -> float:
        return float((window * weights).sum() / w_sum)

    return series.rolling(window=period, min_periods=period).apply(_apply, raw=False)
