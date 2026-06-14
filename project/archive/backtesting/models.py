"""Data models for backtesting results."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Trade:
    entry_time: int
    exit_time: int
    entry_price: float
    exit_price: float
    direction: str  # "LONG"
    pnl: float
    pnl_pct: float

    def to_dict(self) -> dict:
        return {
            "entry_time": self.entry_time,
            "exit_time": self.exit_time,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "direction": self.direction,
            "pnl": round(self.pnl, 4),
            "pnl_pct": round(self.pnl_pct, 4),
        }


@dataclass
class BacktestResult:
    symbol: str
    interval: str
    strategy: str
    market: str
    initial_capital: float
    final_capital: float
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
