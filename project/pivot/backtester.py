"""Backtest Lite v3 — regime-aware thresholds + false-signal analysis."""

from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from pivot.cluster import Cluster, atr14


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
    regime_prob_adj: float        = 0.0,   # from regime.regime_min_prob delta
) -> BacktestResult:
    """
    Entry:  price touches cluster where effective_prob >= min_prob + regime_prob_adj.
    Exit:   first of TP or SL within reaction_window bars.
    Rules:
      - cooldown:        same cluster cannot be re-entered for cooldown bars
      - min_gap:         no new trade within min_gap bars of any prior trade
      - max_per_cluster: cluster retired after this many trades (freshness)
      - entry_dist_atr:  max distance to cluster center (ATR units); None=auto
      - regime_prob_adj: dynamic threshold shift from regime detection
    No lookahead bias: exit uses only future bars.
    """
    atr    = atr14(df)
    closes = df["close"].values
    highs  = df["high"].values
    lows   = df["low"].values
    n      = len(df)
    tp     = tp_atr * atr
    sl     = sl_atr * atr

    effective_min_prob = min(0.90, max(0.50, min_prob + regime_prob_adj))
    viable = [c for c in clusters if c.probability >= effective_min_prob
              and c.historical_touches >= 2]

    # Precompute entry tolerances (fixed per cluster, not per bar)
    if entry_dist_atr is not None:
        _tols = [atr * entry_dist_atr] * len(viable)
    else:
        _tols = [max(cl.center * 0.005, atr * 0.5) for cl in viable]

    # Precompute rolling 20-bar volume average for false-signal analysis
    has_vol   = "volume" in df.columns
    if has_vol:
        vol_arr  = df["volume"].values
        vol_roll = df["volume"].rolling(20, min_periods=1).mean().values
    else:
        vol_arr = vol_roll = None

    # Per-cluster state
    cluster_last_trade: list[int]  = [-9999] * len(viable)
    cluster_trade_cnt:  list[int]  = [0]     * len(viable)

    equity: list[float]    = [0.0]
    holding_bars: list[int] = []
    last_trade_bar          = -9999
    wins = losses           = 0
    cur_streak = max_loss_streak = 0

    # False-signal analysis
    loss_clusters: dict[str, int] = {}
    loss_by_touch: dict[int, int] = {}
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

            # First-touch probability decay: 0.85 ^ (touch_number - 1)
            touch_num      = cluster_trade_cnt[ci] + 1
            effective_prob = cl.probability * (0.85 ** (touch_num - 1))
            if effective_prob < effective_min_prob:
                continue

            # Simulate trade
            entry      = closes[i]
            is_support = cl.center < closes[-1]
            result     = 0.0
            hold       = 0

            for k in range(1, reaction_window + 1):
                idx = i + k
                if idx >= n:
                    break
                hold = k
                if is_support:
                    if highs[idx] - entry >= tp:  result =  tp_atr; break
                    if entry - lows[idx]  >= sl:  result = -sl_atr; break
                else:
                    if entry - lows[idx]  >= tp:  result =  tp_atr; break
                    if highs[idx] - entry >= sl:  result = -sl_atr; break

            if result == 0.0:
                continue

            cluster_last_trade[ci]  = i
            cluster_trade_cnt[ci]  += 1
            last_trade_bar          = i
            holding_bars.append(hold)
            equity.append(equity[-1] + result)

            if result > 0:
                wins      += 1
                cur_streak = 0
            else:
                losses    += 1
                cur_streak += 1
                max_loss_streak = max(max_loss_streak, cur_streak)

                # False-signal analysis
                tf_key = str(cl.timeframes)
                loss_clusters[tf_key] = loss_clusters.get(tf_key, 0) + 1

                loss_by_touch[touch_num] = loss_by_touch.get(touch_num, 0) + 1

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
            "by_timeframe": loss_clusters,
            "by_touch":     loss_by_touch,
            "by_volume":    loss_by_volume,
        },
    )
