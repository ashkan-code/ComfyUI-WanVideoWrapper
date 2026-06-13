"""Tests for DataCollector — uses AsyncMock clients, no real network calls."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from data_engine.collector import DataCollector
from data_engine.models import Candle
from xt_mcp.models.spot import SpotKlineBar, SpotKlineResponse
from xt_mcp.models.futures import FuturesKlineBar, FuturesKlineResponse


def _spot_bar(open_time: int) -> SpotKlineBar:
    return SpotKlineBar.model_validate(
        {"t": open_time, "o": "1", "h": "2", "l": "0.5", "c": "1.5", "v": "10", "a": "15", "T": open_time + 3_599_999},
    )


def _futures_bar(open_time: int) -> FuturesKlineBar:
    return FuturesKlineBar.model_validate(
        {"t": open_time, "o": "1", "h": "2", "l": "0.5", "c": "1.5", "v": "10", "a": "15"},
    )


def _spot_resp(bars: list[SpotKlineBar]) -> SpotKlineResponse:
    resp = MagicMock(spec=SpotKlineResponse)
    resp.result = bars
    return resp


def _futures_resp(bars: list[FuturesKlineBar]) -> FuturesKlineResponse:
    resp = MagicMock(spec=FuturesKlineResponse)
    resp.result = bars
    return resp


@pytest.fixture
def spot_client() -> AsyncMock:
    client = AsyncMock()
    return client


@pytest.fixture
def futures_client() -> AsyncMock:
    client = AsyncMock()
    return client


@pytest.fixture
def collector(spot_client: AsyncMock, futures_client: AsyncMock) -> DataCollector:
    return DataCollector(spot_client=spot_client, futures_client=futures_client)


class TestFetchSpot:
    @pytest.mark.asyncio
    async def test_single_batch_returns_candles(
        self, collector: DataCollector, spot_client: AsyncMock
    ) -> None:
        bars = [_spot_bar(i * 3_600_000) for i in range(3)]
        spot_client.get_kline.return_value = _spot_resp(bars)

        result = await collector.fetch_candles("btc_usdt", "1h", market="spot")

        assert len(result) == 3
        assert all(isinstance(c, Candle) for c in result)
        assert result[0].symbol == "btc_usdt"
        assert result[0].market == "spot"
        assert result[0].interval == "1h"
        spot_client.get_kline.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pagination_stops_when_partial_batch(
        self, collector: DataCollector, spot_client: AsyncMock, monkeypatch
    ) -> None:
        # batch_size = 3 for this test
        monkeypatch.setattr("data_engine.collector.settings.batch_size", 3)

        first_batch = [_spot_bar(i * 3_600_000) for i in range(3)]
        second_batch = [_spot_bar(10 * 3_600_000)]  # partial — signals end
        spot_client.get_kline.side_effect = [
            _spot_resp(first_batch),
            _spot_resp(second_batch),
        ]

        result = await collector.fetch_candles("btc_usdt", "1h", market="spot")

        assert len(result) == 4
        assert spot_client.get_kline.await_count == 2

    @pytest.mark.asyncio
    async def test_pagination_stops_when_empty(
        self, collector: DataCollector, spot_client: AsyncMock, monkeypatch
    ) -> None:
        monkeypatch.setattr("data_engine.collector.settings.batch_size", 3)

        first_batch = [_spot_bar(i * 3_600_000) for i in range(3)]
        spot_client.get_kline.side_effect = [
            _spot_resp(first_batch),
            _spot_resp([]),  # empty response stops loop
        ]

        result = await collector.fetch_candles("btc_usdt", "1h", market="spot")
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_passes_start_end_time(
        self, collector: DataCollector, spot_client: AsyncMock
    ) -> None:
        spot_client.get_kline.return_value = _spot_resp([_spot_bar(1_000_000)])

        await collector.fetch_candles(
            "btc_usdt", "1h", market="spot", start_ms=1_000_000, end_ms=9_000_000
        )

        _, kwargs = spot_client.get_kline.call_args
        assert kwargs["start_time"] == 1_000_000
        assert kwargs["end_time"] == 9_000_000

    @pytest.mark.asyncio
    async def test_candle_fields_mapped_correctly(
        self, collector: DataCollector, spot_client: AsyncMock
    ) -> None:
        bar = _spot_bar(5_000_000)
        spot_client.get_kline.return_value = _spot_resp([bar])

        result = await collector.fetch_candles("btc_usdt", "1h", market="spot")
        c = result[0]

        assert c.open_time == 5_000_000
        assert c.open == pytest.approx(1.0)
        assert c.high == pytest.approx(2.0)
        assert c.low == pytest.approx(0.5)
        assert c.close == pytest.approx(1.5)
        assert c.volume == pytest.approx(10.0)
        assert c.quote_volume == pytest.approx(15.0)


class TestFetchFutures:
    @pytest.mark.asyncio
    async def test_single_batch_futures(
        self, collector: DataCollector, futures_client: AsyncMock
    ) -> None:
        bars = [_futures_bar(i * 3_600_000) for i in range(2)]
        futures_client.get_kline.return_value = _futures_resp(bars)

        result = await collector.fetch_candles("btc_usdt", "1h", market="futures")

        assert len(result) == 2
        assert result[0].market == "futures"
        assert result[0].close_time == 0   # futures API does not provide close_time

    @pytest.mark.asyncio
    async def test_futures_pagination(
        self, collector: DataCollector, futures_client: AsyncMock, monkeypatch
    ) -> None:
        monkeypatch.setattr("data_engine.collector.settings.batch_size", 2)

        batch1 = [_futures_bar(i * 3_600_000) for i in range(2)]
        batch2 = [_futures_bar(5 * 3_600_000)]
        futures_client.get_kline.side_effect = [
            _futures_resp(batch1),
            _futures_resp(batch2),
        ]

        result = await collector.fetch_candles("btc_usdt", "1h", market="futures")
        assert len(result) == 3
        assert futures_client.get_kline.await_count == 2


class TestInvalidMarket:
    @pytest.mark.asyncio
    async def test_raises_value_error(self, collector: DataCollector) -> None:
        with pytest.raises(ValueError, match="Unknown market"):
            await collector.fetch_candles("btc_usdt", "1h", market="invalid")
