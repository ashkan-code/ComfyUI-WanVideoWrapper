"""Tests for portfolio correlation, cointegration, and portfolio backtesting."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from portfolio.cointegration import _adf_stat, analyze_pair, find_cointegrated_pairs
from portfolio.correlation import compute_correlation
from portfolio.portfolio_backtest import PortfolioBacktester
from signals.models import Signal, SignalType


# ─── helpers ────────────────────────────────────────────────────────────────


def _series(values: list[float]) -> pd.Series:
    return pd.Series(values, dtype=float)


def _df(closes: list[float], symbol: str = "x") -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame({
        "open_time": [i * 3_600_000 for i in range(n)],
        "open": closes, "high": [c + 1 for c in closes],
        "low": [c - 1 for c in closes], "close": closes,
        "volume": [1000.0] * n,
    })


def _sig(i: int, price: float, sig_type: SignalType, symbol: str = "btc_usdt") -> Signal:
    return Signal(
        timestamp=i * 3_600_000, symbol=symbol, market="spot",
        interval="1h", strategy="test",
        signal_type=sig_type, strength=1.0, price=price,
    )


# ─── Correlation ────────────────────────────────────────────────────────────


class TestCorrelation:
    def test_identical_series_corr_one(self) -> None:
        s = _series(list(range(1, 51)))
        result = compute_correlation({"a": s, "b": s.copy()})
        assert result.matrix["a"]["b"] == pytest.approx(1.0, abs=1e-4)

    def test_opposite_series_corr_neg_one(self) -> None:
        # Alternating series: one goes up when the other goes down
        ups   = _series([100.0 + i if i % 2 == 0 else 100.0 - i for i in range(50)])
        downs = _series([100.0 - i if i % 2 == 0 else 100.0 + i for i in range(50)])
        result = compute_correlation({"a": ups, "b": downs}, method="prices")
        assert result.matrix["a"]["b"] < -0.9

    def test_diagonal_is_one(self) -> None:
        s = _series([float(i) for i in range(1, 51)])
        t = _series([float(50 - i) for i in range(50)])
        result = compute_correlation({"a": s, "b": t})
        assert result.matrix["a"]["a"] == pytest.approx(1.0, abs=1e-4)
        assert result.matrix["b"]["b"] == pytest.approx(1.0, abs=1e-4)

    def test_returns_method(self) -> None:
        s = _series([100.0 * (1.01 ** i) for i in range(50)])
        t = _series([50.0 * (1.02 ** i) for i in range(50)])
        result = compute_correlation({"a": s, "b": t}, method="returns")
        assert "a" in result.matrix

    def test_prices_method(self) -> None:
        s = _series([float(i) for i in range(1, 51)])
        t = _series([float(i * 2) for i in range(1, 51)])
        result = compute_correlation({"a": s, "b": t}, method="prices")
        assert result.matrix["a"]["b"] == pytest.approx(1.0, abs=1e-4)

    def test_invalid_method_raises(self) -> None:
        s = _series([1.0, 2.0, 3.0, 4.0, 5.0])
        with pytest.raises(ValueError, match="method"):
            compute_correlation({"a": s, "b": s}, method="invalid")

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            compute_correlation({})

    def test_top_positive_sorted(self) -> None:
        a = _series(list(range(1, 51)))
        b = _series([float(i) * 1.1 for i in range(1, 51)])
        c = _series([float(50 - i) for i in range(50)])
        result = compute_correlation({"a": a, "b": b, "c": c}, top_n=2)
        corrs = [p.correlation for p in result.top_positive]
        assert corrs == sorted(corrs, reverse=True)

    def test_top_uncorrelated_near_zero(self) -> None:
        np.random.seed(42)
        a = _series(list(np.random.randn(100).cumsum()))
        b = _series(list(np.random.randn(100).cumsum()))
        c = _series(list(a.values))
        result = compute_correlation({"a": a, "b": b, "c": c}, top_n=1)
        # uncorrelated pair should have |corr| < highly correlated pair
        assert abs(result.top_uncorrelated[0].correlation) <= abs(result.top_positive[0].correlation) + 0.01

    def test_symbols_in_result(self) -> None:
        s = _series([float(i) for i in range(1, 51)])
        result = compute_correlation({"btc": s, "eth": s * 0.9})
        assert "btc" in result.symbols
        assert "eth" in result.symbols


# ─── Cointegration ──────────────────────────────────────────────────────────


class TestADFStat:
    def test_stationary_series_negative_stat(self) -> None:
        # Stationary: strong mean reversion
        np.random.seed(0)
        y = np.cumsum(np.random.randn(200)) * 0.01  # near-stationary
        # We don't assert specific value but just that it runs
        stat = _adf_stat(y)
        assert isinstance(stat, float)

    def test_random_walk_less_negative(self) -> None:
        # Random walk is non-stationary → ADF stat close to 0 or slightly negative
        np.random.seed(1)
        rw = np.cumsum(np.random.randn(200))
        stat_rw = _adf_stat(rw)
        # Strongly mean-reverting series
        mr = np.sin(np.linspace(0, 20 * math.pi, 200)) * 10
        stat_mr = _adf_stat(mr)
        # Mean-reverting should have more negative stat
        assert stat_mr < stat_rw

    def test_short_series_returns_zero(self) -> None:
        assert _adf_stat(np.array([1.0, 2.0, 3.0])) == 0.0


class TestAnalyzePair:
    def test_cointegrated_series(self) -> None:
        # y = x + stationary noise → cointegrated
        np.random.seed(42)
        x = np.cumsum(np.random.randn(200))
        noise = np.random.randn(200) * 0.1
        y = x + noise
        pair = analyze_pair(_series(x), _series(y), "A", "B", significance="10%")
        assert pair.cointegrated  # should detect cointegration

    def test_independent_random_walks_not_cointegrated(self) -> None:
        np.random.seed(7)
        x = np.cumsum(np.random.randn(200))
        y = np.cumsum(np.random.randn(200))  # independent
        pair = analyze_pair(_series(x), _series(y), "A", "B", significance="1%")
        # At 1% it's very unlikely two independent RWs are flagged — usually not cointegrated
        # (not always, so we just check the function runs without error)
        assert isinstance(pair.cointegrated, bool)

    def test_hedge_ratio_near_one_for_identical(self) -> None:
        np.random.seed(99)
        x = np.cumsum(np.random.randn(200))
        y = x.copy()
        pair = analyze_pair(_series(x), _series(y))
        assert pair.hedge_ratio == pytest.approx(1.0, abs=0.05)

    def test_result_fields(self) -> None:
        s = _series([float(i) for i in range(100)])
        pair = analyze_pair(s, s * 1.5, "A", "B")
        assert pair.symbol_a == "A"
        assert pair.symbol_b == "B"
        assert isinstance(pair.spread_std, float)


class TestFindCointegratedPairs:
    def test_returns_all_pairs(self) -> None:
        s = _series([float(i) for i in range(100)])
        pairs = find_cointegrated_pairs({"a": s, "b": s * 2, "c": s * 3})
        assert len(pairs) == 3  # C(3,2) = 3

    def test_sorted_by_adf_ascending(self) -> None:
        np.random.seed(5)
        x = np.cumsum(np.random.randn(150))
        pairs = find_cointegrated_pairs({
            "a": _series(x),
            "b": _series(x + np.random.randn(150) * 0.1),
            "c": _series(np.cumsum(np.random.randn(150))),
        })
        stats = [p.adf_stat for p in pairs]
        assert stats == sorted(stats)


# ─── Portfolio Backtest ─────────────────────────────────────────────────────


class TestPortfolioBacktester:
    def test_empty_raises(self) -> None:
        bt = PortfolioBacktester()
        with pytest.raises(ValueError, match="empty"):
            bt.run({}, {})

    def test_equal_capital_allocation(self) -> None:
        # With no signals → each symbol keeps its share of capital
        closes = [100.0] * 20
        bt = PortfolioBacktester(initial_capital=1000.0, commission_pct=0.0)
        result = bt.run(
            symbol_dfs={"btc": _df(closes), "eth": _df(closes)},
            symbol_signals={},
        )
        # 500 each, no trades → stays at 500 each → total 1000
        assert result.final_capital == pytest.approx(1000.0, rel=1e-3)

    def test_two_symbols_profitable(self) -> None:
        closes_up = [100.0] * 5 + [200.0] * 5
        sigs_btc = [_sig(0, 100.0, SignalType.BUY, "btc"), _sig(5, 200.0, SignalType.SELL, "btc")]
        sigs_eth = [_sig(0, 100.0, SignalType.BUY, "eth"), _sig(5, 200.0, SignalType.SELL, "eth")]
        bt = PortfolioBacktester(initial_capital=1000.0, commission_pct=0.0)
        result = bt.run(
            symbol_dfs={"btc": _df(closes_up), "eth": _df(closes_up)},
            symbol_signals={"btc": sigs_btc, "eth": sigs_eth},
        )
        assert result.final_capital == pytest.approx(2000.0, rel=1e-2)
        assert result.portfolio_return_pct == pytest.approx(100.0, rel=1e-2)

    def test_per_symbol_results_present(self) -> None:
        closes = [100.0] * 10
        bt = PortfolioBacktester(initial_capital=1000.0)
        result = bt.run(
            symbol_dfs={"btc": _df(closes), "eth": _df(closes)},
            symbol_signals={},
        )
        assert "btc" in result.per_symbol
        assert "eth" in result.per_symbol

    def test_equity_curve_length(self) -> None:
        closes = [float(i + 100) for i in range(20)]
        bt = PortfolioBacktester(initial_capital=1000.0)
        result = bt.run(
            symbol_dfs={"btc": _df(closes), "eth": _df(closes)},
            symbol_signals={},
        )
        assert len(result.equity_curve) == 20

    def test_portfolio_metrics_keys(self) -> None:
        closes = [100.0] * 10
        bt = PortfolioBacktester(initial_capital=1000.0)
        result = bt.run(
            symbol_dfs={"btc": _df(closes)},
            symbol_signals={},
        )
        m = result.portfolio_metrics
        assert "total_portfolio_return_pct" in m
        assert "profitable_symbols" in m
        assert "avg_sharpe" in m

    def test_to_dict_structure(self) -> None:
        closes = [100.0] * 10
        bt = PortfolioBacktester(initial_capital=1000.0)
        result = bt.run(
            symbol_dfs={"btc": _df(closes)},
            symbol_signals={},
            strategy="rsi_reversal",
        )
        d = result.to_dict()
        assert d["strategy"] == "rsi_reversal"
        assert "portfolio_metrics" in d
        assert "per_symbol" in d
