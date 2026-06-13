"""Core data models for trading signals."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class Signal:
    symbol: str
    market: str
    interval: str
    timestamp: int          # bar open_time in Unix milliseconds
    signal_type: SignalType
    strategy: str
    price: float
    strength: float = 1.0   # 0.0–1.0; fraction of rules agreeing
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "signal": self.signal_type.value,
            "strategy": self.strategy,
            "symbol": self.symbol,
            "market": self.market,
            "interval": self.interval,
            "price": self.price,
            "strength": round(self.strength, 4),
            "metadata": self.metadata,
        }
