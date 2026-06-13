"""Reaction analyzer: measure historical reactions at cluster zones."""

from __future__ import annotations
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

    Reaction = price moves >= reaction_atr_multiple x ATR
               in any direction within reaction_window candles.

    Probability = Laplace smoothed: (hits + 1) / (touches + 2)
    Confidence  = f(touch count, TF count); capped at 0.40 if touches < min_touches.
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
        is_support = cl.center < last_close   # below price → expect UP reaction
        touches    = 0
        hits       = 0

        for i in range(n - reaction_window):
            if abs(closes[i] - cl.center) > tol:
                continue
            touches += 1
            future_hi = float(highs[i + 1 : i + 1 + reaction_window].max())
            future_lo = float(lows[i + 1  : i + 1 + reaction_window].min())
            # Directional: support → UP reaction, resistance → DOWN reaction
            if is_support:
                if future_hi - closes[i] >= move:
                    hits += 1
            else:
                if closes[i] - future_lo >= move:
                    hits += 1

        cl.historical_touches = touches
        cl.reaction_rate = hits / touches if touches > 0 else 0.0
        # Laplace smoothing — prevents 0/0 and 100% on tiny samples
        cl.probability   = (hits + 1) / (touches + 2)

        # Confidence = weighted sample richness + TF coverage
        sample_w    = min(1.0, touches / max(min_touches, 1))
        tf_w        = min(1.0, cl.tf_count / 3.0)
        cl.confidence = round(sample_w * 0.6 + tf_w * 0.4, 3)
        if touches < min_touches:
            cl.confidence = min(cl.confidence, 0.40)   # LOW CONFIDENCE

    return clusters
