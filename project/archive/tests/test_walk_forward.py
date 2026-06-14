"""Tests for WalkForwardValidator."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from walk_forward.models import WFResult, WFWindow
from walk_forward.walk_forward import WalkForwardValidator, _aggregate


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


def _sinusoidal(n: int = 300) -> list[float]:
    return [50.0 + 15.0 * math.sin(i / 8) for i in range(n)]


def _small_grid() -> dict:
    # 2 combinations only → fast tests
    return {"period": [14, 21], "buy_level": [30], "sell_level": [70]}


class TestWalkForwardValidation:
    def test_returns_wf_result(self) -> None:
        wfv = WalkForwardValidator()
        result = wfv.validate(
            df=_df(_sinusoidal(300)),
            template_name="rsi",
            param_grid=_small_grid(),
            n_windows=3,
        )
        assert isinstance(result, WFResult)

    def test_completed_windows_leq_requested(self) -> None:
        wfv = WalkForwardValidator()
        result = wfv.validate(
            df=_df(_sinusoidal(300)),
            template_name="rsi",
            param_grid=_small_grid(),
            n_windows=5,
        )
        assert result.completed_windows <= result.requested_windows

    def test_window_bar_counts(self) -> None:
        n = 300
        n_windows = 3
        wfv = WalkForwardValidator()
        result = wfv.validate(
            df=_df(_sinusoidal(n)),
            template_name="rsi",
            param_grid=_small_grid(),
            n_windows=n_windows,
            train_ratio=0.7,
        )
        window_size = n // n_windows          # 100
        expected_train = int(window_size * 0.7)  # 70
        expected_test  = window_size - expected_train  # 30
        for w in result.windows:
            assert w.train_bars == expected_train
            assert w.test_bars  == expected_test

    def test_windows_have_best_params(self) -> None:
        wfv = WalkForwardValidator()
        result = wfv.validate(
            df=_df(_sinusoidal(300)),
            template_name="rsi",
            param_grid=_small_grid(),
            n_windows=3,
        )
        for w in result.windows:
            assert "period" in w.best_params
            assert "buy_level" in w.best_params

    def test_aggregate_keys_present(self) -> None:
        wfv = WalkForwardValidator()
        result = wfv.validate(
            df=_df(_sinusoidal(300)),
            template_name="rsi",
            param_grid=_small_grid(),
            n_windows=3,
        )
        agg = result.aggregate
        assert "avg_test_return_pct"   in agg
        assert "avg_test_sharpe"       in agg
        assert "consistency_pct"       in agg
        assert "overfitting_ratio"     in agg or agg.get("overfitting_ratio") is None
        assert "profitable_windows"    in agg

    def test_consistency_pct_in_range(self) -> None:
        wfv = WalkForwardValidator()
        result = wfv.validate(
            df=_df(_sinusoidal(300)),
            template_name="rsi",
            param_grid=_small_grid(),
            n_windows=3,
        )
        pct = result.aggregate.get("consistency_pct", 0)
        assert 0.0 <= pct <= 100.0

    def test_invalid_train_ratio_raises(self) -> None:
        wfv = WalkForwardValidator()
        with pytest.raises(ValueError, match="train_ratio"):
            wfv.validate(
                df=_df(_sinusoidal(300)),
                template_name="rsi",
                param_grid=_small_grid(),
                train_ratio=0.99,
            )

    def test_too_few_bars_raises(self) -> None:
        wfv = WalkForwardValidator()
        with pytest.raises(ValueError, match="bars per window"):
            wfv.validate(
                df=_df([50.0] * 10),
                template_name="rsi",
                param_grid=_small_grid(),
                n_windows=5,
            )

    def test_n_windows_capped(self) -> None:
        wfv = WalkForwardValidator()
        result = wfv.validate(
            df=_df(_sinusoidal(600)),
            template_name="rsi",
            param_grid=_small_grid(),
            n_windows=100,   # exceeds _MAX_WINDOWS
        )
        assert result.requested_windows <= 20

    def test_ema_template(self) -> None:
        wfv = WalkForwardValidator()
        result = wfv.validate(
            df=_df(_sinusoidal(300)),
            template_name="ema_cross",
            param_grid={"fast": [5, 9], "slow": [20, 50]},
            n_windows=3,
        )
        assert isinstance(result, WFResult)

    def test_to_dict_structure(self) -> None:
        wfv = WalkForwardValidator()
        result = wfv.validate(
            df=_df(_sinusoidal(300)),
            template_name="rsi",
            param_grid=_small_grid(),
            n_windows=3,
            symbol="btc_usdt",
        )
        d = result.to_dict()
        assert d["symbol"] == "btc_usdt"
        assert "aggregate" in d
        assert "windows" in d
        assert isinstance(d["windows"], list)

    def test_window_indices_sequential(self) -> None:
        wfv = WalkForwardValidator()
        result = wfv.validate(
            df=_df(_sinusoidal(300)),
            template_name="rsi",
            param_grid=_small_grid(),
            n_windows=3,
        )
        indices = [w.window_idx for w in result.windows]
        assert indices == sorted(indices)


class TestAggregate:
    def _make_window(self, ret: float, sharpe: float, trades: int = 2) -> WFWindow:
        return WFWindow(
            window_idx=0,
            train_bars=70,
            test_bars=30,
            best_params={"period": 14},
            train_metrics={"sharpe_ratio": sharpe + 1.0, "total_return_pct": ret + 5.0},
            test_metrics={
                "sharpe_ratio": sharpe,
                "total_return_pct": ret,
                "win_rate_pct": 50.0,
                "max_drawdown_pct": 5.0,
            },
            test_trades=trades,
        )

    def test_empty_windows_returns_empty(self) -> None:
        assert _aggregate([], "sharpe_ratio") == {}

    def test_avg_return_computed(self) -> None:
        windows = [self._make_window(10.0, 1.0), self._make_window(20.0, 2.0)]
        agg = _aggregate(windows, "sharpe_ratio")
        assert agg["avg_test_return_pct"] == pytest.approx(15.0)

    def test_profitable_windows_counted(self) -> None:
        windows = [
            self._make_window(10.0, 1.0),
            self._make_window(-5.0, -0.5),
            self._make_window(3.0, 0.3),
        ]
        agg = _aggregate(windows, "sharpe_ratio")
        assert agg["profitable_windows"] == 2
        assert agg["consistency_pct"] == pytest.approx(100 * 2 / 3, abs=0.1)

    def test_overfitting_ratio_gt_1_when_train_better(self) -> None:
        windows = [self._make_window(5.0, 0.5)]
        # train sharpe = 1.5, test sharpe = 0.5 → ratio = 3.0
        agg = _aggregate(windows, "sharpe_ratio")
        assert agg["overfitting_ratio"] == pytest.approx(3.0, rel=1e-2)

    def test_avg_test_trades(self) -> None:
        windows = [self._make_window(5.0, 0.5, trades=4), self._make_window(3.0, 0.3, trades=2)]
        agg = _aggregate(windows, "sharpe_ratio")
        assert agg["avg_test_trades"] == pytest.approx(3.0)
