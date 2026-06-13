"""Confluence scorer: 0-100 based on probability, TFs, structure, proximity."""

from __future__ import annotations
from pivot.cluster import Cluster
from pivot.structure import MarketStructure


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
