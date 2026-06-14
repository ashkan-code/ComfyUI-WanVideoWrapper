"""Market regime detection: TRENDING | RANGING | HIGH_VOL | LOW_VOL."""

from __future__ import annotations
import numpy as np
import pandas as pd
from pivot.cluster import atr14


# Dynamic probability threshold adjustments per regime
_PROB_ADJ: dict[str, float] = {
    "TRENDING": 0.00,   # trend supports S/R plays — no change
    "RANGING":  +0.10,  # choppy market — require higher signal quality
    "HIGH_VOL": +0.05,  # noisy price action — slightly stricter
    "LOW_VOL":  -0.05,  # deliberate moves — can relax threshold
}

# Score penalty multipliers (applied to cluster score after calculation)
_SCORE_MULT: dict[str, float] = {
    "TRENDING": 1.00,
    "RANGING":  0.85,
    "HIGH_VOL": 0.80,
    "LOW_VOL":  0.90,
}


def detect_regime(df: pd.DataFrame) -> str:
    """
    Classify market regime using two independent signals:

    Volatility ratio (ATR_current / ATR_median_50bar):
      > 1.5  → HIGH_VOL
      < 0.7  → LOW_VOL

    Displacement (20-bar price move in ATR units):
      > 3.0  → TRENDING
      else   → RANGING
    """
    if len(df) < 20:
        return "RANGING"

    atr_c = atr14(df)
    if atr_c == 0:
        return "RANGING"

    # Rolling True Range for median comparison (last 50 bars)
    n_look  = min(50, len(df) - 1)
    h       = df["high"].values[-n_look:]
    l       = df["low"].values[-n_look:]
    c_prev  = df["close"].values[-(n_look + 1):-1]
    trs     = np.maximum(h - l, np.maximum(np.abs(h - c_prev), np.abs(l - c_prev)))
    atr_med = float(np.median(trs)) if len(trs) > 0 else atr_c
    vol_ratio = atr_c / atr_med if atr_med > 0 else 1.0

    # 20-bar displacement
    n_disp   = min(20, len(df))
    disp_atr = abs(float(df["close"].iloc[-1]) - float(df["close"].iloc[-n_disp])) / atr_c

    if vol_ratio > 1.5:
        return "HIGH_VOL"
    if vol_ratio < 0.70:
        return "LOW_VOL"
    if disp_atr > 3.0:
        return "TRENDING"
    return "RANGING"


def regime_min_prob(regime: str, base_prob: float) -> float:
    """Adjust probability threshold dynamically based on regime."""
    adj = _PROB_ADJ.get(regime, 0.0)
    return round(max(0.50, min(0.90, base_prob + adj)), 2)


def regime_score_mult(regime: str) -> float:
    """Score multiplier applied after cluster scoring to reflect regime quality."""
    return _SCORE_MULT.get(regime, 1.0)
