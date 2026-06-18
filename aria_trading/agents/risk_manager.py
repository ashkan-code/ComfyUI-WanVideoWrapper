"""
ARIA — Risk Manager Agent
Calculates exact position sizes and enforces portfolio-level risk rules.
Last line of defense before any order reaches the exchange.
"""

import asyncio
import logging
from dataclasses import dataclass, field

from config import CONFIG

logger = logging.getLogger(__name__)


@dataclass
class ApprovedTrade:
    setup_id: str
    symbol: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit_levels: list
    position_size_usdt: float
    leverage: int
    risk_amount_usdt: float
    risk_pct: float
    effective_leverage: float
    approved: bool
    rejection_reason: str | None = None


class RiskManagerAgent:
    """
    Calculates position sizes using fixed fractional risk model.
    Enforces hard portfolio rules: max trades, drawdown limits, correlation.
    """

    def __init__(self, account_balance: float):
        self.balance = account_balance
        self._open_trades: list[dict] = []
        self._daily_pnl: float = 0.0
        self._weekly_pnl: float = 0.0

    def update_balance(self, new_balance: float) -> None:
        self.balance = new_balance

    def record_pnl(self, pnl_usdt: float) -> None:
        self._daily_pnl += pnl_usdt
        self._weekly_pnl += pnl_usdt

    def add_open_trade(self, trade: dict) -> None:
        self._open_trades.append(trade)

    def remove_open_trade(self, trade_id: str) -> None:
        self._open_trades = [t for t in self._open_trades if t.get("id") != trade_id]

    # ──────────────────────────────────────────────────────────
    # Main approval flow
    # ──────────────────────────────────────────────────────────

    def approve(self, setup: dict) -> ApprovedTrade:
        """
        Validate and size a trade setup.

        Args:
            setup: TradeSetup dict from SetupGeneratorAgent

        Returns:
            ApprovedTrade (check .approved before using)
        """
        rejection = self._portfolio_check(setup)
        if rejection:
            return ApprovedTrade(
                setup_id=setup["setup_id"], symbol=setup["symbol"],
                direction=setup["direction"], entry_price=setup["entry_trigger_price"],
                stop_loss=setup["stop_loss"], take_profit_levels=[],
                position_size_usdt=0, leverage=1, risk_amount_usdt=0,
                risk_pct=0, effective_leverage=0, approved=False,
                rejection_reason=rejection,
            )

        entry = setup["entry_trigger_price"]
        sl = setup["stop_loss"]
        risk_usdt = self.balance * CONFIG["risk_per_trade_pct"] / 100
        sl_distance = abs(entry - sl)

        if sl_distance == 0:
            return ApprovedTrade(
                setup_id=setup["setup_id"], symbol=setup["symbol"],
                direction=setup["direction"], entry_price=entry, stop_loss=sl,
                take_profit_levels=[], position_size_usdt=0, leverage=1,
                risk_amount_usdt=0, risk_pct=0, effective_leverage=0,
                approved=False, rejection_reason="SL equals entry price",
            )

        # position size in base units
        position_size_usdt = risk_usdt / (sl_distance / entry)
        max_position = self.balance * CONFIG["max_position_pct"] / 100
        position_size_usdt = min(position_size_usdt, max_position)

        # apply correlation discount
        discount = self._correlation_discount(setup["symbol"])
        position_size_usdt *= discount

        effective_lev = position_size_usdt / self.balance
        leverage = min(
            int(effective_lev) + 1,
            CONFIG["max_leverage"],
        )

        tps = [setup["take_profit_1"], setup["take_profit_2"], setup["take_profit_3"]]

        logger.info(
            "RISK APPROVED %s | size=$%.2f | lev=%dx | risk=$%.2f (%.1f%%)",
            setup["symbol"], position_size_usdt, leverage,
            risk_usdt, CONFIG["risk_per_trade_pct"],
        )

        return ApprovedTrade(
            setup_id=setup["setup_id"],
            symbol=setup["symbol"],
            direction=setup["direction"],
            entry_price=entry,
            stop_loss=sl,
            take_profit_levels=tps,
            position_size_usdt=round(position_size_usdt, 2),
            leverage=leverage,
            risk_amount_usdt=round(risk_usdt, 2),
            risk_pct=CONFIG["risk_per_trade_pct"],
            effective_leverage=round(effective_lev, 2),
            approved=True,
        )

    # ──────────────────────────────────────────────────────────
    # Portfolio checks
    # ──────────────────────────────────────────────────────────

    def _portfolio_check(self, setup: dict) -> str | None:
        """
        Run all portfolio-level rule checks.

        Returns:
            Rejection reason string or None if all checks pass
        """
        if len(self._open_trades) >= CONFIG["max_concurrent_trades"]:
            return f"Max concurrent trades ({CONFIG['max_concurrent_trades']}) reached"

        daily_loss_pct = self._daily_pnl / self.balance * 100
        if daily_loss_pct <= -CONFIG["daily_loss_limit_pct"]:
            return f"Daily loss limit hit ({daily_loss_pct:.1f}%)"

        weekly_loss_pct = self._weekly_pnl / self.balance * 100
        if weekly_loss_pct <= -CONFIG["weekly_loss_limit_pct"]:
            return f"Weekly loss limit hit ({weekly_loss_pct:.1f}%)"

        return None

    def _correlation_discount(self, symbol: str) -> float:
        """
        Reduce position size if correlated trades are already open.

        Returns:
            Multiplier between 0.5 and 1.0
        """
        open_symbols = [t.get("symbol", "") for t in self._open_trades]

        # BTC ↔ ETH high correlation
        if symbol in ("ETHUSDT",) and "BTCUSDT" in open_symbols:
            return 0.5
        if symbol == "BTCUSDT" and "ETHUSDT" in open_symbols:
            return 0.5

        # Same L1/L2 ecosystem
        l2_group = {"ARBUSDT", "OPUSDT", "STXUSDT"}
        if symbol in l2_group and any(s in l2_group for s in open_symbols):
            return 0.75

        return 1.0

    # ──────────────────────────────────────────────────────────
    # Position management rules (called by ExitManagerAgent)
    # ──────────────────────────────────────────────────────────

    def sl_after_tp1(self, entry_price: float) -> float:
        """Move SL to breakeven after TP1 is hit."""
        return entry_price

    def sl_after_tp2(self, tp1: float) -> float:
        """Move SL to TP1 after TP2 is hit."""
        return tp1
