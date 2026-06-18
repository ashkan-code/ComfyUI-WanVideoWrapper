"""
ARIA Trading System — SQLite database setup and helpers.
"""

import aiosqlite
import logging
from config import CONFIG

logger = logging.getLogger(__name__)
DB_PATH = CONFIG["db_path"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    timestamp DATETIME,
    symbol TEXT,
    direction TEXT,
    confluence_score INTEGER,
    setup_type TEXT,
    entry_price REAL,
    stop_loss REAL,
    tp1 REAL, tp2 REAL, tp3 REAL,
    exit_price REAL,
    exit_reason TEXT,
    pnl_usdt REAL,
    pnl_pct REAL,
    rr_planned REAL,
    rr_actual REAL,
    duration_minutes INTEGER,
    whale_signal TEXT,
    funding_rate REAL,
    market_state TEXT,
    notes TEXT,
    status TEXT DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS skipped_setups (
    id TEXT PRIMARY KEY,
    timestamp DATETIME,
    symbol TEXT,
    direction TEXT,
    skip_reason TEXT,
    confluence_score INTEGER,
    outcome TEXT DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS market_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME,
    symbol TEXT,
    market_state TEXT,
    overall_bias TEXT,
    confidence INTEGER,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS whale_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME,
    symbol TEXT,
    signal TEXT,
    funding_rate REAL,
    oi_change_pct REAL,
    exchange_netflow REAL,
    summary TEXT
);
"""


async def init_db() -> None:
    """Create all tables if they don't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()
    logger.info("Database initialised at %s", DB_PATH)


async def insert_trade(trade: dict) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO trades
               (id,timestamp,symbol,direction,confluence_score,setup_type,
                entry_price,stop_loss,tp1,tp2,tp3,whale_signal,funding_rate,
                market_state,notes,status)
               VALUES (:id,:timestamp,:symbol,:direction,:confluence_score,
                       :setup_type,:entry_price,:stop_loss,:tp1,:tp2,:tp3,
                       :whale_signal,:funding_rate,:market_state,:notes,:status)""",
            trade,
        )
        await db.commit()


async def update_trade(trade_id: str, updates: dict) -> None:
    cols = ", ".join(f"{k} = :{k}" for k in updates)
    updates["id"] = trade_id
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE trades SET {cols} WHERE id = :id", updates)
        await db.commit()


async def get_open_trades() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM trades WHERE status = 'active'"
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def insert_skipped(setup: dict) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO skipped_setups
               (id,timestamp,symbol,direction,skip_reason,confluence_score)
               VALUES (:id,:timestamp,:symbol,:direction,:skip_reason,:confluence_score)""",
            setup,
        )
        await db.commit()
