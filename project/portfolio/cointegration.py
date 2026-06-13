"""Cointegration detection via ADF test on the spread (pure numpy, no statsmodels)."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


# MacKinnon (1994) approximate critical values for ADF with constant, n → ∞
_CV_1PCT  = -3.43
_CV_5PCT  = -2.86
_CV_10PCT = -2.57


@dataclass
class CointPair:
    symbol_a: str
    symbol_b: str
    adf_stat: float
    p_level: str     # "<1%", "<5%", "<10%", "n/s"
    cointegrated: bool
    spread_mean: float
    spread_std: float
    hedge_ratio: float   # price_b = hedge_ratio * price_a + c  (OLS slope)

    def to_dict(self) -> dict:
        return {
            "symbol_a": self.symbol_a,
            "symbol_b": self.symbol_b,
            "adf_stat": round(self.adf_stat, 4),
            "p_level": self.p_level,
            "cointegrated": self.cointegrated,
            "spread_mean": round(self.spread_mean, 6),
            "spread_std": round(self.spread_std, 6),
            "hedge_ratio": round(self.hedge_ratio, 6),
        }


def _adf_stat(series: np.ndarray) -> float:
    """Augmented Dickey-Fuller test statistic (zero lags, with constant)."""
    y = np.asarray(series, dtype=float)
    n = len(y)
    if n < 10:
        return 0.0

    dy = np.diff(y)
    y_lag = y[:-1]

    X = np.column_stack([np.ones(n - 1), y_lag])
    try:
        coef, _, _, _ = np.linalg.lstsq(X, dy, rcond=None)
        resid = dy - X @ coef
        s2 = np.sum(resid ** 2) / max(n - 3, 1)
        cov = s2 * np.linalg.pinv(X.T @ X)
        se = math.sqrt(abs(float(cov[1, 1])))
        return float(coef[1]) / se if se > 1e-12 else 0.0
    except np.linalg.LinAlgError:
        return 0.0


def _p_level(stat: float) -> str:
    if stat < _CV_1PCT:
        return "<1%"
    if stat < _CV_5PCT:
        return "<5%"
    if stat < _CV_10PCT:
        return "<10%"
    return "n/s"


def analyze_pair(
    prices_a: pd.Series,
    prices_b: pd.Series,
    symbol_a: str = "A",
    symbol_b: str = "B",
    significance: str = "5%",
) -> CointPair:
    """Test if two price series are cointegrated.

    Fits OLS hedge ratio, computes residual spread, runs ADF on the spread.

    Args:
        prices_a, prices_b: Aligned close price Series (same length).
        significance:       Threshold for `cointegrated` flag: '1%'|'5%'|'10%'.
    """
    a = np.asarray(prices_a.dropna(), dtype=float)
    b = np.asarray(prices_b.dropna(), dtype=float)
    min_len = min(len(a), len(b))
    a, b = a[-min_len:], b[-min_len:]

    # OLS: b = hedge_ratio * a + intercept
    X = np.column_stack([np.ones(len(a)), a])
    try:
        coef, _, _, _ = np.linalg.lstsq(X, b, rcond=None)
    except np.linalg.LinAlgError:
        coef = np.array([0.0, 1.0])

    hedge_ratio = float(coef[1])
    spread = b - hedge_ratio * a

    stat = _adf_stat(spread)
    p_lvl = _p_level(stat)

    thresholds = {"1%": _CV_1PCT, "5%": _CV_5PCT, "10%": _CV_10PCT}
    cutoff = thresholds.get(significance, _CV_5PCT)
    cointegrated = stat < cutoff

    return CointPair(
        symbol_a=symbol_a,
        symbol_b=symbol_b,
        adf_stat=round(stat, 4),
        p_level=p_lvl,
        cointegrated=cointegrated,
        spread_mean=float(np.mean(spread)),
        spread_std=float(np.std(spread)),
        hedge_ratio=hedge_ratio,
    )


def find_cointegrated_pairs(
    price_series: dict[str, pd.Series],
    significance: str = "5%",
) -> list[CointPair]:
    """Test all unique pairs and return results sorted by ADF stat (most stationary first)."""
    symbols = list(price_series.keys())
    results: list[CointPair] = []

    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            a, b = symbols[i], symbols[j]
            pair = analyze_pair(
                price_series[a], price_series[b],
                symbol_a=a, symbol_b=b,
                significance=significance,
            )
            results.append(pair)

    results.sort(key=lambda p: p.adf_stat)  # most negative = most stationary first
    return results
