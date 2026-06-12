"""
ARIA — Orchestrator
Coordinates all agents, manages information flow, and drives the
SCANNING → SETUP_FOUND → WAITING_TRIGGER → ACTIVE_TRADE → CLOSING pipeline.
"""

import asyncio
import logging

from config import CONFIG
from database import init_db
from agents import (
    MarketAnalystAgent,
    WhaleTrackerAgent,
    GemHunterAgent,
    SetupGeneratorAgent,
    RiskManagerAgent,
    ExitManagerAgent,
    JournalAgent,
)
import telegram_notifier as tg

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    Central coordinator for the ARIA trading system.
    Owns all agent instances and the inter-agent message bus.
    """

    def __init__(self, account_balance: float = 1000.0):
        self.account_balance = account_balance

        # Shared async queue — all agents emit events here
        self.event_bus: asyncio.Queue = asyncio.Queue()
        self.exit_queue: asyncio.Queue = asyncio.Queue()
        self.gem_queue: asyncio.Queue = asyncio.Queue()

        # Instantiate agents
        self.market_analyst = MarketAnalystAgent(self.event_bus)
        self.whale_tracker = WhaleTrackerAgent(self.event_bus)
        self.gem_hunter = GemHunterAgent(
            self.gem_queue,
            market_analyst=self.market_analyst,
            whale_tracker=self.whale_tracker,
        )
        self.setup_generator = SetupGeneratorAgent(
            self.event_bus,
            market_analyst=self.market_analyst,
            whale_tracker=self.whale_tracker,
        )
        self.risk_manager = RiskManagerAgent(account_balance)
        self.exit_manager = ExitManagerAgent(
            risk_manager=self.risk_manager,
            whale_tracker=self.whale_tracker,
        )
        self.journal = JournalAgent()

        self._stop = asyncio.Event()

    # ──────────────────────────────────────────────────────────
    # Startup
    # ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """
        Initialise database, send startup notification, and launch all agents.
        """
        await init_db()
        await tg.system_online()
        logger.info("ARIA Orchestrator starting all agents")

        tasks = [
            asyncio.create_task(self.market_analyst.run(), name="market_analyst"),
            asyncio.create_task(self.whale_tracker.run(), name="whale_tracker"),
            asyncio.create_task(self.gem_hunter.run(), name="gem_hunter"),
            asyncio.create_task(
                self.setup_generator.run(self.gem_queue), name="setup_generator"
            ),
            asyncio.create_task(
                self.exit_manager.run(self.exit_queue), name="exit_manager"
            ),
            asyncio.create_task(self._event_loop(), name="event_loop"),
            asyncio.create_task(self._exit_loop(), name="exit_loop"),
            asyncio.create_task(self.journal.run_weekly_loop(), name="journal"),
        ]

        try:
            await asyncio.gather(*tasks)
        except Exception as exc:
            logger.critical("Orchestrator fatal error: %s", exc)
            await tg.system_offline(str(exc))
        finally:
            self._stop.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    # ──────────────────────────────────────────────────────────
    # Event processing loop
    # ──────────────────────────────────────────────────────────

    async def _event_loop(self) -> None:
        """
        Central event bus — routes messages from all agents.
        """
        logger.info("Event loop started")
        while not self._stop.is_set():
            try:
                event = await asyncio.wait_for(self.event_bus.get(), timeout=1.0)
                event_type = event.get("type")
                data = event.get("data", {})

                if event_type == "trade_setup":
                    await tg.setup_qualified(data)
                    await self._handle_setup(data)

                elif event_type == "gem_candidate":
                    await tg.gem_found(data)

                elif event_type == "market_analysis":
                    logger.debug("Market update: %s %s",
                                 data.get("symbol"), data.get("market_state"))

                elif event_type == "whale_signal":
                    ws = data.get("whale_signal", "NEUTRAL")
                    if ws in ("BULLISH_STRONG", "BEARISH_STRONG"):
                        logger.info("Whale signal %s: %s", data.get("symbol"), ws)
                        await tg.whale_alert(data["symbol"], ws, data.get("summary", ""))

            except asyncio.TimeoutError:
                pass
            except Exception as exc:
                logger.error("Event loop error: %s", exc)

    async def _handle_setup(self, setup: dict) -> None:
        """
        Process a qualified setup through risk manager and, if approved, open trade.
        """
        approved = self.risk_manager.approve(setup)

        if not approved.approved:
            reason = approved.rejection_reason
            logger.info("Trade rejected by risk manager: %s — %s", setup["symbol"], reason)
            await self.journal.log_skip(
                setup["symbol"], setup["direction"], reason, setup["confluence_score"]
            )
            return

        # Persist trade
        trade_dict = {
            **setup,
            "entry_price": approved.entry_price,
            "take_profit_1": approved.take_profit_levels[0] if approved.take_profit_levels else 0,
            "take_profit_2": approved.take_profit_levels[1] if len(approved.take_profit_levels) > 1 else 0,
            "take_profit_3": approved.take_profit_levels[2] if len(approved.take_profit_levels) > 2 else 0,
            "risk_amount_usdt": approved.risk_amount_usdt,
            "position_size_usdt": approved.position_size_usdt,
            "leverage": approved.leverage,
            "status": "active",
        }

        await self.journal.log_entry(trade_dict)
        self.risk_manager.add_open_trade(trade_dict)
        self.exit_manager.add_trade(trade_dict)
        await tg.trade_opened(trade_dict)

        logger.info(
            "✅ TRADE ACTIVE: %s %s | entry=%.4f SL=%.4f TP1=%.4f | "
            "score=%d leverage=%dx size=$%.2f",
            setup["symbol"], setup["direction"],
            approved.entry_price, approved.stop_loss,
            approved.take_profit_levels[0] if approved.take_profit_levels else 0,
            setup["confluence_score"], approved.leverage, approved.position_size_usdt,
        )

    # ──────────────────────────────────────────────────────────
    # Exit processing loop
    # ──────────────────────────────────────────────────────────

    async def _exit_loop(self) -> None:
        """Process exit decisions from ExitManagerAgent."""
        logger.info("Exit loop started")
        while not self._stop.is_set():
            try:
                event = await asyncio.wait_for(self.exit_queue.get(), timeout=1.0)
                if event.get("type") == "exit_decision":
                    decision = event["data"]
                    await self._handle_exit(decision)
            except asyncio.TimeoutError:
                pass
            except Exception as exc:
                logger.error("Exit loop error: %s", exc)

    async def _handle_exit(self, decision) -> None:
        """Apply an exit decision to the corresponding trade."""
        trade_id = decision.trade_id
        symbol = decision.symbol
        current_price = self.exit_manager._prices.get(symbol, 0)

        open_trade = await self._get_open_trade(trade_id)
        entry_price = (open_trade or {}).get("entry_price", 0)
        direction = (open_trade or {}).get("direction", "long")

        if decision.action == "full_exit":
            pnl_pct = (
                (current_price - entry_price) / entry_price * 100
                if direction == "long" and entry_price
                else (entry_price - current_price) / entry_price * 100
                if entry_price else 0
            )
            if "SL" in decision.reason or "SL hit" in decision.reason:
                await tg.sl_hit(symbol, current_price, pnl_pct)
            elif "TP3" in decision.reason:
                await tg.tp3_hit(symbol, current_price, pnl_pct)

            if open_trade:
                await self.journal.log_exit(trade_id, current_price, decision.reason,
                                            entry_price, direction)
            self.exit_manager.remove_trade(trade_id)
            self.risk_manager.remove_open_trade(trade_id)

        elif decision.action == "partial_exit":
            if "TP1" in decision.reason:
                await tg.tp1_hit(symbol, current_price, decision.new_sl or entry_price)
            elif "TP2" in decision.reason:
                await tg.tp2_hit(symbol, current_price, decision.new_sl or entry_price)
            else:
                await tg.partial_exit(symbol, decision.exit_pct,
                                      decision.reason, decision.new_sl)

        elif decision.action == "trail_sl" and decision.new_sl:
            logger.info("SL trailed for %s → %.4f", symbol, decision.new_sl)

    async def _get_open_trade(self, trade_id: str) -> dict | None:
        trades = await __import__("database").get_open_trades()
        return next((t for t in trades if t.get("id") == trade_id), None)
