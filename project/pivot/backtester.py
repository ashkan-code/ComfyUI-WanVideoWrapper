"""Backtest Lite: fixed TP/SL simulation on cluster touches."""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
from pivot.cluster import Cluster, atr14


@dataclass
class BacktestResult:
    total_trades:    int
    win_rate:        float
    profit_factor:   float
    expectancy:      float   # in ATR units
    max_drawdown:    float   # peak-to-trough in ATR units
    clusters_tested: int


def backtest_clusters(
    clusters: list[Cluster],
    df: pd.DataFrame,
    tp_atr: float = 1.5,
    sl_atr: float = 1.0,
    reaction_window: int = 10,
    min_prob: float = 0.55,
) -> BacktestResult:
    """
    Entry:  price touches cluster where probability >= min_prob.
    Exit:   first of TP (tp_atr x ATR) or SL (sl_atr x ATR).
    Direction: UP if cluster is below price (support), DOWN if above.
    No lookahead: decisions made only with data available at bar i.
    """
    atr    = atr14(df)
    closes = df["close"].values
    highs  = df["high"].values
    lows   = df["low"].values
    n      = len(df)
    tp     = tp_atr * atr
    sl     = sl_atr * atr

    viable = [c for c in clusters if c.probability >= min_prob and c.historical_touches >= 2]
    equity: list[float] = [0.0]
    wins = losses = 0

    for cl in viable:
        tol        = max(cl.center * 0.005, atr * 0.5)
        is_support = cl.center < closes[-1]

        for i in range(n - reaction_window):
            if abs(closes[i] - cl.center) > tol:
                continue
            entry  = closes[i]
            result = 0.0
            for k in range(1, reaction_window + 1):
                idx = i + k
                if idx >= n:
                    break
                if is_support:
                    if highs[idx] - entry >= tp:  result =  tp_atr; break
                    if entry - lows[idx]  >= sl:  result = -sl_atr; break
                else:
                    if entry - lows[idx]  >= tp:  result =  tp_atr; break
                    if highs[idx] - entry >= sl:  result = -sl_atr; break

            if result > 0:   wins   += 1
            elif result < 0: losses += 1
            if result != 0:
                equity.append(equity[-1] + result)

    total = wins + losses
    wr    = wins / total if total > 0 else 0.0
    pf    = (wins * tp_atr) / (losses * sl_atr) if losses > 0 else float("inf")
    exp   = wr * tp_atr - (1 - wr) * sl_atr

    eq   = np.array(equity)
    peak = np.maximum.accumulate(eq)
    mdd  = float((peak - eq).max()) if len(eq) > 1 else 0.0

    return BacktestResult(
        total_trades    = total,
        win_rate        = round(wr, 4),
        profit_factor   = round(pf, 3),
        expectancy      = round(exp, 4),
        max_drawdown    = round(mdd, 3),
        clusters_tested = len(viable),
    )
