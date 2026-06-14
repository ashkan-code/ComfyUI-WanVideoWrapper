"""Five pivot sub-features + weighted pivot_score."""
from __future__ import annotations
import math
from dataclasses import dataclass

import numpy as np

from pivot.cluster import Cluster

TF_WEIGHTS: dict[str, float] = {"1h": 0.20, "4h": 0.35, "1d": 0.45}

DEFAULT_PIVOT_WEIGHTS: dict[str, float] = {
    "pf_strength":          0.20,
    "pf_recency":           0.20,
    "pf_reaction_quality":  0.25,
    "pf_mtf_agreement":     0.20,
    "pf_touch_reliability": 0.15,
}

_LAMBDA_PIVOT = 0.003   # slower recency decay for individual pivot age


def compute_pivot_features(
    cl:       Cluster,
    last_ts:  int,
    bar_ms:   int  = 3_600_000,
    weights:  dict = DEFAULT_PIVOT_WEIGHTS,
) -> None:
    """Compute 5 pf_* sub-features and weighted pivot_score on cluster in-place."""

    # 1. Pivot Strength: ATR-normalised rejection at pivot formation
    if cl.pivots:
        rejs = [p.rejection for p in cl.pivots]
        cl.pf_strength = round(float(np.clip(np.mean(rejs), 0.0, 1.0)), 3)
    else:
        cl.pf_strength = 0.0

    # 2. Pivot Recency: exp decay from the MOST RECENT pivot (not avg)
    if cl.pivots:
        most_recent = max(p.timestamp for p in cl.pivots)
        age_bars    = max(0.0, (last_ts - most_recent) / bar_ms)
        cl.pf_recency = round(max(0.1, math.exp(-_LAMBDA_PIVOT * age_bars)), 3)
    else:
        cl.pf_recency = 0.0

    # 3. Reaction Quality: touch-decay-weighted avg bounce magnitude (3 ATR = full score)
    mags = cl.reaction_magnitudes
    if mags:
        w_total = w_sum = 0.0
        for k, m in enumerate(mags):
            w        = 1.0 / math.sqrt(k + 1)
            w_total += w
            w_sum   += w * m
        avg_mag = w_sum / w_total
        cl.pf_reaction_quality = round(min(1.0, avg_mag / 3.0), 3)
    else:
        cl.pf_reaction_quality = 0.0

    # 4. MTF Agreement: TF-weight-sum (1d=0.45, 4h=0.35, 1h=0.20; unknown TF = 0.10)
    cl.pf_mtf_agreement = round(
        min(1.0, sum(TF_WEIGHTS.get(tf, 0.10) for tf in cl.timeframes)),
        3,
    )

    # 5. Touch Reliability: probability × consistency ratio
    outcomes = cl.touch_outcomes
    if outcomes:
        transitions   = sum(1 for a, b in zip(outcomes, outcomes[1:]) if a != b)
        max_trans     = max(1, len(outcomes) - 1)
        consistency   = 1.0 - transitions / max_trans
        cl.pf_touch_reliability = round(cl.probability * consistency, 3)
    else:
        cl.pf_touch_reliability = round(cl.probability * 0.5, 3)

    # Weighted pivot_score ∈ [0, 1]
    w = weights
    cl.pivot_score = round(
        w.get("pf_strength",          0.20) * cl.pf_strength          +
        w.get("pf_recency",           0.20) * cl.pf_recency           +
        w.get("pf_reaction_quality",  0.25) * cl.pf_reaction_quality  +
        w.get("pf_mtf_agreement",     0.20) * cl.pf_mtf_agreement     +
        w.get("pf_touch_reliability", 0.15) * cl.pf_touch_reliability,
        4,
    )
