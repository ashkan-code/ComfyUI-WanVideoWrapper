"""Backtest Lite v5 — shared utils, per-touch stats, calibration report."""

from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from pivot.cluster     import Cluster, atr14
from pivot.trade_utils import get_viable_clusters, entry_tolerance, resolve_trade


@dataclass
class BacktestResult:
    total_trades:        int
    win_rate:            float
    profit_factor:       float
    expectancy:          float         # in ATR units
    max_drawdown:        float         # peak-to-trough in ATR units
    clusters_tested:     int
    trades_per_100:      float
    avg_holding_bars:    float
    max_consec_losses:   int
    overtrading_warning: bool
    loss_analysis:       dict = field(default_factory=dict)


def backtest_clusters(
    clusters: list[Cluster],
    df: pd.DataFrame,
    tp_atr:          float        = 1.5,
    sl_atr:          float        = 1.0,
    reaction_window: int          = 10,
    min_prob:        float        = 0.55,
    cooldown:        int          = 10,
    min_gap:         int          = 5,
    max_per_cluster: int          = 3,
    entry_dist_atr:  float | None = None,
    regime_prob_adj: float        = 0.0,
) -> BacktestResult:
    """
    Entry:  price touches cluster where probability >= effective_min_prob.
    Exit:   first of TP or SL within reaction_window bars (via resolve_trade).
    Rules:
      - cooldown:        same cluster cannot be re-entered for cooldown bars
      - min_gap:         no new trade within min_gap bars of any prior trade
      - max_per_cluster: cluster retired after this many trades
      - entry_dist_atr:  override auto entry tolerance (ATR units)
      - regime_prob_adj: applied at entry time only (not in initial viable filter)

    Viable filter uses plain min_prob (matches feature_importance).
    regime_prob_adj tightens the per-entry threshold in RANGING / HIGH_VOL regimes.
    """
    atr    = atr14(df)
    closes = df["close"].values
    highs  = df["high"].values
    lows   = df["low"].values
    n      = len(df)
    tp     = tp_atr * atr
    sl     = sl_atr * atr

    # Viable filter: same as feature_importance (no regime adj)
    viable = get_viable_clusters(clusters, min_prob)

    # Per-entry regime-adjusted threshold
    effective_min_prob = min(0.90, max(0.50, min_prob + regime_prob_adj))

    # Entry tolerances: width-based (same formula as feature_importance)
    if entry_dist_atr is not None:
        _tols = [atr * entry_dist_atr] * len(viable)
    else:
        _tols = [entry_tolerance(cl, atr) for cl in viable]

    has_vol = "volume" in df.columns
    if has_vol:
        vol_arr  = df["volume"].values
        vol_roll = df["volume"].rolling(20, min_periods=1).mean().values
    else:
        vol_arr = vol_roll = None

    cluster_last_trade: list[int] = [-9999] * len(viable)
    cluster_trade_cnt:  list[int] = [0]     * len(viable)

    equity: list[float]   = [0.0]
    holding_bars: list[int] = []
    last_trade_bar          = -9999
    wins = losses           = 0
    cur_streak = max_loss_streak = 0

    loss_clusters:  dict[str, int] = {}
    loss_by_touch:  dict[int, int] = {}
    win_by_touch:   dict[int, int] = {}
    loss_by_volume: dict[str, int] = {}

    for i in range(n - reaction_window):
        for ci, cl in enumerate(viable):
            if cluster_trade_cnt[ci] >= max_per_cluster:
                continue
            if (i - cluster_last_trade[ci]) < cooldown:
                continue
            if (i - last_trade_bar) < min_gap:
                continue
            if abs(closes[i] - cl.center) > _tols[ci]:
                continue
            # Per-entry regime check (does not affect viable set)
            if cl.probability < effective_min_prob:
                continue

            touch_key  = min(cluster_trade_cnt[ci] + 1, 4)  # 4 = "4+"
            is_support = cl.center < closes[-1]

            outcome, hold = resolve_trade(
                closes, highs, lows, i, is_support, tp, sl, reaction_window
            )
            if outcome is None:
                continue

            result = tp_atr if outcome == 1 else -sl_atr

            cluster_last_trade[ci]  = i
            cluster_trade_cnt[ci]  += 1
            last_trade_bar          = i
            holding_bars.append(hold)
            equity.append(equity[-1] + result)

            if outcome == 1:
                wins      += 1
                cur_streak = 0
                win_by_touch[touch_key] = win_by_touch.get(touch_key, 0) + 1
            else:
                losses    += 1
                cur_streak += 1
                max_loss_streak = max(max_loss_streak, cur_streak)
                loss_by_touch[touch_key]  = loss_by_touch.get(touch_key, 0) + 1
                tf_key = str(cl.timeframes)
                loss_clusters[tf_key] = loss_clusters.get(tf_key, 0) + 1
                if has_vol and vol_roll is not None and vol_roll[i] > 0:
                    vr = vol_arr[i] / vol_roll[i]
                    vs = "high" if vr > 1.5 else ("low" if vr < 0.70 else "normal")
                else:
                    vs = "normal"
                loss_by_volume[vs] = loss_by_volume.get(vs, 0) + 1

    total = wins + losses
    wr    = wins / total if total > 0 else 0.0
    pf    = (wins * tp_atr) / (losses * sl_atr) if losses > 0 else float("inf")
    exp   = wr * tp_atr - (1 - wr) * sl_atr

    eq   = np.array(equity)
    peak = np.maximum.accumulate(eq)
    mdd  = float((peak - eq).max()) if len(eq) > 1 else 0.0

    t_per_100 = round(total / n * 100, 1) if n > 0 else 0.0
    avg_hold  = round(float(np.mean(holding_bars)), 1) if holding_bars else 0.0
    overfit   = total > n * 0.5

    return BacktestResult(
        total_trades        = total,
        win_rate            = round(wr, 4),
        profit_factor       = round(pf, 3),
        expectancy          = round(exp, 4),
        max_drawdown        = round(mdd, 3),
        clusters_tested     = len(viable),
        trades_per_100      = t_per_100,
        avg_holding_bars    = avg_hold,
        max_consec_losses   = max_loss_streak,
        overtrading_warning = overfit,
        loss_analysis       = {
            "by_timeframe":  loss_clusters,
            "by_touch":      loss_by_touch,
            "wins_by_touch": win_by_touch,
            "by_volume":     loss_by_volume,
        },
    )


def calibration_report(
    clusters: list[Cluster],
    df: pd.DataFrame,
    **bt_kwargs,
) -> list[dict]:
    """
    Group clusters by probability bucket, run a mini-backtest per bucket,
    and compare the predicted win rate (bucket midpoint) to the actual WR.

    Shows whether the system is well-calibrated:
      well-calibrated  → actual WR tracks predicted WR closely
      overconfident    → actual WR < predicted WR
      underconfident   → actual WR > predicted WR

    Returns list of:
      {"bucket": "0.60-0.70", "predicted_wr": 0.65, "actual_wr": 0.61, "count": 8}
    """
    buckets = [(0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 1.01)]
    report: list[dict] = []
    for lo, hi in buckets:
        bucket_cls = [c for c in clusters if lo <= c.probability < hi]
        if not bucket_cls:
            continue
        try:
            bt = backtest_clusters(bucket_cls, df, **bt_kwargs)
        except Exception:
            continue
        if bt.total_trades == 0:
            continue
        report.append({
            "bucket":       f"{lo:.2f}-{hi:.2f}",
            "predicted_wr": round((lo + hi) / 2, 2),
            "actual_wr":    bt.win_rate,
            "count":        bt.total_trades,
        })
    return report
