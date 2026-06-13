"""Tests for StrategyOptimizer and templates."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from optimizer.models import OptimizationResult, TrialResult
from optimizer.optimizer import StrategyOptimizer, _MAX_TRIALS
from optimizer.templates import _build_ema_cross, _build_rsi, get_template, list_templates


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


def _sinusoidal(n: int = 120) -> list[float]:
    return [50.0 + 15.0 * math.sin(i / 8) for i in range(n)]


class TestTemplates:
    def test_list_templates_returns_all(self) -> None:
        names = list_templates()
        assert set(names) == {"rsi", "ema_cross", "macd", "bb"}

    def test_get_known_template(self) -> None:
        t = get_template("rsi")
        assert "factory" in t
        assert "default_grid" in t

    def test_get_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown template"):
            get_template("nonexistent")

    def test_build_rsi(self) -> None:
        strat = _build_rsi({"period": 14, "buy_level": 30, "sell_level": 70})
        assert strat.name == "rsi_opt"

    def test_build_ema_valid(self) -> None:
        strat = _build_ema_cross({"fast": 9, "slow": 21})
        assert strat.name == "ema_opt"

    def test_build_ema_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="fast"):
            _build_ema_cross({"fast": 21, "slow": 9})

    def test_build_ema_equal_raises(self) -> None:
        with pytest.raises(ValueError):
            _build_ema_cross({"fast": 20, "slow": 20})


class TestStrategyOptimizer:
    def test_invalid_metric_raises(self) -> None:
        opt = StrategyOptimizer()
        tmpl = get_template("rsi")
        with pytest.raises(ValueError, match="optimize_for"):
            opt.optimize(
                df=_df(_sinusoidal()),
                factory=tmpl["factory"],
                param_grid={"period": [14], "buy_level": [30], "sell_level": [70]},
                optimize_for="nonsense_metric",
            )

    def test_returns_optimization_result(self) -> None:
        opt = StrategyOptimizer()
        tmpl = get_template("rsi")
        result = opt.optimize(
            df=_df(_sinusoidal()),
            factory=tmpl["factory"],
            param_grid={"period": [14], "buy_level": [30], "sell_level": [70]},
        )
        assert isinstance(result, OptimizationResult)

    def test_trial_count_matches_grid(self) -> None:
        opt = StrategyOptimizer()
        tmpl = get_template("rsi")
        grid = {"period": [10, 14], "buy_level": [25, 30], "sell_level": [70, 75]}
        result = opt.optimize(
            df=_df(_sinusoidal()),
            factory=tmpl["factory"],
            param_grid=grid,
        )
        # 2 * 2 * 2 = 8 valid combos
        assert result.total_trials == 8

    def test_invalid_combos_skipped(self) -> None:
        opt = StrategyOptimizer()
        tmpl = get_template("ema_cross")
        # fast >= slow for some combos → skipped
        grid = {"fast": [20, 50], "slow": [20, 50]}
        result = opt.optimize(
            df=_df(_sinusoidal()),
            factory=tmpl["factory"],
            param_grid=grid,
        )
        # fast=20,slow=20 and fast=50,slow=20 are invalid
        assert result.skipped_trials >= 2

    def test_trials_sorted_by_sharpe_desc(self) -> None:
        opt = StrategyOptimizer()
        tmpl = get_template("rsi")
        grid = {"period": [10, 14, 21], "buy_level": [25, 30], "sell_level": [70, 75]}
        result = opt.optimize(
            df=_df(_sinusoidal()),
            factory=tmpl["factory"],
            param_grid=grid,
            optimize_for="sharpe_ratio",
        )
        sharpes = [t.metrics.get("sharpe_ratio", 0) or 0 for t in result.trials]
        assert sharpes == sorted(sharpes, reverse=True)

    def test_max_drawdown_sorted_asc(self) -> None:
        opt = StrategyOptimizer()
        tmpl = get_template("rsi")
        grid = {"period": [10, 14], "buy_level": [25, 30], "sell_level": [70, 75]}
        result = opt.optimize(
            df=_df(_sinusoidal()),
            factory=tmpl["factory"],
            param_grid=grid,
            optimize_for="max_drawdown_pct",
        )
        dds = [t.metrics.get("max_drawdown_pct", 0) for t in result.trials]
        assert dds == sorted(dds)  # ascending (minimised)

    def test_best_is_first_trial(self) -> None:
        opt = StrategyOptimizer()
        tmpl = get_template("rsi")
        grid = {"period": [14], "buy_level": [30], "sell_level": [70]}
        result = opt.optimize(
            df=_df(_sinusoidal()),
            factory=tmpl["factory"],
            param_grid=grid,
        )
        assert result.best is result.trials[0]

    def test_trials_ranked(self) -> None:
        opt = StrategyOptimizer()
        tmpl = get_template("rsi")
        grid = {"period": [10, 14], "buy_level": [30], "sell_level": [70]}
        result = opt.optimize(
            df=_df(_sinusoidal()),
            factory=tmpl["factory"],
            param_grid=grid,
        )
        ranks = [t.rank for t in result.trials]
        assert ranks == list(range(1, len(ranks) + 1))

    def test_grid_capped_at_max_trials(self) -> None:
        opt = StrategyOptimizer()
        tmpl = get_template("rsi")
        # 10 * 10 * 10 = 1000 combinations — must be capped
        grid = {
            "period":    list(range(5, 15)),
            "buy_level": list(range(20, 30)),
            "sell_level":list(range(65, 75)),
        }
        result = opt.optimize(
            df=_df(_sinusoidal()),
            factory=tmpl["factory"],
            param_grid=grid,
        )
        assert result.total_trials + result.skipped_trials <= _MAX_TRIALS

    def test_empty_df_gives_no_trades(self) -> None:
        opt = StrategyOptimizer()
        tmpl = get_template("rsi")
        result = opt.optimize(
            df=pd.DataFrame(),
            factory=tmpl["factory"],
            param_grid={"period": [14], "buy_level": [30], "sell_level": [70]},
        )
        # No signals on empty df → 0 trades
        for t in result.trials:
            assert t.num_trades == 0

    def test_to_dict_structure(self) -> None:
        opt = StrategyOptimizer()
        tmpl = get_template("rsi")
        result = opt.optimize(
            df=_df(_sinusoidal()),
            factory=tmpl["factory"],
            param_grid={"period": [14], "buy_level": [30], "sell_level": [70]},
            symbol="btc_usdt", interval="1h", market="spot", template="rsi",
        )
        d = result.to_dict()
        assert d["symbol"] == "btc_usdt"
        assert "best" in d
        assert "top_results" in d
        assert isinstance(d["top_results"], list)

    def test_ema_template_works(self) -> None:
        opt = StrategyOptimizer()
        tmpl = get_template("ema_cross")
        result = opt.optimize(
            df=_df(_sinusoidal()),
            factory=tmpl["factory"],
            param_grid={"fast": [5, 9], "slow": [20, 50]},
        )
        assert result.total_trials + result.skipped_trials > 0

    def test_bb_template_works(self) -> None:
        opt = StrategyOptimizer()
        tmpl = get_template("bb")
        result = opt.optimize(
            df=_df(_sinusoidal()),
            factory=tmpl["factory"],
            param_grid={"period": [14, 20], "std": [1.5, 2.0]},
        )
        assert result.total_trials >= 4
