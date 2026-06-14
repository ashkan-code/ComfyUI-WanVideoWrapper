"""Systematic parameter sweep optimizer for pivot confluence backtester.

Total grid: 7 prob × 4 conf × 5 touches × 4 widths × 3 trends × 4 cooldowns × 3 dists = 20,160
Precomputes pivots and reactions to avoid redundant work:
  - Pivot detection:    1×  (fixed across all params)
  - Reaction analysis:  4 widths × 5 touches = 20×
  - Backtests:          up to 20,160× (fast: ~300 bars × ~5 clusters each)
"""

from __future__ import annotations
from dataclasses import dataclass, replace
from itertools   import product

import numpy as np

from pivot.cluster   import Cluster, cluster_pivots, atr14
from pivot.engine    import Pivot, detect_pivots
from pivot.analyzer  import analyze_reactions
from pivot.scorer    import score_cluster
from pivot.structure import detect_structure
from pivot.backtester import backtest_clusters

# ── Parameter grids (all constants — never hardcode in call sites) ────────────
PROB_THRESHOLDS     = (0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90)
CONF_THRESHOLDS     = (0.60, 0.70, 0.80, 0.90)
MIN_TOUCHES_GRID    = (4, 6, 8, 10, 15)
CLUSTER_WIDTHS_ATR  = (0.25, 0.50, 0.75, 1.00)
TREND_FILTERS       = ("off", "uptrend", "both")
COOLDOWNS           = (0, 5, 10, 20)
DIST_TO_CLUSTER_ATR = (1.0, 2.0, 3.0)

TOTAL_COMBINATIONS  = (
    len(PROB_THRESHOLDS) * len(CONF_THRESHOLDS) * len(MIN_TOUCHES_GRID) *
    len(CLUSTER_WIDTHS_ATR) * len(TREND_FILTERS) * len(COOLDOWNS) *
    len(DIST_TO_CLUSTER_ATR)
)

# ── Robustness thresholds ─────────────────────────────────────────────────────
MIN_ROBUST_TRADES = 20
MIN_ROBUST_PF     = 1.20


# ── Data structures ───────────────────────────────────────────────────────────
@dataclass
class ParamSet:
    min_prob:          float
    min_conf:          float
    min_touches:       int
    cluster_width_atr: float
    trend_filter:      str    # "off" | "uptrend" | "both"
    cooldown:          int
    dist_atr:          float


@dataclass
class SweepResult:
    params:          ParamSet
    win_rate:        float
    profit_factor:   float
    expectancy:      float
    max_drawdown:    float
    trade_count:     int
    composite_score: float
    robust:          bool
    overfit_flag:    bool


# ── Scoring ───────────────────────────────────────────────────────────────────
def composite_score(pf: float, exp: float, wr: float, mdd: float) -> float:
    """
    40% Profit Factor + 25% Expectancy + 20% Win Rate + 15% Drawdown Reduction.
    All terms normalized to [0, 1] before weighting.
    """
    pf_n  = min(pf, 3.0) / 3.0                     # cap at 3×
    exp_n = max(0.0, min(exp + 2.0, 4.0)) / 4.0    # shift [-2,+2]→[0,4]→[0,1]
    mdd_n = 1.0 / (1.0 + mdd)                       # low MDD = high score
    return round(0.40 * pf_n + 0.25 * exp_n + 0.20 * wr + 0.15 * mdd_n, 4)


def opportunity_rank(cl: Cluster, trend: str, current_price: float) -> float:
    """
    Opportunity Rank = Probability × Confidence × Confluence × Trend Score.
    Range [0, 1].  Higher = better setup.
    """
    confluence = cl.score / 100.0
    is_support = cl.center < current_price
    if   trend == "UPTREND"   and is_support:      t = 1.0
    elif trend == "DOWNTREND" and not is_support:  t = 1.0
    elif trend == "RANGE":                          t = 0.5
    else:                                           t = 0.3   # counter-trend
    return round(cl.probability * cl.confidence * confluence * t, 4)


# ── Internal helpers ──────────────────────────────────────────────────────────
def _is_robust(total: int, pf: float, exp: float) -> bool:
    return total >= MIN_ROBUST_TRADES and pf >= MIN_ROBUST_PF and exp > 0.0


def _overfit_flag(wr: float, total: int) -> bool:
    """Flag suspiciously high WR on tiny trade count — likely overfitting."""
    return wr > 0.70 and total < 15


def _trend_passes(cl: Cluster, trend: str, price: float, trend_filter: str) -> bool:
    is_support = cl.center < price
    if trend_filter == "uptrend":
        return trend == "UPTREND" and is_support
    if trend_filter == "both":
        return (
            (trend == "UPTREND"   and is_support) or
            (trend == "DOWNTREND" and not is_support)
        )
    return True   # "off" — accept all


# ── Main sweep ────────────────────────────────────────────────────────────────
def run_sweep(
    dfs:                   dict,         # {"1h": df, "4h": df, "1d": df}
    tf_n:                  dict,         # {"1h": 3, "4h": 2, "1d": 2}
    reaction_atr_multiple: float = 1.5,
    reaction_window:       int   = 10,
    max_pivots:            int   = 100,
    tp_atr:                float = 1.5,
    sl_atr:                float = 1.0,
    top_n:                 int   = 10,
    robust_only:           bool  = True,
    verbose:               bool  = True,
) -> tuple[list[SweepResult], int]:
    """
    Run full parameter grid.  Returns (top_n results sorted by composite_score,
    total_robust_count).

    Architecture:
      outer  — cluster_width × min_touches (20 combos, need re-analysis each)
      inner  — prob × conf × trend × cooldown × dist (504 combos per outer)
    """
    df_1h  = dfs["1h"]
    atr    = atr14(df_1h)
    price  = float(df_1h["close"].iloc[-1])

    # Detect pivots once (fixed for all param sets)
    all_pivots: list[Pivot] = []
    for tf, df in dfs.items():
        if len(df) >= 10:
            all_pivots.extend(detect_pivots(df, tf, n=tf_n[tf], max_pivots=max_pivots))

    pivots_1d = detect_pivots(dfs["1d"], "1d", n=2, max_pivots=50)
    structure  = detect_structure(pivots_1d)
    trend      = structure.trend

    results:      list[SweepResult] = []
    total_robust: int               = 0

    for cw_idx, cw_atr in enumerate(CLUSTER_WIDTHS_ATR):
        if verbose:
            print(f"\r  [{cw_idx + 1}/{len(CLUSTER_WIDTHS_ATR)}] cluster_width={cw_atr:.2f}ATR ...",
                  end="", flush=True)

        raw_clusters = cluster_pivots(all_pivots, atr=atr, tol_atr=cw_atr)
        if not raw_clusters:
            continue

        for min_touches in MIN_TOUCHES_GRID:
            # Clone clusters so analyze_reactions doesn't mutate originals
            clusters_a = [replace(cl) for cl in raw_clusters]
            clusters_a = analyze_reactions(
                df_1h, clusters_a,
                reaction_atr_multiple=reaction_atr_multiple,
                reaction_window=reaction_window,
                min_touches=min_touches,
            )
            for cl in clusters_a:
                score_cluster(cl, structure, price)

            # Inner sweep — no re-analysis needed, only filter + backtest
            for min_prob, min_conf, trend_filter, cooldown, dist_atr in product(
                PROB_THRESHOLDS, CONF_THRESHOLDS,
                TREND_FILTERS, COOLDOWNS, DIST_TO_CLUSTER_ATR,
            ):
                viable = [
                    cl for cl in clusters_a
                    if cl.probability         >= min_prob
                    and cl.confidence         >= min_conf
                    and cl.historical_touches >= min_touches
                    and abs(cl.center - price) / price > 0.002
                    and _trend_passes(cl, trend, price, trend_filter)
                ]
                if not viable:
                    continue

                try:
                    bt = backtest_clusters(
                        viable, df_1h,
                        tp_atr=tp_atr, sl_atr=sl_atr,
                        reaction_window=reaction_window,
                        min_prob=min_prob,
                        cooldown=cooldown,
                        min_gap=max(1, cooldown // 2),
                        max_per_cluster=3,
                        entry_dist_atr=dist_atr,
                    )
                except Exception:
                    continue

                if bt.total_trades == 0:
                    continue

                pf_raw = bt.profit_factor
                pf     = min(pf_raw, 10.0) if pf_raw != float("inf") else 10.0
                cs     = composite_score(pf, bt.expectancy, bt.win_rate, bt.max_drawdown)
                robust = _is_robust(bt.total_trades, pf, bt.expectancy)
                ovf    = _overfit_flag(bt.win_rate, bt.total_trades)

                if robust_only and not robust:
                    continue

                total_robust += 1
                results.append(SweepResult(
                    params=ParamSet(
                        min_prob, min_conf, min_touches,
                        cw_atr, trend_filter, cooldown, dist_atr,
                    ),
                    win_rate        = bt.win_rate,
                    profit_factor   = pf_raw,
                    expectancy      = bt.expectancy,
                    max_drawdown    = bt.max_drawdown,
                    trade_count     = bt.total_trades,
                    composite_score = cs,
                    robust          = robust,
                    overfit_flag    = ovf,
                ))

    if verbose:
        print()   # newline after \r progress

    results.sort(key=lambda r: (-r.composite_score, -r.trade_count))
    return results[:top_n], total_robust
