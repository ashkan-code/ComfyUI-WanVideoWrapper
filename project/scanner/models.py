"""Result models for the market scanner."""

from __future__ import annotations

from dataclasses import dataclass, field

from signals.models import Signal


@dataclass
class SymbolResult:
    symbol: str
    market: str
    interval: str
    strategy: str
    total_signals: int
    buy_signals: int
    sell_signals: int
    latest_signal: Signal | None
    error: str | None = None
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "market": self.market,
            "interval": self.interval,
            "strategy": self.strategy,
            "total_signals": self.total_signals,
            "buy_signals": self.buy_signals,
            "sell_signals": self.sell_signals,
            "latest_signal": self.latest_signal.to_dict() if self.latest_signal else None,
            "error": self.error,
            "elapsed_ms": round(self.elapsed_ms, 1),
        }


@dataclass
class ScanResult:
    strategy: str
    interval: str
    market: str
    scanned: int
    succeeded: int
    failed: int
    results: list[SymbolResult] = field(default_factory=list)
    elapsed_ms: float = 0.0

    def with_signals(self) -> list[SymbolResult]:
        """Only results that produced at least one signal."""
        return [r for r in self.results if r.total_signals > 0 and r.error is None]

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "interval": self.interval,
            "market": self.market,
            "scanned": self.scanned,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "results": [r.to_dict() for r in self.results],
        }
