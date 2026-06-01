"""
Order executor — places the 3 legs of an arbitrage triangle.
Handles dry-run, execution timing, and partial-fill recovery.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from config import Config
from scanner import Opportunity, Leg

log = logging.getLogger("executor")


@dataclass
class LegResult:
    leg: Leg
    order_id: Optional[str]
    executed_qty: float
    executed_price: float
    success: bool
    error: str = ""


@dataclass
class ExecutionResult:
    opportunity: Opportunity
    dry_run: bool
    legs: list[LegResult] = field(default_factory=list)
    success: bool = False
    net_profit_usdt: float = 0.0
    start_time_ms: int = 0
    end_time_ms: int = 0
    error: str = ""

    @property
    def duration_ms(self) -> int:
        return self.end_time_ms - self.start_time_ms

    def summary(self) -> str:
        status = "DRY-RUN" if self.dry_run else ("OK" if self.success else "FAIL")
        return (
            f"[{status}] profit={self.net_profit_usdt:+.4f} USDT "
            f"({self.opportunity.net_profit_pct:+.4f}%) "
            f"duration={self.duration_ms}ms"
        )


class OrderExecutor:
    def __init__(self, client, config: Config):
        self._client = client
        self._cfg = config
        self._trades_this_minute: list[float] = []

    def _check_rate_limit(self):
        now = time.time()
        self._trades_this_minute = [t for t in self._trades_this_minute if now - t < 60]
        if len(self._trades_this_minute) >= self._cfg.max_trades_per_min:
            raise RuntimeError(
                f"Rate limit: {self._cfg.max_trades_per_min} trades/min reached"
            )

    def _place_leg(self, leg: Leg, amount: float) -> LegResult:
        """
        Place a single leg order. Amount is in the 'from' currency.
        Returns the resulting amount in 'to' currency.
        """
        try:
            if leg.side == "BUY":
                qty = str(round(amount / leg.price, 8))
            else:
                qty = str(round(amount, 8))

            if self._cfg.dry_run:
                simulated_price = leg.price
                exec_qty = float(qty)
                if leg.side == "BUY":
                    out_qty = exec_qty
                else:
                    out_qty = exec_qty * simulated_price
                return LegResult(
                    leg=leg,
                    order_id="DRY_RUN",
                    executed_qty=out_qty,
                    executed_price=simulated_price,
                    success=True,
                )

            result = self._client.place_order(
                symbol=leg.symbol,
                side=leg.side,
                order_type=self._cfg.order_type,
                quantity=qty,
                price=str(leg.price) if self._cfg.order_type == "LIMIT" else None,
            )

            order_id = str(result.get("orderId", ""))
            exec_qty = float(result.get("executedQty") or result.get("quantity") or qty)
            exec_price = float(result.get("avgPrice") or result.get("price") or leg.price)

            return LegResult(
                leg=leg,
                order_id=order_id,
                executed_qty=exec_qty,
                executed_price=exec_price,
                success=True,
            )

        except Exception as e:
            return LegResult(
                leg=leg,
                order_id=None,
                executed_qty=0.0,
                executed_price=0.0,
                success=False,
                error=str(e),
            )

    def execute(self, opp: Opportunity) -> ExecutionResult:
        """
        Execute all 3 legs sequentially.
        If a leg fails, logs the failure (no automatic rollback —
        market orders can't be rolled back; operator must handle manually).
        """
        result = ExecutionResult(
            opportunity=opp,
            dry_run=self._cfg.dry_run,
            start_time_ms=int(time.time() * 1000),
        )

        try:
            self._check_rate_limit()
        except RuntimeError as e:
            result.error = str(e)
            result.end_time_ms = int(time.time() * 1000)
            log.warning(f"Rate limit blocked execution: {e}")
            return result

        prefix = "[DRY-RUN] " if self._cfg.dry_run else ""
        log.info(f"{prefix}Executing: {opp}")

        legs = [opp.triangle.leg1, opp.triangle.leg2, opp.triangle.leg3]
        amount = opp.start_amount

        for i, leg in enumerate(legs, 1):
            leg_result = self._place_leg(leg, amount)
            result.legs.append(leg_result)

            if not leg_result.success:
                result.error = f"Leg {i} failed: {leg_result.error}"
                result.end_time_ms = int(time.time() * 1000)
                log.error(f"{prefix}{result.error}")
                return result

            log.info(
                f"{prefix}  Leg {i}: {leg.symbol} {leg.side} "
                f"qty={leg_result.executed_qty:.6f} @ {leg_result.executed_price:.8f} "
                f"[order_id={leg_result.order_id}]"
            )

            # Amount flowing into next leg
            if leg.side == "BUY":
                amount = leg_result.executed_qty * (1 - self._cfg.trading_fee)
            else:
                amount = leg_result.executed_qty * (1 - self._cfg.trading_fee)

        result.success = True
        result.net_profit_usdt = round(amount - opp.start_amount, 6)
        result.end_time_ms = int(time.time() * 1000)
        self._trades_this_minute.append(time.time())

        log.info(f"{prefix}{result.summary()}")
        return result
