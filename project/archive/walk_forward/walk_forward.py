"""Walk-forward validator: train on each window, test on the next slice."""

from __future__ import annotations

import logging
import time
from typing import Callable

import pandas as pd

from backtesting.engine import Backtester
from optimizer.optimizer import StrategyOptimizer
from optimizer.templates import get_template
from signals.strategy import Strategy
from walk_forward.models import WFResult, WFWindow

logger = logging.getLogger(__name__)

_MIN_BARS_PER_WINDOW = 30   # absolute minimum to produce meaningful signals
_MAX_WINDOWS = 20


class WalkForwardValidator:
    """Rolling walk-forward: split data into N windows, optimise on train, test on hold-out.

    For each window *i*:
      - train slice: bars [i*w : i*w + int(w*train_ratio)]
      - test  slice: bars [i*w + int(w*train_ratio) : (i+1)*w]

    Aggregates out-of-sample metrics across all completed windows and computes
    an overfitting ratio (avg in-sample metric / avg out-of-sample metric).
    """

    def __init__(
        self,
        initial_capital: float = 10_000.0,
        commission_pct: float = 0.001,
    ) -> None:
        self._optimizer = StrategyOptimizer(
            initial_capital=initial_capital,
            commission_pct=commission_pct,
        )
        self._backtester = Backtester(
            initial_capital=initial_capital,
            commission_pct=commission_pct,
        )

    def validate(
        self,
        df: pd.DataFrame,
        template_name: str,
        param_grid: dict[str, list],
        optimize_for: str = "sharpe_ratio",
        n_windows: int = 5,
        train_ratio: float = 0.7,
        symbol: str = "",
        interval: str = "",
        market: str = "spot",
    ) -> WFResult:
        """Run walk-forward validation and return aggregated out-of-sample stats.

        Args:
            df:            Full OHLCV DataFrame (pre-fetched).
            template_name: Optimisable template: 'rsi' | 'ema_cross' | 'macd' | 'bb'
            param_grid:    Parameter grid passed to StrategyOptimizer.
            optimize_for:  In-sample metric to maximise per window.
            n_windows:     Number of rolling windows (max 20).
            train_ratio:   Fraction of each window used for training (0.5–0.9).

        Raises:
            ValueError: Too few bars for the requested window count, or bad args.
        """
        n_windows = min(n_windows, _MAX_WINDOWS)
        if not (0.3 <= train_ratio <= 0.9):
            raise ValueError("train_ratio must be between 0.3 and 0.9")

        total_bars = len(df)
        window_size = total_bars // n_windows

        if window_size < _MIN_BARS_PER_WINDOW:
            raise ValueError(
                f"Only {window_size} bars per window (need ≥ {_MIN_BARS_PER_WINDOW}). "
                f"Increase lookback or reduce n_windows."
            )

        tmpl = get_template(template_name)
        factory: Callable[[dict], Strategy] = tmpl["factory"]

        t0 = time.monotonic()
        windows: list[WFWindow] = []

        for i in range(n_windows):
            start = i * window_size
            end = (i + 1) * window_size
            train_end = start + int(window_size * train_ratio)

            train_df = df.iloc[start:train_end].reset_index(drop=True)
            test_df = df.iloc[train_end:end].reset_index(drop=True)

            if len(train_df) < 10 or len(test_df) < 5:
                logger.debug("Window %d skipped: too few bars", i)
                continue

            opt = self._optimizer.optimize(
                df=train_df,
                factory=factory,
                param_grid=param_grid,
                symbol=symbol,
                interval=interval,
                market=market,
                template=template_name,
                optimize_for=optimize_for,
            )

            if opt.best is None:
                logger.debug("Window %d skipped: optimizer found no valid trials", i)
                continue

            best_params = opt.best.params
            train_metrics = opt.best.metrics

            try:
                strategy = factory(best_params)
            except (ValueError, TypeError):
                continue

            test_signals = strategy.generate(
                test_df, symbol=symbol, market=market, interval=interval
            )
            bt = self._backtester.run(
                df=test_df,
                signals=test_signals,
                symbol=symbol,
                interval=interval,
                strategy=strategy.name,
                market=market,
            )

            windows.append(WFWindow(
                window_idx=i,
                train_bars=len(train_df),
                test_bars=len(test_df),
                best_params=best_params,
                train_metrics=train_metrics,
                test_metrics=bt.metrics,
                test_trades=len(bt.trades),
            ))
            logger.debug(
                "Window %d: best_params=%s test_return=%.2f%%",
                i, best_params, bt.metrics.get("total_return_pct", 0),
            )

        aggregate = _aggregate(windows, optimize_for)

        return WFResult(
            symbol=symbol,
            interval=interval,
            market=market,
            template=template_name,
            optimize_for=optimize_for,
            requested_windows=n_windows,
            completed_windows=len(windows),
            train_ratio=train_ratio,
            windows=windows,
            aggregate=aggregate,
            elapsed_ms=(time.monotonic() - t0) * 1000.0,
        )


def _aggregate(windows: list[WFWindow], optimize_for: str) -> dict:
    if not windows:
        return {}

    def _avg(key: str) -> float | None:
        vals = [
            w.test_metrics[key]
            for w in windows
            if w.test_metrics.get(key) is not None
        ]
        return round(sum(vals) / len(vals), 4) if vals else None

    profitable = sum(
        1 for w in windows
        if (w.test_metrics.get("total_return_pct") or 0.0) > 0
    )

    train_vals = [(w.train_metrics.get(optimize_for) or 0.0) for w in windows]
    test_vals  = [(w.test_metrics.get(optimize_for) or 0.0) for w in windows]
    avg_train = sum(train_vals) / len(train_vals)
    avg_test  = sum(test_vals) / len(test_vals)

    # Overfitting ratio: > 1 means in-sample looks better than out-of-sample
    if avg_test != 0:
        overfitting_ratio = round(avg_train / avg_test, 4)
    else:
        overfitting_ratio = None

    return {
        "avg_test_return_pct":   _avg("total_return_pct"),
        "avg_test_sharpe":       _avg("sharpe_ratio"),
        "avg_test_win_rate_pct": _avg("win_rate_pct"),
        "avg_test_max_drawdown": _avg("max_drawdown_pct"),
        "avg_test_trades":       round(sum(w.test_trades for w in windows) / len(windows), 1),
        "profitable_windows":    profitable,
        "total_windows":         len(windows),
        "consistency_pct":       round(profitable / len(windows) * 100, 1),
        f"avg_train_{optimize_for}": round(avg_train, 4),
        f"avg_test_{optimize_for}":  round(avg_test, 4),
        "overfitting_ratio":     overfitting_ratio,
    }
