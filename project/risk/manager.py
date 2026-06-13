"""RiskManager: combines sizing functions into PositionSize / StopTarget / RiskReport."""

from __future__ import annotations

from risk.models import PositionSize, RiskReport, StopTarget
from risk.sizing import (
    atr_stop_price,
    atr_target_price,
    kelly_fraction,
    size_from_fixed_stop,
)


class RiskManager:
    """Produces position sizes and risk reports for a given trade setup.

    Decision flow:
        1. Determine stop/target from ATR or explicit percentages.
        2. Size the position so that hitting the stop = risk_pct of capital
           (fixed-fraction), or Kelly fraction derived from backtest stats.
    """

    def __init__(
        self,
        kelly_cap: float = 0.25,
        default_atr_multiplier: float = 2.0,
        default_reward_ratio: float = 2.0,
    ) -> None:
        self.kelly_cap = kelly_cap
        self.default_atr_multiplier = default_atr_multiplier
        self.default_reward_ratio = default_reward_ratio

    # ── sizing ────────────────────────────────────────────────────────────────

    def size_fixed(
        self,
        capital: float,
        risk_pct: float,
        entry_price: float,
        stop_price: float,
    ) -> PositionSize:
        qty = size_from_fixed_stop(capital, risk_pct, entry_price, stop_price)
        return PositionSize(
            method="fixed_fraction",
            capital=capital,
            risk_pct=risk_pct,
            risk_amount=capital * risk_pct,
            entry_price=entry_price,
            stop_price=stop_price,
            quantity=qty,
            position_value=qty * entry_price,
        )

    def size_kelly(
        self,
        capital: float,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        entry_price: float,
        stop_price: float,
    ) -> PositionSize:
        frac = kelly_fraction(win_rate, avg_win, avg_loss, cap=self.kelly_cap)
        qty = size_from_fixed_stop(capital, frac, entry_price, stop_price)
        return PositionSize(
            method="kelly",
            capital=capital,
            risk_pct=frac,
            risk_amount=capital * frac,
            entry_price=entry_price,
            stop_price=stop_price,
            quantity=qty,
            position_value=qty * entry_price,
        )

    # ── stops & targets ───────────────────────────────────────────────────────

    def stops_from_atr(
        self,
        entry_price: float,
        side: str,
        atr: float,
        atr_multiplier: float | None = None,
        reward_ratio: float | None = None,
    ) -> StopTarget:
        mul = atr_multiplier if atr_multiplier is not None else self.default_atr_multiplier
        rr  = reward_ratio  if reward_ratio  is not None else self.default_reward_ratio
        stop   = atr_stop_price(entry_price, side, atr, mul)
        target = atr_target_price(entry_price, side, atr, mul, rr)
        stop_dist   = abs(entry_price - stop)
        target_dist = abs(target - entry_price)
        return StopTarget(
            entry_price=entry_price,
            side=side,
            stop_price=stop,
            target_price=target,
            stop_distance=stop_dist,
            target_distance=target_dist,
            stop_pct=stop_dist / entry_price if entry_price > 0 else 0.0,
            target_pct=target_dist / entry_price if entry_price > 0 else 0.0,
            risk_reward_ratio=rr,
        )

    def stops_from_pct(
        self,
        entry_price: float,
        side: str,
        stop_pct: float,
        target_pct: float,
    ) -> StopTarget:
        if side == "long":
            stop   = entry_price * (1.0 - stop_pct)
            target = entry_price * (1.0 + target_pct)
        else:
            stop   = entry_price * (1.0 + stop_pct)
            target = entry_price * (1.0 - target_pct)
        stop_dist   = abs(entry_price - stop)
        target_dist = abs(target - entry_price)
        rr = target_dist / stop_dist if stop_dist > 0 else 0.0
        return StopTarget(
            entry_price=entry_price,
            side=side,
            stop_price=stop,
            target_price=target,
            stop_distance=stop_dist,
            target_distance=target_dist,
            stop_pct=stop_pct,
            target_pct=target_pct,
            risk_reward_ratio=rr,
        )

    # ── full report ───────────────────────────────────────────────────────────

    def full_report(
        self,
        symbol: str,
        interval: str,
        market: str,
        capital: float,
        risk_pct: float,
        entry_price: float,
        side: str,
        atr: float,
        method: str = "fixed",
        atr_multiplier: float | None = None,
        reward_ratio: float | None = None,
        win_rate: float | None = None,
        avg_win: float | None = None,
        avg_loss: float | None = None,
    ) -> RiskReport:
        mul = atr_multiplier if atr_multiplier is not None else self.default_atr_multiplier
        st  = self.stops_from_atr(entry_price, side, atr, mul, reward_ratio)

        if method == "kelly" and win_rate and avg_win and avg_loss:
            pos = self.size_kelly(capital, win_rate, avg_win, avg_loss, entry_price, st.stop_price)
        else:
            pos = self.size_fixed(capital, risk_pct, entry_price, st.stop_price)

        qty = pos.quantity
        return RiskReport(
            symbol=symbol,
            interval=interval,
            market=market,
            side=side,
            entry_price=entry_price,
            atr=atr,
            atr_multiplier=mul,
            position_size=pos,
            stop_target=st,
            max_loss=qty * st.stop_distance,
            max_gain=qty * st.target_distance,
        )
