"""Reaction analyzer: measure historical reactions at cluster zones.

Touch decay: repeated tests of a level weaken it.
Weight of touch #k = 1 / sqrt(k)  →  1st=1.00, 2nd=0.71, 3rd=0.58, 4th=0.50 ...
Probability is Laplace-smoothed over decay-weighted counts so a level that has
been probed many times without failing is penalized, not rewarded.
"""

from __future__ import annotations
import math
import pandas as pd
from pivot.cluster import Cluster, atr14


def analyze_reactions(
    df: pd.DataFrame,
    clusters: list[Cluster],
    reaction_atr_multiple: float = 1.0,
    reaction_window: int = 10,
    min_touches: int = 4,
) -> list[Cluster]:
    """
    For each cluster scan 1h df for historical price touches.

    Reaction = price moves >= reaction_atr_multiple × ATR within reaction_window bars.

    Probability = Laplace on decay-weighted counts: (hit_w + 1) / (total_w + 2)
    Confidence  = f(raw touch count, TF count); capped at 0.40 if < min_touches.
    """
    atr    = atr14(df)
    closes = df["close"].values
    highs  = df["high"].values
    lows   = df["low"].values
    n      = len(df)
    move   = reaction_atr_multiple * atr

    last_close = closes[-1]

    for cl in clusters:
        tol        = max(cl.center * 0.005, atr * 0.5)
        is_support = cl.center < last_close

        touch_results: list[bool] = []

        for i in range(n - reaction_window):
            if abs(closes[i] - cl.center) > tol:
                continue
            future_hi = float(highs[i + 1 : i + 1 + reaction_window].max())
            future_lo = float(lows[i + 1  : i + 1 + reaction_window].min())
            if is_support:
                touch_results.append(future_hi - closes[i] >= move)
            else:
                touch_results.append(closes[i] - future_lo >= move)

        raw_touches = len(touch_results)
        raw_hits    = sum(touch_results)

        # Touch decay: w_k = 1/sqrt(k) → older, over-tested levels get penalized
        total_w = 0.0
        hit_w   = 0.0
        for idx, is_hit in enumerate(touch_results):
            w        = 1.0 / math.sqrt(idx + 1)
            total_w += w
            if is_hit:
                hit_w += w

        cl.historical_touches = raw_touches
        cl.reaction_rate      = raw_hits / raw_touches if raw_touches > 0 else 0.0
        cl.probability        = (hit_w + 1.0) / (total_w + 2.0)

        # Confidence uses raw touch count (not weighted) — more data = more reliable
        sample_w      = min(1.0, raw_touches / max(min_touches, 1))
        tf_w          = min(1.0, cl.tf_count / 3.0)
        cl.confidence = round(sample_w * 0.6 + tf_w * 0.4, 3)
        if raw_touches < min_touches:
            cl.confidence = min(cl.confidence, 0.40)

    return clusters
