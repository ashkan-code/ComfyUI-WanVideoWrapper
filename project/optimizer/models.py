"""Result models for strategy optimization."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TrialResult:
    params: dict
    metrics: dict
    final_capital: float
    num_trades: int
    rank: int = 0

    def to_dict(self) -> dict:
        return {
            "rank": self.rank,
            "params": self.params,
            "metrics": self.metrics,
            "final_capital": round(self.final_capital, 4),
            "num_trades": self.num_trades,
        }


@dataclass
class OptimizationResult:
    symbol: str
    interval: str
    market: str
    template: str
    optimize_for: str
    total_trials: int
    skipped_trials: int
    best: TrialResult | None
    trials: list[TrialResult] = field(default_factory=list)
    elapsed_ms: float = 0.0

    def to_dict(self, top_n: int = 10) -> dict:
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "market": self.market,
            "template": self.template,
            "optimize_for": self.optimize_for,
            "total_trials": self.total_trials,
            "skipped_trials": self.skipped_trials,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "best": self.best.to_dict() if self.best else None,
            "top_results": [t.to_dict() for t in self.trials[:top_n]],
        }
