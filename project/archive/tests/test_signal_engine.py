"""Tests for SignalEngine."""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock

import pytest

from signals.engine import SignalEngine
from signals.models import SignalType
from xt_mcp.models.spot import SpotKlineBar, SpotKlineResponse


def _spot_bar(open_time: int, close: float) -> SpotKlineBar:
    return SpotKlineBar.model_validate({
        "t": open_time, "o": str(close), "h": str(close + 1),
        "l": str(close - 1), "c": str(close), "v": "1000", "a": "50000", "T": open_time + 3_599_999,
    })


def _spot_resp(bars: list[SpotKlineBar]) -> MagicMock:
    resp = MagicMock(spec=SpotKlineResponse)
    resp.result = bars
    return resp


@pytest.fixture
def spot_client() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def engine(spot_client: AsyncMock) -> SignalEngine:
    return SignalEngine(spot_client=spot_client)


class TestSignalEngine:
    @pytest.mark.asyncio
    async def test_run_returns_signals(self, engine: SignalEngine, spot_client: AsyncMock) -> None:
        # Falling prices → RSI will generate BUY signals
        bars = [_spot_bar(i * 3_600_000, 100.0 - i * 1.5) for i in range(80)]
        spot_client.get_kline.return_value = _spot_resp(bars)

        signals = await engine.run("btc_usdt", "1h", "rsi_reversal", market="spot")
        assert isinstance(signals, list)

    @pytest.mark.asyncio
    async def test_signals_have_correct_metadata(self, engine: SignalEngine, spot_client: AsyncMock) -> None:
        # Prices fall slowly (stay positive) → RSI eventually oversold → BUY signals
        bars = [_spot_bar(i * 3_600_000, 100.0 - i * 0.5) for i in range(80)]
        spot_client.get_kline.return_value = _spot_resp(bars)

        signals = await engine.run("btc_usdt", "1h", "rsi_reversal", market="spot")
        for s in signals:
            assert s.symbol == "btc_usdt"
            assert s.market == "spot"
            assert s.interval == "1h"
            assert s.strategy == "rsi_reversal"
            assert s.signal_type in (SignalType.BUY, SignalType.SELL)
            assert s.price > 0

    @pytest.mark.asyncio
    async def test_unknown_strategy_raises(self, engine: SignalEngine, spot_client: AsyncMock) -> None:
        bars = [_spot_bar(i * 3_600_000, float(50 + i)) for i in range(30)]
        spot_client.get_kline.return_value = _spot_resp(bars)

        with pytest.raises(ValueError, match="Unknown strategy"):
            await engine.run("btc_usdt", "1h", "nonexistent_strategy")

    @pytest.mark.asyncio
    async def test_unknown_market_raises(self, engine: SignalEngine, spot_client: AsyncMock) -> None:
        with pytest.raises(ValueError, match="Unknown market"):
            await engine.run("btc_usdt", "1h", "rsi_reversal", market="invalid")

    @pytest.mark.asyncio
    async def test_empty_api_response_returns_no_signals(self, engine: SignalEngine, spot_client: AsyncMock) -> None:
        spot_client.get_kline.return_value = _spot_resp([])
        signals = await engine.run("btc_usdt", "1h", "rsi_reversal")
        assert signals == []

    @pytest.mark.asyncio
    async def test_lookback_capped_at_1000(self, engine: SignalEngine, spot_client: AsyncMock) -> None:
        bars = [_spot_bar(i * 3_600_000, 50.0) for i in range(100)]
        spot_client.get_kline.return_value = _spot_resp(bars)

        await engine.run("btc_usdt", "1h", "rsi_reversal", lookback=2000)
        # get_kline called with positional args: (symbol, interval, limit)
        args, _ = spot_client.get_kline.call_args
        limit_sent = args[2]
        assert limit_sent <= 1000

    @pytest.mark.asyncio
    async def test_combined_strategy_runs(self, engine: SignalEngine, spot_client: AsyncMock) -> None:
        bars = [_spot_bar(i * 3_600_000, 50 + 10 * math.sin(i / 5)) for i in range(100)]
        spot_client.get_kline.return_value = _spot_resp(bars)

        signals = await engine.run("btc_usdt", "1h", "combined_momentum")
        # Combined strategy with 3 rules: strength is fraction of agreeing rules
        for s in signals:
            assert s.strength <= 1.0
            assert s.strength > 0.0
