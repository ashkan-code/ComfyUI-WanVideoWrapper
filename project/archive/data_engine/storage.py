"""SQLite-backed candle store.

One SQLite file per market (data/spot.db, data/futures.db).  Uses
thread-local connections so the store is safe to share across threads
(each thread gets its own sqlite3.Connection).
"""

from __future__ import annotations

import pathlib
import sqlite3
import threading

from data_engine.models import Candle

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS candles (
    symbol       TEXT    NOT NULL,
    market       TEXT    NOT NULL,
    interval     TEXT    NOT NULL,
    open_time    INTEGER NOT NULL,
    open         REAL    NOT NULL,
    high         REAL    NOT NULL,
    low          REAL    NOT NULL,
    close        REAL    NOT NULL,
    volume       REAL    NOT NULL,
    quote_volume REAL    NOT NULL DEFAULT 0,
    close_time   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, market, interval, open_time)
)
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_candles_lookup
ON candles (symbol, market, interval, open_time)
"""

_UPSERT = """
INSERT OR REPLACE INTO candles
    (symbol, market, interval, open_time, open, high, low, close,
     volume, quote_volume, close_time)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class CandleStore:
    """Thread-safe SQLite store for OHLCV candle data."""

    def __init__(self, db_path: str | pathlib.Path) -> None:
        self._path = pathlib.Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._local: threading.local = threading.local()
        self._init_db()

    # ── internal helpers ──────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            conn = sqlite3.connect(str(self._path))
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    def _init_db(self) -> None:
        conn = self._conn()
        conn.execute(_CREATE_TABLE)
        conn.execute(_CREATE_INDEX)
        conn.commit()

    # ── public API ────────────────────────────────────────────────────────────

    def upsert_candles(self, candles: list[Candle]) -> int:
        """Persist *candles*, replacing any duplicate (symbol, market, interval, open_time).

        Returns the number of rows processed.
        """
        if not candles:
            return 0
        rows = [
            (
                c.symbol, c.market, c.interval, c.open_time,
                c.open, c.high, c.low, c.close,
                c.volume, c.quote_volume, c.close_time,
            )
            for c in candles
        ]
        conn = self._conn()
        conn.executemany(_UPSERT, rows)
        conn.commit()
        return len(rows)

    def get_candles(
        self,
        symbol: str,
        market: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int | None = None,
    ) -> list[Candle]:
        """Return candles ordered by open_time ascending."""
        query = "SELECT * FROM candles WHERE symbol=? AND market=? AND interval=?"
        args: list = [symbol, market, interval]
        if start_ms is not None:
            query += " AND open_time >= ?"
            args.append(start_ms)
        if end_ms is not None:
            query += " AND open_time <= ?"
            args.append(end_ms)
        query += " ORDER BY open_time"
        if limit is not None:
            query += f" LIMIT {int(limit)}"

        rows = self._conn().execute(query, args).fetchall()
        return [
            Candle(
                symbol=r["symbol"],
                market=r["market"],
                interval=r["interval"],
                open_time=r["open_time"],
                open=r["open"],
                high=r["high"],
                low=r["low"],
                close=r["close"],
                volume=r["volume"],
                quote_volume=r["quote_volume"],
                close_time=r["close_time"],
            )
            for r in rows
        ]

    def get_latest_timestamp(self, symbol: str, market: str, interval: str) -> int | None:
        """Return the largest open_time stored, or None if no rows exist."""
        row = self._conn().execute(
            "SELECT MAX(open_time) FROM candles WHERE symbol=? AND market=? AND interval=?",
            (symbol, market, interval),
        ).fetchone()
        if row and row[0] is not None:
            return int(row[0])
        return None

    def count_candles(self, symbol: str, market: str, interval: str) -> int:
        """Return the number of candle rows for a (symbol, market, interval) key."""
        row = self._conn().execute(
            "SELECT COUNT(*) FROM candles WHERE symbol=? AND market=? AND interval=?",
            (symbol, market, interval),
        ).fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        if hasattr(self._local, "conn"):
            self._local.conn.close()
            del self._local.conn
