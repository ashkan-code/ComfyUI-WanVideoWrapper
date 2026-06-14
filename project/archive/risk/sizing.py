"""Core position-sizing and stop/target calculation functions."""

from __future__ import annotations


# ── Kelly criterion ───────────────────────────────────────────────────────────


def kelly_fraction(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    cap: float = 0.25,
) -> float:
    """Return half-Kelly fraction capped at *cap*.

    f* = (p*(b+1) - 1) / b,  b = avg_win / avg_loss
    Returns 0 if inputs are degenerate.
    """
    if win_rate <= 0 or win_rate >= 1 or avg_win <= 0 or avg_loss <= 0:
        return 0.0
    b = avg_win / avg_loss
    full_kelly = (win_rate * (b + 1) - 1) / b
    half_kelly = full_kelly / 2.0
    return max(0.0, min(half_kelly, cap))


# ── Fixed-fraction ────────────────────────────────────────────────────────────


def size_from_fixed_stop(
    capital: float,
    risk_pct: float,
    entry_price: float,
    stop_price: float,
) -> float:
    """Units to trade so that hitting stop_price risks exactly capital*risk_pct."""
    per_unit_risk = abs(entry_price - stop_price)
    if per_unit_risk == 0 or capital <= 0:
        return 0.0
    return (capital * risk_pct) / per_unit_risk


# ── ATR-based stop / target ───────────────────────────────────────────────────


def atr_stop_price(
    entry_price: float,
    side: str,
    atr: float,
    multiplier: float,
) -> float:
    """Stop price placed *multiplier* ATRs away from entry."""
    offset = atr * multiplier
    return entry_price - offset if side == "long" else entry_price + offset


def atr_target_price(
    entry_price: float,
    side: str,
    atr: float,
    multiplier: float,
    reward_ratio: float,
) -> float:
    """Target price placed *multiplier * reward_ratio* ATRs away from entry."""
    offset = atr * multiplier * reward_ratio
    return entry_price + offset if side == "long" else entry_price - offset
