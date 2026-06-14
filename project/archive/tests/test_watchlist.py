"""Tests for watchlist: DB schema, WatchlistManager, and MCP tools."""

from __future__ import annotations

import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from watchlist.db import get_connection
from watchlist.manager import WatchlistManager
from watchlist.models import AlertRecord, WatchlistEntry


# ─── helpers ────────────────────────────────────────────────────────────────


@pytest.fixture
def mgr(tmp_path: pathlib.Path) -> WatchlistManager:
    return WatchlistManager(db_path=tmp_path / "test.db")


def _make_signal(ts: int, price: float = 50_000.0, signal_type: str = "BUY"):
    sig = MagicMock()
    sig.timestamp = ts
    sig.price = price
    sig.signal_type.value = signal_type
    return sig


# ─── DB schema ───────────────────────────────────────────────────────────────


class TestWatchlistDB:
    def test_schema_creates_tables(self, tmp_path: pathlib.Path) -> None:
        conn = get_connection(tmp_path / "w.db")
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "watchlist" in tables
        assert "alert_log" in tables

    def test_schema_is_idempotent(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "w.db"
        get_connection(path)
        get_connection(path)   # second call must not raise

    def test_creates_parent_dir(self, tmp_path: pathlib.Path) -> None:
        nested = tmp_path / "a" / "b" / "w.db"
        get_connection(nested)
        assert nested.exists()


# ─── WatchlistManager ────────────────────────────────────────────────────────


class TestWatchlistManager:
    def test_add_returns_entry(self, mgr: WatchlistManager) -> None:
        entry = mgr.add("btc_usdt", "rsi_reversal")
        assert isinstance(entry, WatchlistEntry)
        assert entry.symbol == "btc_usdt"
        assert entry.strategy == "rsi_reversal"
        assert entry.interval == "1h"
        assert entry.market == "spot"
        assert entry.id is not None

    def test_add_custom_interval_market(self, mgr: WatchlistManager) -> None:
        entry = mgr.add("eth_usdt", "ema_cross", interval="4h", market="futures")
        assert entry.interval == "4h"
        assert entry.market == "futures"

    def test_add_duplicate_raises(self, mgr: WatchlistManager) -> None:
        mgr.add("btc_usdt", "rsi_reversal")
        with pytest.raises(ValueError, match="already in watchlist"):
            mgr.add("btc_usdt", "rsi_reversal")

    def test_add_same_symbol_different_strategy(self, mgr: WatchlistManager) -> None:
        mgr.add("btc_usdt", "rsi_reversal")
        entry = mgr.add("btc_usdt", "ema_cross")
        assert entry.strategy == "ema_cross"

    def test_remove_existing(self, mgr: WatchlistManager) -> None:
        mgr.add("btc_usdt", "rsi_reversal")
        assert mgr.remove("btc_usdt", "rsi_reversal") is True
        assert mgr.list_entries() == []

    def test_remove_nonexistent(self, mgr: WatchlistManager) -> None:
        assert mgr.remove("eth_usdt", "ema_cross") is False

    def test_list_entries_empty(self, mgr: WatchlistManager) -> None:
        assert mgr.list_entries() == []

    def test_list_entries_multiple(self, mgr: WatchlistManager) -> None:
        mgr.add("btc_usdt", "rsi_reversal")
        mgr.add("eth_usdt", "ema_cross", interval="4h")
        entries = mgr.list_entries()
        assert len(entries) == 2
        symbols = {e.symbol for e in entries}
        assert symbols == {"btc_usdt", "eth_usdt"}

    def test_log_alert(self, mgr: WatchlistManager) -> None:
        alert = mgr.log_alert(
            "btc_usdt", "rsi_reversal", "1h", "spot", "BUY", 50_000.0, 1_700_000_000_000
        )
        assert isinstance(alert, AlertRecord)
        assert alert.symbol == "btc_usdt"
        assert alert.signal_type == "BUY"
        assert alert.price == 50_000.0
        assert alert.signal_timestamp == 1_700_000_000_000

    def test_recent_alerts_order(self, mgr: WatchlistManager) -> None:
        mgr.log_alert("btc_usdt", "rsi_reversal", "1h", "spot", "BUY",  50_000.0, 1_700_000_000_000)
        mgr.log_alert("eth_usdt", "ema_cross",    "1h", "spot", "SELL",  3_000.0, 1_700_000_001_000)
        alerts = mgr.recent_alerts(limit=10)
        assert len(alerts) == 2
        # newest first
        assert alerts[0].symbol == "eth_usdt"

    def test_recent_alerts_limit(self, mgr: WatchlistManager) -> None:
        for i in range(5):
            mgr.log_alert("btc_usdt", "rsi_reversal", "1h", "spot", "BUY", 1.0, i)
        assert len(mgr.recent_alerts(limit=3)) == 3

    def test_get_last_ts_none_when_no_alerts(self, mgr: WatchlistManager) -> None:
        assert mgr.get_last_signal_timestamp("btc_usdt", "rsi_reversal", "1h", "spot") is None

    def test_get_last_ts_returns_max(self, mgr: WatchlistManager) -> None:
        mgr.log_alert("btc_usdt", "rsi_reversal", "1h", "spot", "BUY", 1.0, 1_000)
        mgr.log_alert("btc_usdt", "rsi_reversal", "1h", "spot", "BUY", 2.0, 3_000)
        mgr.log_alert("btc_usdt", "rsi_reversal", "1h", "spot", "BUY", 3.0, 2_000)
        assert mgr.get_last_signal_timestamp("btc_usdt", "rsi_reversal", "1h", "spot") == 3_000

    def test_get_last_ts_scoped_to_entry(self, mgr: WatchlistManager) -> None:
        mgr.log_alert("btc_usdt", "rsi_reversal", "1h", "spot", "BUY", 1.0, 9_000)
        # different strategy — should not bleed through
        assert mgr.get_last_signal_timestamp("btc_usdt", "ema_cross", "1h", "spot") is None

    def test_entry_to_dict(self, mgr: WatchlistManager) -> None:
        entry = mgr.add("btc_usdt", "rsi_reversal", interval="4h", market="futures")
        d = entry.to_dict()
        assert d["symbol"] == "btc_usdt"
        assert d["interval"] == "4h"
        assert d["market"] == "futures"
        assert "created_at" in d

    def test_alert_to_dict(self, mgr: WatchlistManager) -> None:
        alert = mgr.log_alert("btc_usdt", "rsi_reversal", "1h", "spot", "SELL", 48_000.0, 5_000)
        d = alert.to_dict()
        assert d["signal_type"] == "SELL"
        assert d["price"] == pytest.approx(48_000.0)
        assert "notified_at" in d


# ─── MCP tools ───────────────────────────────────────────────────────────────


class TestWatchlistTools:
    @pytest.mark.asyncio
    async def test_add_tool(self, tmp_path: pathlib.Path) -> None:
        from xt_mcp.tools.watchlist import add_to_watchlist
        mgr = WatchlistManager(db_path=tmp_path / "t.db")
        with patch("xt_mcp.tools.watchlist.WatchlistManager", return_value=mgr):
            result = await add_to_watchlist("btc_usdt", "rsi_reversal")
        assert result["error"] is False
        assert result["entry"]["symbol"] == "btc_usdt"

    @pytest.mark.asyncio
    async def test_add_tool_duplicate_returns_error(self, tmp_path: pathlib.Path) -> None:
        from xt_mcp.tools.watchlist import add_to_watchlist
        mgr = WatchlistManager(db_path=tmp_path / "t.db")
        mgr.add("btc_usdt", "rsi_reversal")
        with patch("xt_mcp.tools.watchlist.WatchlistManager", return_value=mgr):
            result = await add_to_watchlist("btc_usdt", "rsi_reversal")
        assert result["error"] is True

    @pytest.mark.asyncio
    async def test_remove_tool(self, tmp_path: pathlib.Path) -> None:
        from xt_mcp.tools.watchlist import remove_from_watchlist
        mgr = WatchlistManager(db_path=tmp_path / "t.db")
        mgr.add("btc_usdt", "rsi_reversal")
        with patch("xt_mcp.tools.watchlist.WatchlistManager", return_value=mgr):
            result = await remove_from_watchlist("btc_usdt", "rsi_reversal")
        assert result["error"] is False
        assert result["removed"] is True

    @pytest.mark.asyncio
    async def test_remove_tool_not_found(self, tmp_path: pathlib.Path) -> None:
        from xt_mcp.tools.watchlist import remove_from_watchlist
        mgr = WatchlistManager(db_path=tmp_path / "t.db")
        with patch("xt_mcp.tools.watchlist.WatchlistManager", return_value=mgr):
            result = await remove_from_watchlist("eth_usdt", "ema_cross")
        assert result["removed"] is False

    @pytest.mark.asyncio
    async def test_list_watchlist_tool(self, tmp_path: pathlib.Path) -> None:
        from xt_mcp.tools.watchlist import list_watchlist
        mgr = WatchlistManager(db_path=tmp_path / "t.db")
        mgr.add("btc_usdt", "rsi_reversal")
        mgr.add("eth_usdt", "ema_cross")
        with patch("xt_mcp.tools.watchlist.WatchlistManager", return_value=mgr):
            result = await list_watchlist()
        assert result["error"] is False
        assert result["count"] == 2

    @pytest.mark.asyncio
    async def test_list_watchlist_empty(self, tmp_path: pathlib.Path) -> None:
        from xt_mcp.tools.watchlist import list_watchlist
        mgr = WatchlistManager(db_path=tmp_path / "t.db")
        with patch("xt_mcp.tools.watchlist.WatchlistManager", return_value=mgr):
            result = await list_watchlist()
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_check_empty_watchlist(self, tmp_path: pathlib.Path) -> None:
        from xt_mcp.tools.watchlist import check_watchlist_signals
        mgr = WatchlistManager(db_path=tmp_path / "t.db")
        with patch("xt_mcp.tools.watchlist.WatchlistManager", return_value=mgr):
            result = await check_watchlist_signals()
        assert result["error"] is False
        assert result["total"] == 0
        assert "empty" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_check_finds_new_signals(self, tmp_path: pathlib.Path) -> None:
        from xt_mcp.tools.watchlist import check_watchlist_signals
        mgr = WatchlistManager(db_path=tmp_path / "t.db")
        mgr.add("btc_usdt", "rsi_reversal")

        import time
        future_ts = int(time.time() * 1000) + 3_600_000   # 1 hour in future

        mock_signal = _make_signal(future_ts)
        mock_engine = AsyncMock()
        mock_engine.run_with_df.return_value = ([mock_signal], MagicMock())

        with (
            patch("xt_mcp.tools.watchlist.WatchlistManager", return_value=mgr),
            patch("xt_mcp.tools.watchlist.SignalEngine", return_value=mock_engine),
        ):
            result = await check_watchlist_signals()

        assert result["error"] is False
        assert result["total"] == 1
        assert result["new_alerts"][0]["signal_type"] == "BUY"

    @pytest.mark.asyncio
    async def test_check_skips_old_signals(self, tmp_path: pathlib.Path) -> None:
        from xt_mcp.tools.watchlist import check_watchlist_signals
        mgr = WatchlistManager(db_path=tmp_path / "t.db")
        mgr.add("btc_usdt", "rsi_reversal")
        # log an alert with ts=5000 so cutoff becomes 5000
        mgr.log_alert("btc_usdt", "rsi_reversal", "1h", "spot", "BUY", 1.0, 5_000)

        old_signal = _make_signal(ts=4_000)  # older than cutoff
        mock_engine = AsyncMock()
        mock_engine.run_with_df.return_value = ([old_signal], MagicMock())

        with (
            patch("xt_mcp.tools.watchlist.WatchlistManager", return_value=mgr),
            patch("xt_mcp.tools.watchlist.SignalEngine", return_value=mock_engine),
        ):
            result = await check_watchlist_signals()

        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_get_recent_alerts_tool(self, tmp_path: pathlib.Path) -> None:
        from xt_mcp.tools.watchlist import get_recent_alerts
        mgr = WatchlistManager(db_path=tmp_path / "t.db")
        mgr.log_alert("btc_usdt", "rsi_reversal", "1h", "spot", "BUY", 50_000.0, 1_000)
        with patch("xt_mcp.tools.watchlist.WatchlistManager", return_value=mgr):
            result = await get_recent_alerts(limit=10)
        assert result["error"] is False
        assert result["count"] == 1
        assert result["alerts"][0]["signal_type"] == "BUY"
