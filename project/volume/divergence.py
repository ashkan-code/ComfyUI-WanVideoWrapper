"""Volume divergence detection: rising price with falling volume (distribution)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from volume.models import DivergenceSignal


def detect_volume_divergence(
    df: pd.DataFrame,
    window: int = 14,
    price_thresh: float = 0.02,
    vol_decline_thresh: float = 0.15,
) -> list[DivergenceSignal]:
    """Detect bars where price and volume trends disagree.

    Compares the *window*-bar price change against the ratio of the
    short-term average volume to the longer-term average volume.

    Signals:
    - BEARISH           : price up > price_thresh% but volume declining
                          (distribution — trend may be weakening).
    - BULLISH_EXHAUSTION: price down > price_thresh% but volume declining
                          (selling is drying up — potential reversal).

    Args:
        df:                OHLCV DataFrame.
        window:            Lookback for price ROC (default 14).
        price_thresh:      Minimum absolute price change to qualify (default 2 %).
        vol_decline_thresh: Volume must be this much below baseline (default 15 %).

    Returns:
        List of DivergenceSignal ordered by open_time.
    """
    close  = df["close"]
    volume = df["volume"]

    price_roc    = close.pct_change(window)
    short_vol    = volume.rolling(window).mean()
    baseline_vol = volume.rolling(window * 3).mean()

    signals: list[DivergenceSignal] = []
    for i in range(window * 3, len(df)):
        p_roc   = price_roc.iloc[i]
        sv      = short_vol.iloc[i]
        bv      = baseline_vol.iloc[i]
        if np.isnan(p_roc) or np.isnan(sv) or np.isnan(bv) or bv == 0:
            continue

        vol_ratio = sv / bv   # < 1.0 means volume is below baseline

        if p_roc > price_thresh and vol_ratio < (1.0 - vol_decline_thresh):
            signals.append(DivergenceSignal(
                open_time=int(df["open_time"].iloc[i]),
                divergence_type="BEARISH",
                price_change_pct=round(p_roc * 100, 2),
                volume_ratio=round(vol_ratio, 3),
            ))
        elif p_roc < -price_thresh and vol_ratio < (1.0 - vol_decline_thresh):
            signals.append(DivergenceSignal(
                open_time=int(df["open_time"].iloc[i]),
                divergence_type="BULLISH_EXHAUSTION",
                price_change_pct=round(p_roc * 100, 2),
                volume_ratio=round(vol_ratio, 3),
            ))

    return signals
