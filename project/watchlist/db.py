"""SQLite connection factory and schema initialisation."""

from __future__ import annotations

import pathlib
import sqlite3

_DEFAULT_DB = pathlib.Path(__file__).parent.parent / "data" / "watchlist.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT    NOT NULL,
    strategy    TEXT    NOT NULL,
    interval    TEXT    NOT NULL DEFAULT '1h',
    market      TEXT    NOT NULL DEFAULT 'spot',
    created_at  INTEGER NOT NULL,
    UNIQUE (symbol, strategy, interval, market)
);

CREATE TABLE IF NOT EXISTS alert_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol           TEXT    NOT NULL,
    strategy         TEXT    NOT NULL,
    interval         TEXT    NOT NULL,
    market           TEXT    NOT NULL,
    signal_type      TEXT    NOT NULL,
    price            REAL    NOT NULL,
    signal_timestamp INTEGER NOT NULL,
    notified_at      INTEGER NOT NULL
);
"""


def get_connection(db_path: str | pathlib.Path | None = None) -> sqlite3.Connection:
    path = pathlib.Path(db_path or _DEFAULT_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn
