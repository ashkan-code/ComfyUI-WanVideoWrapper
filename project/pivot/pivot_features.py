"""Five pivot sub-features + weighted pivot_score."""
from __future__ import annotations
import math

import numpy as np

from pivot.cluster import Cluster

TF_WEIGHTS: dict[str, float] = {"1h": 0.20, "4h": 0.35, "1d": 0.45}

# pf_recency zeroed: data shows negative correlation with wins.
# Reaction quality and touch reliability carry the most predictive power.
DEFAULT_PIVOT_WEIGHTS: dict[str, float] = {
    "pf_strength":          0.25,
    "pf_recency":           0.00,
    "pf_reaction_quality":  0.35,
    "pf_mtf_agreement":     0.25,
    "pf_touch_reliability": 0.15,
}

_LAMBDA_PIVOT = 0.003


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

    # 2. Pivot Recency: exp decay from most recent pivot (weight=0.0 by default)
    if cl.pivots:
        most_recent = max(p.timestamp for p in cl.pivots)
        age_bars    = max(0.0, (last_ts - most_recent) / bar_ms)
        cl.pf_recency = round(max(0.1, math.exp(-_LAMBDA_PIVOT * age_bars)), 3)
    else:
        cl.pf_recency = 0.0

    # 3. Reaction Quality: win-only touch-decay-weighted avg bounce (3 ATR = score 1.0)
    mags     = cl.reaction_magnitudes
    outcomes = cl.touch_outcomes
    if mags and outcomes:
        w_total = w_sum = 0.0
        for k, (m, hit) in enumerate(zip(mags, outcomes)):
            if hit:
                w        = 1.0 / math.sqrt(k + 1)
                w_total += w
                w_sum   += w * m
        avg_win_mag = w_sum / w_total if w_total > 0 else 0.0
        cl.pf_reaction_quality = round(min(1.0, avg_win_mag / 3.0), 3)
    elif mags:
        w_total = w_sum = 0.0
        for k, m in enumerate(mags):
            w        = 1.0 / math.sqrt(k + 1)
            w_total += w
            w_sum   += w * m
        cl.pf_reaction_quality = round(min(1.0, (w_sum / w_total) / 3.0), 3) if w_total > 0 else 0.0
    else:
        cl.pf_reaction_quality = 0.0

    # 4. MTF Agreement: TF-weight-sum (1d=0.45, 4h=0.35, 1h=0.20)
    cl.pf_mtf_agreement = round(
        min(1.0, sum(TF_WEIGHTS.get(tf, 0.10) for tf in cl.timeframes)),
        3,
    )

    # 5. Touch Reliability: 50% overall probability + 50% recent win rate (last 6 touches)
    if outcomes:
        n_recent  = min(6, len(outcomes))
        recent_wr = sum(outcomes[-n_recent:]) / n_recent
        cl.pf_touch_reliability = round(0.5 * cl.probability + 0.5 * recent_wr, 3)
    else:
        cl.pf_touch_reliability = round(cl.probability * 0.5, 3)

    # Weighted pivot_score ∈ [0, 1]
    w = weights
    cl.pivot_score = round(
        w.get("pf_strength",          0.25) * cl.pf_strength          +
        w.get("pf_recency",           0.00) * cl.pf_recency           +
        w.get("pf_reaction_quality",  0.35) * cl.pf_reaction_quality  +
        w.get("pf_mtf_agreement",     0.25) * cl.pf_mtf_agreement     +
        w.get("pf_touch_reliability", 0.15) * cl.pf_touch_reliability,
        4,
    )
