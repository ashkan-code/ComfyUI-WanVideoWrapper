"""Confluence scorer: score_cluster (0-100) + compute_quality_score."""

from __future__ import annotations
import math
from pivot.cluster import Cluster
from pivot.structure import MarketStructure

# Recency decay constant: exp(-LAMBDA × age_bars)
# At 200 bars old: exp(-0.005 × 200) ≈ 0.37
_RECENCY_LAMBDA = 0.005


def score_cluster(
    cluster: Cluster,
    structure: MarketStructure,
    current_price: float,
) -> int:
    s = 0.0

    # 1. Probability (30 pts)
    s += cluster.probability * 30

    # 2. Multi-TF confluence (25 pts)
    s += min(cluster.tf_count / 3.0, 1.0) * 25

    # 3. Historical touch richness (15 pts)
    s += min(cluster.historical_touches / 8.0, 1.0) * 15

    # 4. Market structure alignment (20 pts)
    is_support    = cluster.center < current_price
    is_resistance = cluster.center > current_price
    if   structure.trend == "UPTREND"   and is_support:    s += 20
    elif structure.trend == "DOWNTREND" and is_resistance: s += 20
    elif structure.trend == "RANGE":                        s += 10

    # 5. Proximity — closer = more actionable (10 pts)
    dist = abs(current_price - cluster.center) / current_price
    s += max(0.0, 1.0 - dist * 20) * 10

    cluster.score = min(100, int(round(s)))
    return cluster.score


def compute_quality_score(
    cl: Cluster,
    trend_score: float,
    volume_score: float,
    last_ts: int,
    bar_ms: int = 3_600_000,   # 1 hour in ms
) -> None:
    """
    Compute and store on cluster:

      recency_weight = exp(-LAMBDA × age_in_bars)   ∈ [0.1, 1.0]
      quality_score  = Prob × Conf × TrendScore × VolumeScore

    Ranking key = quality_score × recency_weight  (recency applied externally).
    """
    age_bars         = max(0.0, (last_ts - cl.avg_timestamp) / bar_ms)
    cl.recency_weight = round(max(0.1, math.exp(-_RECENCY_LAMBDA * age_bars)), 3)
    cl.trend_score    = round(float(trend_score),  3)
    cl.volume_score   = round(float(volume_score), 3)
    cl.quality_score  = round(
        cl.probability * cl.confidence * trend_score * volume_score,
        4,
    )
