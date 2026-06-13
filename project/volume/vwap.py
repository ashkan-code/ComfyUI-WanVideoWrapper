"""Cumulative VWAP with volume-weighted standard-deviation bands."""

from __future__ import annotations

import numpy as np
import pandas as pd

from volume.models import VWAPResult


def compute_vwap(
    df: pd.DataFrame,
    std_multiplier: float = 2.0,
) -> VWAPResult:
    """Compute cumulative VWAP and ±1/±2 std bands from the DataFrame start.

    Uses typical price = (H + L + C) / 3.  Bands are built from the
    volume-weighted standard deviation of typical price around VWAP.

    Returns:
        VWAPResult with current values and price position relative to bands.
    """
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"]

    cum_vol    = vol.cumsum()
    cum_tp_vol = (tp * vol).cumsum()
    vwap       = cum_tp_vol / cum_vol.replace(0, np.nan)

    # Volume-weighted variance: E[x²] - E[x]²
    cum_tp2_vol = (tp ** 2 * vol).cumsum()
    vw_variance = (cum_tp2_vol / cum_vol.replace(0, np.nan)) - vwap ** 2
    vw_std      = np.sqrt(vw_variance.clip(lower=0))

    upper_1 = vwap + 1.0 * vw_std
    lower_1 = vwap - 1.0 * vw_std
    upper_2 = vwap + std_multiplier * vw_std
    lower_2 = vwap - std_multiplier * vw_std

    cur_price = float(df["close"].iloc[-1])
    cur_vwap  = float(vwap.iloc[-1]) if not np.isnan(vwap.iloc[-1]) else cur_price
    cur_u1    = float(upper_1.iloc[-1]) if not np.isnan(upper_1.iloc[-1]) else cur_vwap
    cur_l1    = float(lower_1.iloc[-1]) if not np.isnan(lower_1.iloc[-1]) else cur_vwap
    cur_u2    = float(upper_2.iloc[-1]) if not np.isnan(upper_2.iloc[-1]) else cur_vwap
    cur_l2    = float(lower_2.iloc[-1]) if not np.isnan(lower_2.iloc[-1]) else cur_vwap

    if cur_price >= cur_u2:
        position = "ABOVE_BAND2"
    elif cur_price >= cur_u1:
        position = "ABOVE_BAND1"
    elif cur_price >= cur_vwap:
        position = "ABOVE_VWAP"
    elif cur_price >= cur_l1:
        position = "BELOW_VWAP"
    elif cur_price >= cur_l2:
        position = "BELOW_BAND1"
    else:
        position = "BELOW_BAND2"

    return VWAPResult(
        current_vwap=cur_vwap,
        current_upper_1=cur_u1,
        current_lower_1=cur_l1,
        current_upper_2=cur_u2,
        current_lower_2=cur_l2,
        current_price=cur_price,
        position=position,
        std_multiplier=std_multiplier,
    )
