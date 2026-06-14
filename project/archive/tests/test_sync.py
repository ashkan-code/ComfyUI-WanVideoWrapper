"""Tests for SyncManager."""

from __future__ import annotations

import pathlib
from unittest.mock import AsyncMock, patch

import pytest

from data_engine.collector import DataCollector
from data_engine.models import Candle
from data_engine.storage import CandleStore
from data_engine.sync import SyncManager


def _candle(open_time: int, symbol: str = "btc_usdt") -> Candle:
    return Candle(
        symbol=symbol, market="spot", interval="1h",
        open_time=open_time, open=1.0, high=2.0, low=0.5, close=1.5,
        volume=10.0,
    )


@pytest.fixture
def store(tmp_path: pathlib.Path) -> CandleStore:
    return CandleStore(tmp_path / "test.db")


@pytest.fixture
def mock_collector() -> AsyncMock:
    collector = AsyncMock(spec=DataCollector)
    collector.fetch_candles.return_value = []
    return collector


@pytest.fixture
def mgr(store: CandleStore, mock_collector: AsyncMock) -> SyncManager:
    return SyncManager(store=store, collector=mock_collector)


class TestSyncSymbol:
    @pytest.mark.asyncio
    async def test_full_sync_uses_max_history(
        self, mgr: SyncManager, mock_collector: AsyncMock
    ) -> None:
        mock_collector.fetch_candles.return_value = [_candle(1_000_000)]

        await mgr.sync_symbol("btc_usdt", "1h", market="spot", force_full=True)

        mock_collector.fetch_candles.assert_awaited_once()
        _, kwargs = mock_collector.fetch_candles.call_args
        # start_ms should be set (roughly now - max_history_days)
        assert kwargs["start_ms"] is not None
        assert kwargs["end_ms"] is not None
        assert kwargs["start_ms"] < kwargs["end_ms"]

    @pytest.mark.asyncio
    async def test_incremental_uses_latest_plus_interval(
        self, mgr: SyncManager, store: CandleStore, mock_collector: AsyncMock
    ) -> None:
        # Pre-populate a candle at t=3_600_000
        store.upsert_candles([_candle(3_600_000)])
        mock_collector.fetch_candles.return_value = [_candle(7_200_000)]

        await mgr.sync_symbol("btc_usdt", "1h", market="spot")

        _, kwargs = mock_collector.fetch_candles.call_args
        # start_ms = 3_600_000 + interval_ms(1h=3_600_000) = 7_200_000
        assert kwargs["start_ms"] == 7_200_000

    @pytest.mark.asyncio
    async def test_nothing_to_sync_returns_zero(
        self, mgr: SyncManager, mock_collector: AsyncMock
    ) -> None:
        # Patch time so start_ms >= end_ms is impossible in normal flow,
        # but force it by making latest very recent
        import time

        future_ts = int(time.time() * 1000) + 100_000
        mgr._store.upsert_candles([_candle(future_ts)])

        result = await mgr.sync_symbol("btc_usdt", "1h", market="spot")
        assert result == 0
        mock_collector.fetch_candles.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stores_fetched_candles(
        self, mgr: SyncManager, store: CandleStore, mock_collector: AsyncMock
    ) -> None:
        candles = [_candle(i * 3_600_000) for i in range(1, 4)]
        mock_collector.fetch_candles.return_value = candles

        count = await mgr.sync_symbol("btc_usdt", "1h", market="spot", force_full=True)

        assert count == 3
        assert store.count_candles("btc_usdt", "spot", "1h") == 3


class TestFullSync:
    @pytest.mark.asyncio
    async def test_full_sync_calls_all_combinations(
        self, mgr: SyncManager, mock_collector: AsyncMock, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            "data_engine.sync.settings.default_symbols", ["btc_usdt", "eth_usdt"]
        )
        monkeypatch.setattr(
            "data_engine.sync.settings.default_timeframes", ["1h", "4h"]
        )

        summary = await mgr.full_sync()

        # 2 symbols × 2 timeframes = 4 tasks
        assert mock_collector.fetch_candles.await_count == 4
        assert len(summary) == 4

    @pytest.mark.asyncio
    async def test_full_sync_explicit_symbols(
        self, mgr: SyncManager, mock_collector: AsyncMock
    ) -> None:
        summary = await mgr.full_sync(
            symbols=["btc_usdt"], timeframes=["1h"], market="spot"
        )
        assert "btc_usdt/1h" in summary

    @pytest.mark.asyncio
    async def test_failed_task_logged_not_raised(
        self, mgr: SyncManager, mock_collector: AsyncMock
    ) -> None:
        mock_collector.fetch_candles.side_effect = RuntimeError("network error")

        summary = await mgr.full_sync(
            symbols=["btc_usdt"], timeframes=["1h"], market="spot"
        )
        # Error is swallowed into the summary (missing key)
        assert "btc_usdt/1h" not in summary


class TestIncrementalSync:
    @pytest.mark.asyncio
    async def test_incremental_starts_from_latest(
        self, mgr: SyncManager, store: CandleStore, mock_collector: AsyncMock
    ) -> None:
        store.upsert_candles([_candle(10_000_000)])
        mock_collector.fetch_candles.return_value = [_candle(13_600_000)]

        await mgr.incremental_sync(symbols=["btc_usdt"], timeframes=["1h"])

        _, kwargs = mock_collector.fetch_candles.call_args
        assert kwargs["start_ms"] == 10_000_000 + 3_600_000

    @pytest.mark.asyncio
    async def test_incremental_summary_returned(
        self, mgr: SyncManager, mock_collector: AsyncMock
    ) -> None:
        mock_collector.fetch_candles.return_value = [_candle(1_000_000)]

        summary = await mgr.incremental_sync(
            symbols=["btc_usdt"], timeframes=["1h"], market="spot"
        )
        assert summary["btc_usdt/1h"] == 1
