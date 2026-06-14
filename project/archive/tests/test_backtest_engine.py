"""Tests for the Backtester engine."""

from __future__ import annotations

import pandas as pd
import pytest

from backtesting.engine import Backtester
from backtesting.models import BacktestResult, Trade
from signals.models import Signal, SignalType


def _df(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame({
        "open_time": [i * 3_600_000 for i in range(n)],
        "open":   closes,
        "high":   [c + 1.0 for c in closes],
        "low":    [c - 1.0 for c in closes],
        "close":  closes,
        "volume": [1000.0] * n,
    })


def _sig(i: int, price: float, sig_type: SignalType) -> Signal:
    return Signal(
        timestamp=i * 3_600_000,
        symbol="btc_usdt",
        market="spot",
        interval="1h",
        strategy="test",
        signal_type=sig_type,
        strength=1.0,
        price=price,
    )


class TestBacktesterBasics:
    def test_invalid_capital_raises(self) -> None:
        with pytest.raises(ValueError, match="initial_capital"):
            Backtester(initial_capital=0.0)

    def test_invalid_commission_raises(self) -> None:
        with pytest.raises(ValueError, match="commission_pct"):
            Backtester(commission_pct=1.5)

    def test_empty_df_returns_no_trades(self) -> None:
        bt = Backtester()
        result = bt.run(pd.DataFrame(), signals=[], symbol="x")
        assert result.trades == []
        assert result.final_capital == bt.initial_capital

    def test_no_signals_returns_no_trades(self) -> None:
        bt = Backtester()
        result = bt.run(_df([100.0] * 50), signals=[])
        assert result.trades == []


class TestBacktesterTrades:
    def test_single_buy_sell_cycle(self) -> None:
        closes = [100.0] * 10 + [110.0] * 10
        signals = [
            _sig(0, 100.0, SignalType.BUY),
            _sig(10, 110.0, SignalType.SELL),
        ]
        bt = Backtester(initial_capital=1000.0, commission_pct=0.0)
        result = bt.run(_df(closes), signals=signals)
        assert len(result.trades) == 1
        t = result.trades[0]
        assert t.direction == "LONG"
        assert t.entry_price == pytest.approx(100.0)
        assert t.exit_price == pytest.approx(110.0)
        assert t.pnl_pct == pytest.approx(10.0)

    def test_profit_grows_capital(self) -> None:
        closes = [100.0] * 5 + [200.0] * 5
        signals = [
            _sig(0, 100.0, SignalType.BUY),
            _sig(5, 200.0, SignalType.SELL),
        ]
        bt = Backtester(initial_capital=1000.0, commission_pct=0.0)
        result = bt.run(_df(closes), signals=signals)
        assert result.final_capital == pytest.approx(2000.0, rel=1e-3)

    def test_commission_reduces_profit(self) -> None:
        closes = [100.0] * 5 + [200.0] * 5
        signals = [
            _sig(0, 100.0, SignalType.BUY),
            _sig(5, 200.0, SignalType.SELL),
        ]
        bt_no_comm = Backtester(initial_capital=1000.0, commission_pct=0.0)
        bt_comm    = Backtester(initial_capital=1000.0, commission_pct=0.001)
        no_comm = bt_no_comm.run(_df(closes), signals=signals).final_capital
        with_comm = bt_comm.run(_df(closes), signals=signals).final_capital
        assert with_comm < no_comm

    def test_sell_without_position_is_ignored(self) -> None:
        closes = [100.0] * 10
        signals = [_sig(0, 100.0, SignalType.SELL)]
        bt = Backtester(initial_capital=1000.0, commission_pct=0.0)
        result = bt.run(_df(closes), signals=signals)
        assert result.trades == []
        assert result.final_capital == pytest.approx(1000.0)

    def test_open_position_closed_at_last_bar(self) -> None:
        closes = [100.0] * 5 + [120.0] * 5
        signals = [_sig(0, 100.0, SignalType.BUY)]  # no SELL signal
        bt = Backtester(initial_capital=1000.0, commission_pct=0.0)
        result = bt.run(_df(closes), signals=signals)
        assert len(result.trades) == 1
        assert result.trades[0].exit_price == pytest.approx(120.0)

    def test_multiple_cycles(self) -> None:
        closes = [100.0, 100.0, 110.0, 110.0, 105.0, 105.0, 115.0, 115.0]
        signals = [
            _sig(0, 100.0, SignalType.BUY),
            _sig(2, 110.0, SignalType.SELL),
            _sig(4, 105.0, SignalType.BUY),
            _sig(6, 115.0, SignalType.SELL),
        ]
        bt = Backtester(initial_capital=1000.0, commission_pct=0.0)
        result = bt.run(_df(closes), signals=signals)
        assert len(result.trades) == 2

    def test_equity_curve_length_matches_df(self) -> None:
        closes = [100.0 + i for i in range(20)]
        signals = [_sig(0, 100.0, SignalType.BUY), _sig(10, 110.0, SignalType.SELL)]
        bt = Backtester(initial_capital=1000.0, commission_pct=0.0)
        result = bt.run(_df(closes), signals=signals)
        assert len(result.equity_curve) == len(closes)

    def test_result_fields_populated(self) -> None:
        closes = [100.0] * 5 + [110.0] * 5
        signals = [
            _sig(0, 100.0, SignalType.BUY),
            _sig(5, 110.0, SignalType.SELL),
        ]
        bt = Backtester(initial_capital=1000.0, commission_pct=0.0)
        result = bt.run(_df(closes), signals=signals, symbol="eth_usdt", interval="4h", strategy="rsi_reversal")
        assert result.symbol == "eth_usdt"
        assert result.interval == "4h"
        assert result.strategy == "rsi_reversal"
        assert result.metrics["num_trades"] == 1
        assert result.metrics["total_return_pct"] == pytest.approx(10.0, rel=1e-2)
