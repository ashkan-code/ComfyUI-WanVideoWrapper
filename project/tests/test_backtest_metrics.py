"""Tests for backtesting metrics computation."""

from __future__ import annotations

import math

import pytest

from backtesting.metrics import _max_drawdown, _sharpe_ratio, compute_metrics
from backtesting.models import Trade


def _trade(pnl: float, pnl_pct: float) -> Trade:
    return Trade(
        entry_time=0,
        exit_time=1,
        entry_price=100.0,
        exit_price=100.0 + pnl,
        direction="LONG",
        pnl=pnl,
        pnl_pct=pnl_pct,
    )


class TestComputeMetrics:
    def test_no_trades_returns_zeros(self) -> None:
        m = compute_metrics([], [10_000.0], 10_000.0)
        assert m["num_trades"] == 0
        assert m["total_return_pct"] == 0.0
        assert m["win_rate_pct"] == 0.0

    def test_all_winning_trades(self) -> None:
        trades = [_trade(100.0, 10.0), _trade(50.0, 5.0)]
        curve = [10_000.0, 10_100.0, 10_150.0]
        m = compute_metrics(trades, curve, 10_000.0)
        assert m["win_rate_pct"] == pytest.approx(100.0)
        assert m["gross_loss"] == 0.0
        assert m["profit_factor"] is None  # inf

    def test_all_losing_trades(self) -> None:
        trades = [_trade(-100.0, -10.0), _trade(-50.0, -5.0)]
        curve = [10_000.0, 9_900.0, 9_850.0]
        m = compute_metrics(trades, curve, 10_000.0)
        assert m["win_rate_pct"] == pytest.approx(0.0)
        assert m["gross_profit"] == 0.0
        assert m["profit_factor"] == pytest.approx(0.0)

    def test_mixed_trades(self) -> None:
        trades = [_trade(200.0, 20.0), _trade(-100.0, -10.0)]
        curve = [10_000.0, 10_200.0, 10_100.0]
        m = compute_metrics(trades, curve, 10_000.0)
        assert m["win_rate_pct"] == pytest.approx(50.0)
        assert m["profit_factor"] == pytest.approx(2.0)
        assert m["num_trades"] == 2

    def test_total_return_pct(self) -> None:
        trades = [_trade(1000.0, 10.0)]
        curve = [10_000.0, 11_000.0]
        m = compute_metrics(trades, curve, 10_000.0)
        assert m["total_return_pct"] == pytest.approx(10.0)

    def test_best_worst_avg(self) -> None:
        trades = [_trade(100.0, 10.0), _trade(-50.0, -5.0), _trade(20.0, 2.0)]
        curve = [10_000.0, 10_100.0, 10_050.0, 10_070.0]
        m = compute_metrics(trades, curve, 10_000.0)
        assert m["best_trade_pct"] == pytest.approx(10.0)
        assert m["worst_trade_pct"] == pytest.approx(-5.0)
        assert m["avg_trade_pct"] == pytest.approx((10.0 - 5.0 + 2.0) / 3, abs=1e-3)


class TestMaxDrawdown:
    def test_no_drawdown_flat(self) -> None:
        assert _max_drawdown([100.0, 100.0, 100.0]) == pytest.approx(0.0)

    def test_monotone_increase_no_drawdown(self) -> None:
        assert _max_drawdown([100.0, 110.0, 120.0]) == pytest.approx(0.0)

    def test_simple_drawdown(self) -> None:
        # Peak 200, trough 100 → 50% drawdown
        dd = _max_drawdown([100.0, 200.0, 100.0])
        assert dd == pytest.approx(50.0)

    def test_single_element(self) -> None:
        assert _max_drawdown([100.0]) == pytest.approx(0.0)

    def test_drawdown_not_from_start(self) -> None:
        # Peak occurs mid-series
        dd = _max_drawdown([100.0, 150.0, 300.0, 150.0])
        assert dd == pytest.approx(50.0)


class TestSharpeRatio:
    def test_flat_returns_zero(self) -> None:
        assert _sharpe_ratio([100.0, 100.0, 100.0]) == pytest.approx(0.0)

    def test_single_element_returns_zero(self) -> None:
        assert _sharpe_ratio([100.0]) == pytest.approx(0.0)

    def test_positive_returns_positive_sharpe(self) -> None:
        # Steadily rising equity → positive Sharpe
        curve = [100.0 + i for i in range(50)]
        sharpe = _sharpe_ratio(curve)
        assert sharpe > 0.0

    def test_negative_returns_negative_sharpe(self) -> None:
        curve = [100.0 - i * 0.5 for i in range(50)]
        sharpe = _sharpe_ratio(curve)
        assert sharpe < 0.0
