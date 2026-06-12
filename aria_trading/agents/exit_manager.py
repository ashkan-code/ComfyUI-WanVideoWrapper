"""
ARIA — Exit Manager Agent (Trade Guardian)
Monitors every open trade in real-time and decides when to
close, reduce, or hold each position with surgical precision.
"""

import asyncio
import logging
import time
from dataclasses import dataclass

import aiohttp

from config import CONFIG
import telegram_notifier as tg

logger = logging.getLogger(__name__)


@dataclass
class ExitDecision:
    trade_id: str
    symbol: str
    action: str        # "hold" | "partial_exit" | "full_exit" | "trail_sl" | "cancel"
    exit_pct: float    # 0–100
    new_sl: float | None
    reason: str
    urgency: str       # "immediate" | "next_candle" | "limit_order"
    timestamp: str


class ExitManagerAgent:
    """
    Monitors open trades every 30 seconds.
    Applies TP scaling, SL trailing, and emergency exits.
    """

    def __init__(self, risk_manager=None, whale_tracker=None):
        self.risk_manager = risk_manager
        self.whale_tracker = whale_tracker
        self._open_trades: list[dict] = []
        self._prices: dict[str, float] = {}
        self.interval = CONFIG["exit_check_interval"]
        self.rest_url = CONFIG["bitunix_rest_url"]

    def add_trade(self, trade: dict) -> None:
        self._open_trades.append(trade)

    def remove_trade(self, trade_id: str) -> None:
        self._open_trades = [t for t in self._open_trades if t.get("setup_id") != trade_id]

    def update_price(self, symbol: str, price: float) -> None:
        self._prices[symbol] = price

    # ──────────────────────────────────────────────────────────
    # Main loop
    # ──────────────────────────────────────────────────────────

    async def run(self, exit_queue: asyncio.Queue) -> None:
        """Monitor loop — checks all open trades every 30 seconds."""
        logger.info("ExitManagerAgent started")
        while True:
            await self._refresh_prices()
            for trade in list(self._open_trades):
                try:
                    decision = await self.evaluate(trade)
                    if decision.action != "hold":
                        await exit_queue.put({"type": "exit_decision", "data": decision})
                        logger.info("EXIT %s: %s (%.0f%%) — %s",
                                    trade["symbol"], decision.action, decision.exit_pct, decision.reason)
                except Exception as exc:
                    logger.error("ExitManager error on %s: %s", trade.get("symbol"), exc)
            await asyncio.sleep(self.interval)

    # ──────────────────────────────────────────────────────────
    # Decision logic
    # ──────────────────────────────────────────────────────────

    async def evaluate(self, trade: dict) -> ExitDecision:
        """
        Evaluate a single open trade and return an exit decision.

        Args:
            trade: Active trade dict including entry, SL, TP levels

        Returns:
            ExitDecision
        """
        symbol = trade["symbol"]
        direction = trade["direction"]
        entry = trade["entry_price"]
        sl = trade["stop_loss"]
        tp1 = trade["take_profit_1"]
        tp2 = trade["take_profit_2"]
        tp3 = trade["take_profit_3"]
        current = self._prices.get(symbol, entry)
        trade_id = trade["setup_id"]
        whale = self.whale_tracker.get_cached(symbol) if self.whale_tracker else {}
        funding = (whale or {}).get("funding_rate", {}).get("current", 0.0)

        def make(action, exit_pct, new_sl, reason, urgency="next_candle") -> ExitDecision:
            return ExitDecision(
                trade_id=trade_id, symbol=symbol, action=action,
                exit_pct=exit_pct, new_sl=new_sl, reason=reason,
                urgency=urgency,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            )

        # ── IMMEDIATE FULL EXIT ──────────────────────────────
        if direction == "long":
            if current <= sl:
                await tg.send(f"❌ SL hit — {symbol} LONG | Exit: {current:.4f}")
                return make("full_exit", 100, None, "SL hit", urgency="immediate")
            if funding > 0.002:
                return make("full_exit", 100, None, f"Funding extreme {funding:.4f}", urgency="immediate")

        if direction == "short":
            if current >= sl:
                await tg.send(f"❌ SL hit — {symbol} SHORT | Exit: {current:.4f}")
                return make("full_exit", 100, None, "SL hit", urgency="immediate")
            if funding < -0.001:
                return make("full_exit", 100, None, f"Funding extreme short {funding:.4f}", urgency="immediate")

        # ── TP CASCADE ───────────────────────────────────────
        tp1_hit = (direction == "long" and current >= tp1) or (direction == "short" and current <= tp1)
        tp2_hit = (direction == "long" and current >= tp2) or (direction == "short" and current <= tp2)
        tp3_hit = (direction == "long" and current >= tp3) or (direction == "short" and current <= tp3)

        if tp3_hit and trade.get("tp2_closed"):
            await tg.send(f"✅ TP3 hit — {symbol} {direction.upper()} | Full exit at {current:.4f}")
            return make("full_exit", 100, None, "TP3 reached", urgency="limit_order")

        if tp2_hit and trade.get("tp1_closed") and not trade.get("tp2_closed"):
            new_sl = self.risk_manager.sl_after_tp2(tp1) if self.risk_manager else tp1
            await tg.send(f"✅ TP2 hit — {symbol} | 30% closed. SL → {new_sl:.4f}")
            return make("partial_exit", 30, new_sl, "TP2 reached", urgency="limit_order")

        if tp1_hit and not trade.get("tp1_closed"):
            new_sl = self.risk_manager.sl_after_tp1(entry) if self.risk_manager else entry
            await tg.send(f"✅ TP1 hit — {symbol} | 50% closed. SL → breakeven {new_sl:.4f}")
            return make("partial_exit", 50, new_sl, "TP1 reached, SL to BE", urgency="limit_order")

        # ── PARTIAL EXIT WARNINGS ────────────────────────────
        if direction == "long" and funding > CONFIG["funding_rate_long_max"]:
            return make("partial_exit", 50, None, f"Funding rising: {funding:.4f}")

        if direction == "short" and funding < CONFIG["funding_rate_short_max"]:
            return make("partial_exit", 50, None, f"Funding flipping: {funding:.4f}")

        return make("hold", 0, None, "All conditions valid")

    # ──────────────────────────────────────────────────────────
    # Price refresh
    # ──────────────────────────────────────────────────────────

    async def _refresh_prices(self) -> None:
        """Fetch current prices for all open trade symbols."""
        symbols = list({t["symbol"] for t in self._open_trades})
        if not symbols:
            return
        url = f"{self.rest_url}/fapi/v1/ticker/price"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if isinstance(data, list):
                            for item in data:
                                if item.get("symbol") in symbols:
                                    self._prices[item["symbol"]] = float(item["price"])
                        elif isinstance(data, dict):
                            sym = data.get("symbol")
                            if sym:
                                self._prices[sym] = float(data.get("price", 0))
        except Exception as exc:
            logger.debug("Price refresh error: %s", exc)
