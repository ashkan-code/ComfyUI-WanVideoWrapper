"""Volume-at-price profile: POC, Value Area High/Low."""

from __future__ import annotations

import numpy as np
import pandas as pd

from volume.models import VolumeBin, VolumeProfileResult

_VA_TARGET = 0.70   # 70 % of total volume defines the Value Area


def compute_volume_profile(
    df: pd.DataFrame,
    bins: int = 50,
) -> VolumeProfileResult:
    """Compute volume-at-price distribution.

    Args:
        df:   OHLCV DataFrame.
        bins: Number of price buckets (default 50).

    Returns:
        VolumeProfileResult with POC, VAH, VAL, and per-bin volumes.
    """
    high   = df["high"].values
    low    = df["low"].values
    close  = df["close"].values
    volume = df["volume"].values

    typical = (high + low + close) / 3.0
    price_min = float(low.min())
    price_max = float(high.max())
    price_range = price_max - price_min

    if price_range == 0 or bins < 1:
        poc = float(np.mean(typical))
        return VolumeProfileResult(
            poc_price=poc, vah=poc, val=poc,
            total_volume=float(volume.sum()),
            value_area_pct=1.0,
        )

    bin_size = price_range / bins
    vol_per_bin = np.zeros(bins)

    for i in range(len(typical)):
        idx = int((typical[i] - price_min) / bin_size)
        idx = min(max(idx, 0), bins - 1)
        vol_per_bin[idx] += volume[i]

    # Point of Control
    poc_bin = int(np.argmax(vol_per_bin))
    poc_price = price_min + (poc_bin + 0.5) * bin_size

    # Value Area: expand from POC until 70 % of volume is captured
    total_volume = vol_per_bin.sum()
    target = total_volume * _VA_TARGET
    accumulated = vol_per_bin[poc_bin]
    lo_idx = poc_bin
    hi_idx = poc_bin

    while accumulated < target:
        lo_vol = vol_per_bin[lo_idx - 1] if lo_idx > 0 else 0.0
        hi_vol = vol_per_bin[hi_idx + 1] if hi_idx < bins - 1 else 0.0
        if lo_vol == 0 and hi_vol == 0:
            break
        if lo_vol >= hi_vol and lo_idx > 0:
            lo_idx -= 1
            accumulated += vol_per_bin[lo_idx]
        elif hi_idx < bins - 1:
            hi_idx += 1
            accumulated += vol_per_bin[hi_idx]
        else:
            break

    vah = price_min + (hi_idx + 1) * bin_size
    val = price_min + lo_idx * bin_size

    # Build bin list
    bin_list: list[VolumeBin] = []
    for i in range(bins):
        bvol = float(vol_per_bin[i])
        if bvol == 0:
            continue
        b_low  = price_min + i * bin_size
        b_high = b_low + bin_size
        bin_list.append(VolumeBin(
            price_low=b_low,
            price_high=b_high,
            price_mid=(b_low + b_high) / 2.0,
            volume=bvol,
            pct=bvol / total_volume * 100 if total_volume > 0 else 0.0,
        ))

    return VolumeProfileResult(
        poc_price=poc_price,
        vah=vah,
        val=val,
        total_volume=float(total_volume),
        value_area_pct=accumulated / total_volume if total_volume > 0 else 0.0,
        bins=bin_list,
    )
