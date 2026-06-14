"""Cluster multi-timeframe pivots into price zones."""

from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from pivot.engine import Pivot


@dataclass
class Cluster:
    center:        float
    width:         float
    pivot_count:   int          # pivots from multi-TF that mapped here
    tf_count:      int
    timeframes:    set
    avg_timestamp: int
    pivots:        list = field(default_factory=list, repr=False)
    # filled by analyzer
    historical_touches: int   = 0
    reaction_rate:      float = 0.0   # raw
    probability:        float = 0.0   # Laplace smoothed + touch-decay weighted
    confidence:         float = 0.0
    score:              int   = 0
    # filled by scorer.compute_quality_score
    quality_score:      float = 0.0   # Prob × Conf × TrendScore × VolumeScore
    trend_score:        float = 0.5
    volume_score:       float = 0.5
    recency_weight:     float = 1.0   # exp(-λ × age_in_bars)
    # pivot sub-features (filled by pivot_features.compute_pivot_features)
    pf_strength:          float = 0.0
    pf_recency:           float = 0.0
    pf_reaction_quality:  float = 0.0
    pf_mtf_agreement:     float = 0.0
    pf_touch_reliability: float = 0.0
    pivot_score:          float = 0.0
    # raw sequences for importance analysis (filled by analyzer)
    reaction_magnitudes:  list  = field(default_factory=list, repr=False)
    touch_outcomes:       list  = field(default_factory=list, repr=False)


def atr14(df: pd.DataFrame) -> float:
    h  = df["high"];  l = df["low"];  cp = df["close"].shift(1)
    tr = (h - l).combine(((h - cp).abs()), max).combine(((l - cp).abs()), max)
    v  = float(tr.rolling(14).mean().iloc[-1])
    return v if not np.isnan(v) else float((h - l).mean())


def cluster_pivots(
    pivots: list[Pivot],
    atr: float,
    tol_pct: float = 0.5,
    tol_atr: float = 0.5,
) -> list[Cluster]:
    """
    Merge pivots within max(tol_pct%, tol_atr×ATR).
    Sorted by pivot_count descending.
    """
    if not pivots:
        return []

    sorted_p = sorted(pivots, key=lambda p: p.price)
    used     = [False] * len(sorted_p)
    clusters: list[Cluster] = []

    for i, p in enumerate(sorted_p):
        if used[i]:
            continue
        tol   = max(p.price * tol_pct / 100.0, atr * tol_atr)
        group = [p];  used[i] = True

        for j in range(i + 1, len(sorted_p)):
            if not used[j] and abs(sorted_p[j].price - p.price) <= tol:
                group.append(sorted_p[j]);  used[j] = True

        prices = [g.price for g in group]
        tfs    = {g.timeframe for g in group}
        clusters.append(Cluster(
            center        = float(np.mean(prices)),
            width         = float(max(prices) - min(prices)),
            pivot_count   = len(group),
            tf_count      = len(tfs),
            timeframes    = tfs,
            avg_timestamp = int(np.mean([g.timestamp for g in group])),
            pivots        = group,
        ))

    clusters.sort(key=lambda c: -c.pivot_count)
    return clusters
