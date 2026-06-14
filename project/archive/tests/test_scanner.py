"""Tests for MarketScanner."""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scanner.models import ScanResult, SymbolResult
from scanner.scanner import MarketScanner
from signals.models import Signal, SignalType
from xt_mcp.models.spot import SpotKlineBar, SpotKlineResponse


def _bar(open_time: int, close: float) -> SpotKlineBar:
    return SpotKlineBar.model_validate({
        "t": open_time, "o": str(close), "h": str(close + 1),
        "l": str(close - 1), "c": str(close), "v": "1000", "a": "50000",
        "T": open_time + 3_599_999,
    })


def _resp(bars: list[SpotKlineBar]) -> MagicMock:
    r = MagicMock(spec=SpotKlineResponse)
    r.result = bars
    return r


def _falling_bars(n: int = 80) -> list[SpotKlineBar]:
    return [_bar(i * 3_600_000, 100.0 - i * 1.0) for i in range(n)]


class TestMarketScannerValidation:
    def test_invalid_concurrency_raises(self) -> None:
        with pytest.raises(ValueError):
            MarketScanner(concurrency=0)

    def test_lookback_capped(self) -> None:
        s = MarketScanner(lookback=9999)
        assert s.lookback <= 1000


class TestMarketScannerScan:
    @pytest.mark.asyncio
    async def test_scan_returns_scan_result(self) -> None:
        spot_mock = AsyncMock()
        spot_mock.get_kline.return_value = _resp(_falling_bars())
        with patch("scanner.scanner.SignalEngine") as MockEngine:
            MockEngine.return_value._spot = spot_mock
            MockEngine.return_value._futures = AsyncMock()
            MockEngine.return_value.run = AsyncMock(return_value=[])
            scanner = MarketScanner(concurrency=2)
            result = await scanner.scan(["btc_usdt", "eth_usdt"], "rsi_reversal", "1h", "spot")
        assert isinstance(result, ScanResult)
        assert result.scanned == 2

    @pytest.mark.asyncio
    async def test_scan_all_succeed(self) -> None:
        with patch("scanner.scanner.SignalEngine") as MockEngine:
            MockEngine.return_value.run = AsyncMock(return_value=[])
            scanner = MarketScanner()
            result = await scanner.scan(["btc_usdt", "eth_usdt"], "rsi_reversal")
        assert result.succeeded == 2
        assert result.failed == 0

    @pytest.mark.asyncio
    async def test_scan_error_counted(self) -> None:
        def _raise(*a, **kw):
            raise RuntimeError("network error")

        with patch("scanner.scanner.SignalEngine") as MockEngine:
            MockEngine.return_value.run = AsyncMock(side_effect=_raise)
            scanner = MarketScanner()
            result = await scanner.scan(["btc_usdt"], "rsi_reversal")
        assert result.failed == 1
        assert result.succeeded == 0
        assert result.results[0].error is not None

    @pytest.mark.asyncio
    async def test_scan_caps_at_max_symbols(self) -> None:
        symbols = [f"sym{i}_usdt" for i in range(100)]
        with patch("scanner.scanner.SignalEngine") as MockEngine:
            MockEngine.return_value.run = AsyncMock(return_value=[])
            scanner = MarketScanner()
            result = await scanner.scan(symbols, "rsi_reversal")
        assert result.scanned <= 50

    @pytest.mark.asyncio
    async def test_results_sorted_by_signals_desc(self) -> None:
        def _make_signals(n: int):
            return [
                Signal(
                    timestamp=i * 3_600_000, symbol="x", market="spot",
                    interval="1h", strategy="rsi_reversal",
                    signal_type=SignalType.BUY, strength=1.0, price=100.0,
                )
                for i in range(n)
            ]

        call_count = 0
        async def _run(symbol, **kw):
            nonlocal call_count
            call_count += 1
            # btc gets 5 signals, eth gets 0
            return _make_signals(5) if symbol == "btc_usdt" else []

        with patch("scanner.scanner.SignalEngine") as MockEngine:
            MockEngine.return_value.run = _run
            scanner = MarketScanner()
            result = await scanner.scan(["eth_usdt", "btc_usdt"], "rsi_reversal")

        # btc (5 signals) should be first
        assert result.results[0].symbol == "btc_usdt"
        assert result.results[0].total_signals == 5
        assert result.results[1].symbol == "eth_usdt"
        assert result.results[1].total_signals == 0

    @pytest.mark.asyncio
    async def test_with_signals_filters_empty(self) -> None:
        async def _run(symbol, **kw):
            if symbol == "btc_usdt":
                return [Signal(
                    timestamp=0, symbol="btc_usdt", market="spot",
                    interval="1h", strategy="rsi_reversal",
                    signal_type=SignalType.BUY, strength=1.0, price=100.0,
                )]
            return []

        with patch("scanner.scanner.SignalEngine") as MockEngine:
            MockEngine.return_value.run = _run
            scanner = MarketScanner()
            result = await scanner.scan(["btc_usdt", "eth_usdt"], "rsi_reversal")

        assert len(result.with_signals()) == 1
        assert result.with_signals()[0].symbol == "btc_usdt"

    @pytest.mark.asyncio
    async def test_buy_sell_counts(self) -> None:
        def _make_signal(sig_type: SignalType) -> Signal:
            return Signal(
                timestamp=0, symbol="btc_usdt", market="spot",
                interval="1h", strategy="rsi_reversal",
                signal_type=sig_type, strength=1.0, price=100.0,
            )

        async def _run(symbol, **kw):
            return [_make_signal(SignalType.BUY), _make_signal(SignalType.BUY),
                    _make_signal(SignalType.SELL)]

        with patch("scanner.scanner.SignalEngine") as MockEngine:
            MockEngine.return_value.run = _run
            scanner = MarketScanner()
            result = await scanner.scan(["btc_usdt"], "rsi_reversal")

        r = result.results[0]
        assert r.buy_signals == 2
        assert r.sell_signals == 1
        assert r.total_signals == 3

    @pytest.mark.asyncio
    async def test_elapsed_ms_positive(self) -> None:
        with patch("scanner.scanner.SignalEngine") as MockEngine:
            MockEngine.return_value.run = AsyncMock(return_value=[])
            scanner = MarketScanner()
            result = await scanner.scan(["btc_usdt"], "rsi_reversal")
        assert result.elapsed_ms >= 0.0


class TestSymbolResultToDict:
    def test_to_dict_no_signal(self) -> None:
        r = SymbolResult(
            symbol="btc_usdt", market="spot", interval="1h",
            strategy="rsi_reversal", total_signals=0,
            buy_signals=0, sell_signals=0, latest_signal=None,
        )
        d = r.to_dict()
        assert d["symbol"] == "btc_usdt"
        assert d["latest_signal"] is None
        assert d["error"] is None

    def test_to_dict_with_error(self) -> None:
        r = SymbolResult(
            symbol="bad_usdt", market="spot", interval="1h",
            strategy="rsi_reversal", total_signals=0,
            buy_signals=0, sell_signals=0, latest_signal=None,
            error="timeout",
        )
        d = r.to_dict()
        assert d["error"] == "timeout"
