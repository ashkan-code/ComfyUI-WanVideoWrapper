"""
ARIA — Journal & Analytics Agent
Records every trade and generates weekly performance insights.
"""

import asyncio
import logging
import time
import uuid

import aiosqlite

from config import CONFIG
import database as db

logger = logging.getLogger(__name__)


class JournalAgent:
    """
    Logs all trade activity to SQLite and generates performance analytics.
    """

    def __init__(self):
        self._db_path = CONFIG["db_path"]

    # ──────────────────────────────────────────────────────────
    # Trade logging
    # ──────────────────────────────────────────────────────────

    async def log_entry(self, trade: dict) -> None:
        """
        Log a new trade entry.

        Args:
            trade: ApprovedTrade or TradeSetup dict
        """
        record = {
            "id": trade.get("setup_id", str(uuid.uuid4())[:8]),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "symbol": trade.get("symbol"),
            "direction": trade.get("direction"),
            "confluence_score": trade.get("confluence_score", 0),
            "setup_type": trade.get("setup_type", ""),
            "entry_price": trade.get("entry_trigger_price", trade.get("entry_price", 0)),
            "stop_loss": trade.get("stop_loss", 0),
            "tp1": trade.get("take_profit_1", trade.get("take_profit_levels", [0])[0] if trade.get("take_profit_levels") else 0),
            "tp2": trade.get("take_profit_2", trade.get("take_profit_levels", [0, 0])[1] if len(trade.get("take_profit_levels", [])) > 1 else 0),
            "tp3": trade.get("take_profit_3", trade.get("take_profit_levels", [0, 0, 0])[2] if len(trade.get("take_profit_levels", [])) > 2 else 0),
            "whale_signal": trade.get("whale_signal", ""),
            "funding_rate": trade.get("funding_rate", 0),
            "market_state": trade.get("htf_bias", ""),
            "notes": trade.get("notes", ""),
            "status": "active",
        }
        await db.insert_trade(record)
        logger.info("JOURNAL: entry logged — %s %s @%s",
                    record["symbol"], record["direction"], record["entry_price"])

    async def log_exit(self, trade_id: str, exit_price: float, exit_reason: str,
                       entry_price: float, direction: str) -> None:
        """
        Update trade record with exit details and compute P&L.

        Args:
            trade_id: The setup_id
            exit_price: Exit execution price
            exit_reason: e.g. "SL hit", "TP1 reached"
            entry_price: Original entry price
            direction: "long" or "short"
        """
        if direction == "long":
            pnl_pct = (exit_price - entry_price) / entry_price * 100
        else:
            pnl_pct = (entry_price - exit_price) / entry_price * 100

        await db.update_trade(trade_id, {
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "pnl_pct": round(pnl_pct, 3),
            "status": "closed_win" if pnl_pct >= 0 else "closed_loss",
        })
        icon = "✅" if pnl_pct >= 0 else "❌"
        logger.info("JOURNAL: exit logged %s — %s %.2f%%", trade_id, icon, pnl_pct)

    async def log_skip(self, symbol: str, direction: str, reason: str, score: int) -> None:
        """Log a skipped setup for later analysis."""
        record = {
            "id": str(uuid.uuid4())[:8],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "symbol": symbol,
            "direction": direction,
            "skip_reason": reason,
            "confluence_score": score,
        }
        await db.insert_skipped(record)

    # ──────────────────────────────────────────────────────────
    # Analytics
    # ──────────────────────────────────────────────────────────

    async def weekly_report(self) -> str:
        """
        Generate a weekly performance report.

        Returns:
            Formatted string report
        """
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row

            # Closed trades
            async with conn.execute(
                "SELECT * FROM trades WHERE status IN ('closed_win','closed_loss')"
            ) as cur:
                trades = [dict(r) for r in await cur.fetchall()]

        if not trades:
            return "No closed trades to analyse yet."

        wins = [t for t in trades if t["status"] == "closed_win"]
        losses = [t for t in trades if t["status"] == "closed_loss"]

        win_rate = len(wins) / len(trades) * 100
        avg_win = sum(t["pnl_pct"] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0
        expectancy = (win_rate / 100 * avg_win) + ((1 - win_rate / 100) * avg_loss)

        # Best and worst setups
        by_type: dict[str, list] = {}
        for t in trades:
            by_type.setdefault(t.get("setup_type", "unknown"), []).append(t["pnl_pct"])
        type_stats = {k: sum(v) / len(v) for k, v in by_type.items()}
        best_type = max(type_stats, key=type_stats.get) if type_stats else "N/A"

        lines = [
            "═══ ARIA WEEKLY PERFORMANCE REPORT ═══",
            f"Total trades : {len(trades)}",
            f"Win rate     : {win_rate:.1f}%",
            f"Avg win      : +{avg_win:.2f}%",
            f"Avg loss     : {avg_loss:.2f}%",
            f"Expectancy   : {expectancy:.3f}% per trade",
            f"Best setup   : {best_type} ({type_stats.get(best_type, 0):.2f}% avg)",
            "═══════════════════════════════════════",
        ]
        return "\n".join(lines)

    async def run_weekly_loop(self) -> None:
        """Auto-generate weekly report every 7 days."""
        while True:
            await asyncio.sleep(7 * 24 * 3600)
            report = await self.weekly_report()
            logger.info("\n%s", report)
