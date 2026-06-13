"""StrategyOptimizer: grid search over strategy parameters using the backtester."""

from __future__ import annotations

import itertools
import logging
import time
from typing import Callable

import pandas as pd

from backtesting.engine import Backtester
from optimizer.models import OptimizationResult, TrialResult
from signals.strategy import Strategy

logger = logging.getLogger(__name__)

_MAX_TRIALS = 100
_VALID_METRICS = {
    "sharpe_ratio", "total_return_pct", "win_rate_pct",
    "profit_factor", "max_drawdown_pct",
}


class StrategyOptimizer:
    """Exhaustive grid search: tries every parameter combination and ranks by metric."""

    def __init__(
        self,
        initial_capital: float = 10_000.0,
        commission_pct: float = 0.001,
    ) -> None:
        self._backtester = Backtester(
            initial_capital=initial_capital,
            commission_pct=commission_pct,
        )

    def optimize(
        self,
        df: pd.DataFrame,
        factory: Callable[[dict], Strategy],
        param_grid: dict[str, list],
        symbol: str = "",
        interval: str = "",
        market: str = "spot",
        template: str = "",
        optimize_for: str = "sharpe_ratio",
    ) -> OptimizationResult:
        """Run grid search and return results sorted by *optimize_for* (descending).

        Invalid parameter combinations (e.g. fast >= slow for EMA) are silently
        skipped and counted in *skipped_trials*.

        Args:
            df:           OHLCV DataFrame (already fetched).
            factory:      Callable that builds a Strategy from a params dict.
            param_grid:   Dict mapping param name → list of values to try.
            optimize_for: Metric to maximise. For max_drawdown_pct minimisation
                          is used automatically.

        Returns:
            OptimizationResult with trials sorted best→worst.
        """
        if optimize_for not in _VALID_METRICS:
            raise ValueError(
                f"optimize_for must be one of {sorted(_VALID_METRICS)}, got {optimize_for!r}"
            )

        t0 = time.monotonic()
        keys = list(param_grid.keys())
        combos = list(itertools.product(*param_grid.values()))

        # Cap total trials
        if len(combos) > _MAX_TRIALS:
            logger.warning("Capping grid search from %d to %d trials", len(combos), _MAX_TRIALS)
            combos = combos[:_MAX_TRIALS]

        trials: list[TrialResult] = []
        skipped = 0

        for combo in combos:
            params = dict(zip(keys, combo))
            try:
                strategy = factory(params)
            except (ValueError, TypeError):
                skipped += 1
                continue

            signals = strategy.generate(df, symbol=symbol, market=market, interval=interval)
            bt_result = self._backtester.run(
                df=df, signals=signals,
                symbol=symbol, interval=interval,
                strategy=strategy.name, market=market,
            )

            trials.append(TrialResult(
                params=params,
                metrics=bt_result.metrics,
                final_capital=bt_result.final_capital,
                num_trades=len(bt_result.trades),
            ))

        # Sort: maximise all metrics except max_drawdown_pct (minimise that)
        reverse = optimize_for != "max_drawdown_pct"
        trials.sort(
            key=lambda t: self._sort_key(t, optimize_for),
            reverse=reverse,
        )
        for rank, trial in enumerate(trials, start=1):
            trial.rank = rank

        return OptimizationResult(
            symbol=symbol,
            interval=interval,
            market=market,
            template=template,
            optimize_for=optimize_for,
            total_trials=len(trials),
            skipped_trials=skipped,
            best=trials[0] if trials else None,
            trials=trials,
            elapsed_ms=(time.monotonic() - t0) * 1000.0,
        )

    @staticmethod
    def _sort_key(trial: TrialResult, metric: str) -> float:
        val = trial.metrics.get(metric)
        if val is None:
            return -1e9
        return float(val)
