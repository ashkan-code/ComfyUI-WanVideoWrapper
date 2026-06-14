"""Predictive power analysis for the 5 pivot sub-features."""
from __future__ import annotations
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from pivot.cluster import Cluster, atr14

FEATURE_NAMES = (
    "pf_strength",
    "pf_recency",
    "pf_reaction_quality",
    "pf_mtf_agreement",
    "pf_touch_reliability",
)


@dataclass
class FeatureImportanceResult:
    n_trades:           int
    n_winners:          int
    n_losers:           int
    winner_means:       dict[str, float]
    loser_means:        dict[str, float]
    lift_ratios:        dict[str, float]   # winner_mean / loser_mean
    correlations:       dict[str, float]   # point-biserial r ∈ [-1, 1]
    ranking:            list[str]          # sorted by |r| descending
    optimal_weights:    dict[str, float]   # normalised from max(0, r)
    top_winner_feature: str                # highest positive r
    top_loser_feature:  str                # most negative r


def analyze_feature_importance(
    clusters:        list[Cluster],
    df:              pd.DataFrame,
    tp_atr:          float = 1.5,
    sl_atr:          float = 1.0,
    reaction_window: int   = 10,
    min_prob:        float = 0.55,
    cooldown:        int   = 10,
    min_gap:         int   = 5,
    max_per_cluster: int   = 3,
) -> FeatureImportanceResult:
    """
    Replay a lightweight backtest, recording per-trade pivot feature values
    and outcomes.  Compute point-biserial correlation for each feature,
    rank by |r|, and derive optimal weights from positive correlations only.
    """
    atr    = atr14(df)
    closes = df["close"].values
    highs  = df["high"].values
    lows   = df["low"].values
    n      = len(df)
    tp     = tp_atr * atr
    sl     = sl_atr * atr

    viable = [c for c in clusters
              if c.probability >= min_prob and c.historical_touches >= 2
              and c.pivot_score > 0.0]
    if not viable:
        return _empty()

    tols = [max(cl.center * 0.005, atr * 0.5) for cl in viable]
    cl_last   = [-9999] * len(viable)
    cl_cnt    = [0]     * len(viable)
    last_bar  = -9999
    records: list[dict] = []

    for i in range(n - reaction_window):
        for ci, cl in enumerate(viable):
            if cl_cnt[ci]  >= max_per_cluster:    continue
            if (i - cl_last[ci]) < cooldown:      continue
            if (i - last_bar)    < min_gap:        continue
            if abs(closes[i] - cl.center) > tols[ci]: continue

            touch_num  = cl_cnt[ci] + 1

            entry      = closes[i]
            is_support = cl.center < closes[-1]
            outcome    = 0   # default: no trade resolved → skip below

            for k in range(1, reaction_window + 1):
                idx = i + k
                if idx >= n:
                    break
                if is_support:
                    if highs[idx] - entry >= tp:  outcome = 1; break
                    if entry - lows[idx]  >= sl:  outcome = 0; break
                else:
                    if entry - lows[idx]  >= tp:  outcome = 1; break
                    if highs[idx] - entry >= sl:  outcome = 0; break
            else:
                continue   # no TP or SL hit → skip

            # Both TP and SL might not trigger in the inner loop but we broke out properly
            # Verify we have a valid exit (outcome was set inside loop)
            cl_last[ci]  = i
            cl_cnt[ci]  += 1
            last_bar     = i

            records.append({
                "outcome":              outcome,
                "pf_strength":          cl.pf_strength,
                "pf_recency":           cl.pf_recency,
                "pf_reaction_quality":  cl.pf_reaction_quality,
                "pf_mtf_agreement":     cl.pf_mtf_agreement,
                "pf_touch_reliability": cl.pf_touch_reliability,
            })

    if len(records) < 5:
        return _empty()

    outcomes  = np.array([r["outcome"] for r in records], dtype=float)
    n_total   = len(outcomes)
    n_winners = int(outcomes.sum())
    n_losers  = n_total - n_winners

    winner_means: dict[str, float] = {}
    loser_means:  dict[str, float] = {}
    lift_ratios:  dict[str, float] = {}
    correlations: dict[str, float] = {}

    for feat in FEATURE_NAMES:
        vals     = np.array([r[feat] for r in records], dtype=float)
        w_vals   = vals[outcomes == 1]
        l_vals   = vals[outcomes == 0]
        w_mean   = float(w_vals.mean()) if len(w_vals) > 0 else 0.0
        l_mean   = float(l_vals.mean()) if len(l_vals) > 0 else 0.0
        std_all  = float(vals.std())

        winner_means[feat] = round(w_mean, 4)
        loser_means[feat]  = round(l_mean, 4)
        lift_ratios[feat]  = round(w_mean / l_mean, 3) if l_mean > 1e-9 else 0.0

        if std_all > 1e-9 and n_winners > 0 and n_losers > 0:
            r_pb = ((w_mean - l_mean) / std_all
                    * math.sqrt(n_winners * n_losers / n_total ** 2))
            correlations[feat] = round(r_pb, 4)
        else:
            correlations[feat] = 0.0

    ranking    = sorted(FEATURE_NAMES, key=lambda f: -abs(correlations[f]))
    pos_feats  = [f for f in ranking if correlations[f] > 0]
    neg_feats  = [f for f in ranking if correlations[f] < 0]
    raw_pos    = {f: max(0.0, correlations[f]) for f in FEATURE_NAMES}
    total_pos  = sum(raw_pos.values())
    if total_pos > 1e-9:
        opt_w = {f: round(raw_pos[f] / total_pos, 4) for f in FEATURE_NAMES}
    else:
        opt_w = {f: 0.2 for f in FEATURE_NAMES}

    return FeatureImportanceResult(
        n_trades           = n_total,
        n_winners          = n_winners,
        n_losers           = n_losers,
        winner_means       = winner_means,
        loser_means        = loser_means,
        lift_ratios        = lift_ratios,
        correlations       = correlations,
        ranking            = list(ranking),
        optimal_weights    = opt_w,
        top_winner_feature = pos_feats[0] if pos_feats else ranking[0],
        top_loser_feature  = neg_feats[0] if neg_feats else ranking[-1],
    )


def _empty() -> FeatureImportanceResult:
    emp  = {f: 0.0 for f in FEATURE_NAMES}
    eq_w = {f: 0.2 for f in FEATURE_NAMES}
    return FeatureImportanceResult(
        n_trades=0, n_winners=0, n_losers=0,
        winner_means=emp, loser_means=emp,
        lift_ratios=emp, correlations=emp,
        ranking=list(FEATURE_NAMES),
        optimal_weights=eq_w,
        top_winner_feature="pf_reaction_quality",
        top_loser_feature="pf_strength",
    )
