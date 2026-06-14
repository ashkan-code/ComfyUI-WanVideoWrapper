"""Signal quality: TrendScore and VolumeScore, both ∈ [0, 1]."""

from __future__ import annotations
import pandas as pd
from pivot.structure import MarketStructure


def compute_trend_score(df: pd.DataFrame, structure: MarketStructure) -> float:
    """
    TrendScore ∈ [0.0, 1.0]

    Components (60/40 weighted):
      Swing structure — HH+HL → 1.0 ... LH+LL → 0.0 (from detect_structure)
      EMA20 slope     — ±2% over 10 bars normalized to [0, 1]

    Reference values:
      1.0  strong uptrend
      0.7  weak uptrend
      0.5  range / neutral
      0.3  weak downtrend
      0.0  strong downtrend
    """
    # Swing structure component
    hh = structure.last_hh is not None
    hl = structure.last_hl is not None
    lh = structure.last_lh is not None
    ll = structure.last_ll is not None

    if   hh and hl:  struct_s = 1.00   # confirmed uptrend
    elif hh and ll:  struct_s = 0.65   # expanding range, slight up bias
    elif lh and hl:  struct_s = 0.35   # contracting range, slight down bias
    elif lh and ll:  struct_s = 0.00   # confirmed downtrend
    else:            struct_s = 0.50   # insufficient pivot data

    # EMA20 slope component
    closes = df["close"]
    ema20  = closes.ewm(span=20, adjust=False).mean()
    if len(ema20) >= 10:
        base  = float(ema20.iloc[-10])
        tip   = float(ema20.iloc[-1])
        slope = (tip - base) / base if base > 0 else 0.0
        # Normalize: +2% / 10 bars → 1.0; -2% / 10 bars → 0.0
        slope_s = max(0.0, min(1.0, (slope / 0.02 + 1.0) / 2.0))
    else:
        slope_s = 0.50

    return round(0.60 * struct_s + 0.40 * slope_s, 3)


def compute_volume_score(df: pd.DataFrame, window: int = 20) -> float:
    """
    VolumeScore ∈ [0, 1].

    last_vol / avg_vol(window):
      0.0× avg → 0.00   (no volume = low confidence)
      1.0× avg → 0.50   (normal)
      2.0× avg → 1.00   (elevated, capped)
    """
    vol = df["volume"]
    if len(vol) < 2 or "volume" not in df.columns:
        return 0.50
    avg  = float(vol.tail(window).mean())
    last = float(vol.iloc[-1])
    if avg <= 0:
        return 0.50
    return round(min(1.0, max(0.0, (last / avg) / 2.0)), 3)
