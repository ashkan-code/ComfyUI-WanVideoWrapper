"""Realized volatility, ATR percentile, and volatility cone (pure numpy/pandas)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from regime.adx import compute_adx

# Bars per year for common intervals
_ANNUALIZATION: dict[str, int] = {
    "1m":  252 * 24 * 60,
    "5m":  252 * 24 * 12,
    "15m": 252 * 24 * 4,
    "30m": 252 * 24 * 2,
    "1h":  252 * 24,
    "2h":  252 * 12,
    "4h":  252 * 6,
    "8h":  252 * 3,
    "1d":  252,
    "1w":  52,
}

_DEFAULT_ANN = 252 * 24   # 1h fallback


def _ann_factor(interval: str) -> int:
    return _ANNUALIZATION.get(interval, _DEFAULT_ANN)


def realized_volatility(close: pd.Series, window: int, interval: str) -> pd.Series:
    """Log-return standard deviation annualised to % per year."""
    log_ret = np.log(close / close.shift(1))
    ann = _ann_factor(interval)
    return log_ret.rolling(window).std() * np.sqrt(ann) * 100.0


def current_hv(close: pd.Series, window: int, interval: str) -> float | None:
    """Most-recent annualised HV value, or None if insufficient data."""
    rv = realized_volatility(close, window, interval).dropna()
    return float(rv.iloc[-1]) if not rv.empty else None


def atr_percentile(df: pd.DataFrame, period: int = 14) -> float:
    """Percentile rank of the current ATR within its own history (0–100)."""
    adx_df = compute_adx(df, period=period)
    atr    = adx_df["atr"].dropna()
    if atr.empty:
        return 50.0
    cur = float(atr.iloc[-1])
    return float((atr <= cur).mean() * 100.0)


def volatility_regime(percentile: float) -> str:
    """Classify ATR percentile into a volatility regime label."""
    if percentile < 25:
        return "CALM"
    if percentile < 50:
        return "NORMAL"
    if percentile < 75:
        return "ELEVATED"
    return "HIGH"


def volatility_cone(
    close: pd.Series,
    windows: tuple[int, ...] = (5, 10, 21, 42, 63),
    interval: str = "1h",
) -> dict[str, dict]:
    """For each window compute percentile levels of rolling HV.

    Returns a dict keyed by window size with min/p25/p50/p75/max/current/percentile.
    """
    result: dict[str, dict] = {}
    ann = _ann_factor(interval)
    log_ret = np.log(close / close.shift(1))

    for w in windows:
        rv = (log_ret.rolling(w).std() * np.sqrt(ann) * 100.0).dropna()
        if len(rv) < 2:
            continue
        cur = float(rv.iloc[-1])
        result[str(w)] = {
            "window":     w,
            "min":        round(float(rv.min()), 2),
            "p25":        round(float(rv.quantile(0.25)), 2),
            "p50":        round(float(rv.quantile(0.50)), 2),
            "p75":        round(float(rv.quantile(0.75)), 2),
            "max":        round(float(rv.max()), 2),
            "current":    round(cur, 2),
            "percentile": round(float((rv <= cur).mean() * 100.0), 1),
        }
    return result
