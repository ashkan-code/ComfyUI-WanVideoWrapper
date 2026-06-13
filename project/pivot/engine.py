"""Pivot detection: High/Low pivots from OHLCV data."""

from __future__ import annotations
from dataclasses import dataclass
import pandas as pd


@dataclass
class Pivot:
    price:     float
    timestamp: int
    type:      str   # "HIGH" | "LOW"
    strength:  int   # window n
    timeframe: str
    bar_index: int


def detect_pivots(
    df: pd.DataFrame,
    timeframe: str,
    n: int = 3,
    max_pivots: int = 100,
) -> list[Pivot]:
    """
    Pivot High: High[i] == max(High[i-n : i+n+1])
    Pivot Low:  Low[i]  == min(Low[i-n  : i+n+1])
    Returns last max_pivots, newest first.
    """
    highs = df["high"].values
    lows  = df["low"].values
    times = df["open_time"].values
    pivots: list[Pivot] = []

    for i in range(n, len(df) - n):
        if highs[i] >= highs[i - n : i + n + 1].max():
            pivots.append(Pivot(float(highs[i]), int(times[i]), "HIGH", n, timeframe, i))
        if lows[i] <= lows[i - n : i + n + 1].min():
            pivots.append(Pivot(float(lows[i]),  int(times[i]), "LOW",  n, timeframe, i))

    pivots.sort(key=lambda p: p.timestamp, reverse=True)
    return pivots[:max_pivots]
