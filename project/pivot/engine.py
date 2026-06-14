"""Pivot detection: High/Low pivots from OHLCV data."""

from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd


@dataclass
class Pivot:
    price:     float
    timestamp: int
    type:      str   # "HIGH" | "LOW"
    strength:  int   # window n
    timeframe: str
    bar_index: int
    rejection: float = 0.0


def _atr14(highs, lows, closes, period: int = 14) -> float:
    if len(closes) < period + 1:
        return float(np.mean(highs - lows))
    tr = np.maximum(highs[1:] - lows[1:],
         np.maximum(np.abs(highs[1:] - closes[:-1]),
                    np.abs(lows[1:] - closes[:-1])))
    return max(1e-9, float(np.mean(tr[-period:])))


def detect_pivots(
    df: pd.DataFrame,
    timeframe: str,
    n: int = 3,
    max_pivots: int = 100,
    atr: float = 0.0,
) -> list[Pivot]:
    """
    Pivot High: High[i] == max(High[i-n : i+n+1])
    Pivot Low:  Low[i]  == min(Low[i-n  : i+n+1])
    Returns last max_pivots, newest first.
    """
    highs = df["high"].values
    lows  = df["low"].values
    times = df["open_time"].values
    closes = df["close"].values

    if atr == 0.0:
        atr = _atr14(highs, lows, closes)

    pivots: list[Pivot] = []

    for i in range(n, len(df) - n):
        if highs[i] >= highs[i - n : i + n + 1].max():
            if atr > 0:
                adj = (np.mean(highs[max(0, i-n):i]) + np.mean(highs[i+1:i+n+1])) / 2.0
                rej = min(1.0, max(0.0, (highs[i] - adj) / atr / 2.0))
            else:
                rej = 0.0
            pivots.append(Pivot(float(highs[i]), int(times[i]), "HIGH", n, timeframe, i, rejection=rej))
        if lows[i] <= lows[i - n : i + n + 1].min():
            if atr > 0:
                adj = (np.mean(lows[max(0, i-n):i]) + np.mean(lows[i+1:i+n+1])) / 2.0
                rej = min(1.0, max(0.0, (adj - lows[i]) / atr / 2.0))
            else:
                rej = 0.0
            pivots.append(Pivot(float(lows[i]),  int(times[i]), "LOW",  n, timeframe, i, rejection=rej))

    pivots.sort(key=lambda p: p.timestamp, reverse=True)
    return pivots[:max_pivots]
