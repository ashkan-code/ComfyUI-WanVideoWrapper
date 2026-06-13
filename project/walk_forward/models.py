"""Result models for walk-forward validation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WFWindow:
    window_idx: int
    train_bars: int
    test_bars: int
    best_params: dict
    train_metrics: dict   # optimizer's in-sample best
    test_metrics: dict    # backtest on out-of-sample slice
    test_trades: int

    def to_dict(self) -> dict:
        return {
            "window_idx": self.window_idx,
            "train_bars": self.train_bars,
            "test_bars": self.test_bars,
            "best_params": self.best_params,
            "train_metrics": self.train_metrics,
            "test_metrics": self.test_metrics,
            "test_trades": self.test_trades,
        }


@dataclass
class WFResult:
    symbol: str
    interval: str
    market: str
    template: str
    optimize_for: str
    requested_windows: int
    completed_windows: int
    train_ratio: float
    windows: list[WFWindow] = field(default_factory=list)
    aggregate: dict = field(default_factory=dict)
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "market": self.market,
            "template": self.template,
            "optimize_for": self.optimize_for,
            "requested_windows": self.requested_windows,
            "completed_windows": self.completed_windows,
            "train_ratio": self.train_ratio,
            "aggregate": self.aggregate,
            "windows": [w.to_dict() for w in self.windows],
            "elapsed_ms": round(self.elapsed_ms, 1),
        }
