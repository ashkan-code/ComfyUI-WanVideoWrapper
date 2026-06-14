"""Tests for CandleStore (SQLite backend)."""

from __future__ import annotations

import pathlib
import tempfile

import pytest

from data_engine.models import Candle
from data_engine.storage import CandleStore


def _make_candle(open_time: int, symbol: str = "btc_usdt", close: float = 50000.0) -> Candle:
    return Candle(
        symbol=symbol,
        market="spot",
        interval="1h",
        open_time=open_time,
        open=49000.0,
        high=51000.0,
        low=48000.0,
        close=close,
        volume=100.0,
        quote_volume=5_000_000.0,
        close_time=open_time + 3_599_999,
    )


@pytest.fixture
def store(tmp_path: pathlib.Path) -> CandleStore:
    return CandleStore(tmp_path / "test.db")


class TestCandleStoreInit:
    def test_creates_file(self, tmp_path: pathlib.Path) -> None:
        db = tmp_path / "sub" / "candles.db"
        CandleStore(db)
        assert db.exists()

    def test_empty_count(self, store: CandleStore) -> None:
        assert store.count_candles("btc_usdt", "spot", "1h") == 0

    def test_empty_latest_timestamp(self, store: CandleStore) -> None:
        assert store.get_latest_timestamp("btc_usdt", "spot", "1h") is None


class TestUpsert:
    def test_upsert_returns_count(self, store: CandleStore) -> None:
        candles = [_make_candle(1_000_000 * i) for i in range(5)]
        assert store.upsert_candles(candles) == 5

    def test_upsert_empty_returns_zero(self, store: CandleStore) -> None:
        assert store.upsert_candles([]) == 0

    def test_count_after_upsert(self, store: CandleStore) -> None:
        candles = [_make_candle(1_000_000 * i) for i in range(3)]
        store.upsert_candles(candles)
        assert store.count_candles("btc_usdt", "spot", "1h") == 3

    def test_deduplication(self, store: CandleStore) -> None:
        c = _make_candle(1_000_000)
        store.upsert_candles([c])
        store.upsert_candles([c])  # second upsert is a no-op (same PK)
        assert store.count_candles("btc_usdt", "spot", "1h") == 1

    def test_replace_updates_close(self, store: CandleStore) -> None:
        store.upsert_candles([_make_candle(1_000_000, close=50_000.0)])
        store.upsert_candles([_make_candle(1_000_000, close=99_000.0)])
        rows = store.get_candles("btc_usdt", "spot", "1h")
        assert rows[0].close == pytest.approx(99_000.0)


class TestGetCandles:
    def test_returns_ordered(self, store: CandleStore) -> None:
        ts = [3_000_000, 1_000_000, 2_000_000]
        store.upsert_candles([_make_candle(t) for t in ts])
        rows = store.get_candles("btc_usdt", "spot", "1h")
        assert [r.open_time for r in rows] == [1_000_000, 2_000_000, 3_000_000]

    def test_start_filter(self, store: CandleStore) -> None:
        store.upsert_candles([_make_candle(t) for t in [1_000_000, 2_000_000, 3_000_000]])
        rows = store.get_candles("btc_usdt", "spot", "1h", start_ms=2_000_000)
        assert len(rows) == 2
        assert rows[0].open_time == 2_000_000

    def test_end_filter(self, store: CandleStore) -> None:
        store.upsert_candles([_make_candle(t) for t in [1_000_000, 2_000_000, 3_000_000]])
        rows = store.get_candles("btc_usdt", "spot", "1h", end_ms=2_000_000)
        assert len(rows) == 2
        assert rows[-1].open_time == 2_000_000

    def test_limit(self, store: CandleStore) -> None:
        store.upsert_candles([_make_candle(t) for t in [1_000_000, 2_000_000, 3_000_000]])
        rows = store.get_candles("btc_usdt", "spot", "1h", limit=1)
        assert len(rows) == 1

    def test_no_cross_market_contamination(self, store: CandleStore) -> None:
        spot_c = _make_candle(1_000_000)
        futures_c = Candle(
            symbol="btc_usdt", market="futures", interval="1h",
            open_time=1_000_000, open=1.0, high=2.0, low=0.5, close=1.5,
            volume=10.0,
        )
        store.upsert_candles([spot_c, futures_c])
        spot_rows = store.get_candles("btc_usdt", "spot", "1h")
        futures_rows = store.get_candles("btc_usdt", "futures", "1h")
        assert len(spot_rows) == 1
        assert len(futures_rows) == 1

    def test_no_cross_interval_contamination(self, store: CandleStore) -> None:
        c1h = _make_candle(1_000_000)
        c4h = Candle(
            symbol="btc_usdt", market="spot", interval="4h",
            open_time=1_000_000, open=1.0, high=2.0, low=0.5, close=1.5,
            volume=10.0,
        )
        store.upsert_candles([c1h, c4h])
        assert store.count_candles("btc_usdt", "spot", "1h") == 1
        assert store.count_candles("btc_usdt", "spot", "4h") == 1


class TestLatestTimestamp:
    def test_returns_max(self, store: CandleStore) -> None:
        store.upsert_candles([_make_candle(t) for t in [1_000_000, 3_000_000, 2_000_000]])
        assert store.get_latest_timestamp("btc_usdt", "spot", "1h") == 3_000_000

    def test_returns_none_when_empty(self, store: CandleStore) -> None:
        assert store.get_latest_timestamp("eth_usdt", "spot", "1h") is None
