"""Shared trade utilities — single source of truth for backtester and feature_importance.

Problems fixed:
  - get_viable_clusters: same filter in both files (no regime adj in initial filter)
  - entry_tolerance: width-based zone tolerance (price must re-enter the zone)
  - resolve_trade: unified exit logic, correct handling of end-of-data edge case
"""
from __future__ import annotations
import numpy as np
from pivot.cluster import Cluster


def get_viable_clusters(
    clusters:    list[Cluster],
    min_prob:    float,
    min_touches: int = 2,
) -> list[Cluster]:
    """
    Shared viable cluster filter.

    Uses plain min_prob — no regime_prob_adj here.
    regime_prob_adj is applied per-entry inside the backtester loop only.
    Both backtester and feature_importance call this identically so their
    viable sets are identical when regime_prob_adj=0.
    """
    return [
        c for c in clusters
        if c.probability         >= min_prob
        and c.historical_touches >= min_touches
    ]


def entry_tolerance(cl: Cluster, atr: float) -> float:
    """
    Touch / entry tolerance based on the cluster's actual price width.

    Price must RE-ENTER the zone (not merely approach it).
    Avoids counting touches that only grazed the outer edge of a wide cluster.

      half_width = cl.width × 0.5  (zero-width clusters get floor)
      floor  = 0.20 × ATR
      ceiling = 0.75 × ATR
    """
    half_width = cl.width * 0.5 if cl.width > atr * 0.05 else 0.0
    return min(atr * 0.75, max(atr * 0.20, half_width))


def resolve_trade(
    closes:          np.ndarray,
    highs:           np.ndarray,
    lows:            np.ndarray,
    entry_bar:       int,
    is_support:      bool,
    tp:              float,
    sl:              float,
    reaction_window: int,
) -> tuple[int | None, int]:
    """
    Simulate trade exit from bars AFTER entry_bar (no lookahead bias).

    Returns (outcome, hold_bars):
      outcome =  1   → TP hit (win)
      outcome = -1   → SL hit (loss)
      outcome = None → unresolved: end of data OR window expired without hit

    Edge case fixed vs old feature_importance.py:
      When `idx >= n` caused the for-loop to break, the `else: continue`
      clause did NOT run, so the unresolved trade was incorrectly recorded
      as a loss (outcome=0). Now returns None → caller skips it.
    """
    n     = len(closes)
    entry = closes[entry_bar]
    for k in range(1, reaction_window + 1):
        idx = entry_bar + k
        if idx >= n:
            return None, k          # end of data — unresolved
        if is_support:
            if highs[idx] - entry >= tp:  return  1, k
            if entry - lows[idx]  >= sl:  return -1, k
        else:
            if entry - lows[idx]  >= tp:  return  1, k
            if highs[idx] - entry >= sl:  return -1, k
    return None, reaction_window    # window expired — unresolved


def verify_consistency(bt_trades: int, fi_trades: int) -> str:
    """Return a ✅/❌ consistency verdict for printing."""
    if bt_trades == fi_trades:
        return f"✅ Consistent — both count {bt_trades} trades"
    diff = abs(bt_trades - fi_trades)
    return (
        f"❌ Inconsistent — BT={bt_trades}  FI={fi_trades}  diff={diff}\n"
        f"     Likely cause: regime_prob_adj active (by design) or different min_prob.\n"
        f"     Re-run with regime_prob_adj=0.0 to isolate."
    )
