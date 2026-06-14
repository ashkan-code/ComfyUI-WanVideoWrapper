"""ADX + Directional Indicators computed from OHLCV (pure numpy/pandas)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _wilder_smooth(vals: np.ndarray, period: int) -> np.ndarray:
    """Wilder's smoothing for TR/DM: seed = SUM of first *period* values."""
    n = len(vals)
    result = np.full(n, np.nan)
    if n < period:
        return result
    result[period - 1] = np.nansum(vals[:period])
    factor = (period - 1) / period
    for i in range(period, n):
        prev = result[i - 1]
        cur  = vals[i]
        if np.isnan(prev) or np.isnan(cur):
            continue
        result[i] = prev * factor + cur
    return result


def _smooth_adx(dx: np.ndarray, period: int) -> np.ndarray:
    """ADX smoothing: seed = AVERAGE of first *period* DX values, then (p-1+1)/p."""
    n = len(dx)
    result = np.full(n, np.nan)
    # Find first run of `period` consecutive non-NaN values
    start = 0
    while start < n and np.isnan(dx[start]):
        start += 1
    if start + period > n:
        return result
    result[start + period - 1] = np.nanmean(dx[start: start + period])
    for i in range(start + period, n):
        prev = result[i - 1]
        cur  = dx[i]
        if np.isnan(prev) or np.isnan(cur):
            continue
        result[i] = (prev * (period - 1) + cur) / period
    return result


def compute_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Return DataFrame with columns: adx, di_plus, di_minus, atr.

    Uses Wilder smoothing throughout, matching the standard ADX definition.
    Requires columns: high, low, close (at least *2*period* rows for stability).
    """
    high  = df["high"].values.astype(float)
    low   = df["low"].values.astype(float)
    close = df["close"].values.astype(float)
    n = len(high)

    # True Range
    prev_close = np.roll(close, 1)
    prev_close[0] = np.nan
    tr = np.maximum.reduce([
        high - low,
        np.abs(high - prev_close),
        np.abs(low  - prev_close),
    ])
    tr[0] = np.nan

    # Directional Movement
    up_move   = high - np.roll(high, 1)
    down_move = np.roll(low, 1) - low
    up_move[0] = down_move[0] = np.nan

    dm_plus  = np.where((up_move > down_move) & (up_move > 0),   up_move,   0.0)
    dm_minus = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    dm_plus[0] = dm_minus[0] = np.nan

    # Wilder smooth
    atr_s   = _wilder_smooth(tr,       period)
    dmp_s   = _wilder_smooth(dm_plus,  period)
    dmm_s   = _wilder_smooth(dm_minus, period)

    with np.errstate(divide="ignore", invalid="ignore"):
        di_plus  = np.where(atr_s > 0, 100.0 * dmp_s / atr_s, np.nan)
        di_minus = np.where(atr_s > 0, 100.0 * dmm_s / atr_s, np.nan)
        di_sum   = di_plus + di_minus
        dx       = np.where(di_sum > 0, 100.0 * np.abs(di_plus - di_minus) / di_sum, np.nan)

    adx = _smooth_adx(np.nan_to_num(dx, nan=0.0), period)
    # Leading values remain NaN (set by _smooth_adx)

    atr_normalised = atr_s / period   # per-bar ATR (comparable across instruments)

    return pd.DataFrame(
        {"adx": adx, "di_plus": di_plus, "di_minus": di_minus, "atr": atr_normalised},
        index=df.index,
    )


def compute_atr_ratio(df: pd.DataFrame, short: int = 14, long: int = 50) -> pd.Series:
    """Return short-ATR / long-ATR ratio.  > 1 means above-average volatility."""
    adx_short = compute_adx(df, period=short)["atr"]
    adx_long  = compute_adx(df, period=long)["atr"]
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = adx_short / adx_long.replace(0.0, np.nan)
    return ratio.fillna(1.0)
