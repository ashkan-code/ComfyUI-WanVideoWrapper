"""WatchlistManager: add/remove symbols, log alerts, query recent activity."""

from __future__ import annotations

import pathlib
import sqlite3
import time

from watchlist.db import get_connection
from watchlist.models import AlertRecord, WatchlistEntry


class WatchlistManager:
    def __init__(self, db_path: str | pathlib.Path | None = None) -> None:
        self._db_path = db_path

    # ── connection helper ─────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        return get_connection(self._db_path)

    # ── watchlist CRUD ────────────────────────────────────────────────────────

    def add(
        self,
        symbol: str,
        strategy: str,
        interval: str = "1h",
        market: str = "spot",
    ) -> WatchlistEntry:
        now = int(time.time() * 1000)
        with self._conn() as conn:
            try:
                cur = conn.execute(
                    "INSERT INTO watchlist (symbol, strategy, interval, market, created_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (symbol, strategy, interval, market, now),
                )
                entry_id = cur.lastrowid
            except sqlite3.IntegrityError:
                raise ValueError(
                    f"{symbol}/{strategy}/{interval}/{market} already in watchlist"
                )
        return self._get_entry(entry_id)

    def remove(
        self,
        symbol: str,
        strategy: str,
        interval: str = "1h",
        market: str = "spot",
    ) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM watchlist WHERE symbol=? AND strategy=? AND interval=? AND market=?",
                (symbol, strategy, interval, market),
            )
            return cur.rowcount > 0

    def list_entries(self) -> list[WatchlistEntry]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM watchlist ORDER BY created_at"
            ).fetchall()
            return [WatchlistEntry(**dict(r)) for r in rows]

    def _get_entry(self, entry_id: int) -> WatchlistEntry:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM watchlist WHERE id=?", (entry_id,)
            ).fetchone()
            return WatchlistEntry(**dict(row))

    # ── alert log ─────────────────────────────────────────────────────────────

    def log_alert(
        self,
        symbol: str,
        strategy: str,
        interval: str,
        market: str,
        signal_type: str,
        price: float,
        signal_timestamp: int,
    ) -> AlertRecord:
        now = int(time.time() * 1000)
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO alert_log"
                " (symbol, strategy, interval, market, signal_type, price, signal_timestamp, notified_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (symbol, strategy, interval, market, signal_type, price, signal_timestamp, now),
            )
            row = conn.execute(
                "SELECT * FROM alert_log WHERE id=?", (cur.lastrowid,)
            ).fetchone()
            return AlertRecord(**dict(row))

    def recent_alerts(self, limit: int = 50) -> list[AlertRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM alert_log ORDER BY notified_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [AlertRecord(**dict(r)) for r in rows]

    def get_last_signal_timestamp(
        self, symbol: str, strategy: str, interval: str, market: str
    ) -> int | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT MAX(signal_timestamp) AS ts FROM alert_log"
                " WHERE symbol=? AND strategy=? AND interval=? AND market=?",
                (symbol, strategy, interval, market),
            ).fetchone()
            return row["ts"]
