"""Volume indicators: OBV, VWAP."""

from __future__ import annotations

import pandas as pd


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume — cumulative volume signed by price direction."""
    delta = close.diff()
    direction = delta.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    direction.iloc[0] = 0  # first bar has no previous bar
    return (direction * volume).cumsum().rename("obv")


def vwap(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
) -> pd.Series:
    """Volume-Weighted Average Price (cumulative over the entire series)."""
    typical_price = (high + low + close) / 3.0
    cumulative_vol = volume.cumsum()
    return (typical_price * volume).cumsum() / cumulative_vol.replace(0.0, float("nan"))
