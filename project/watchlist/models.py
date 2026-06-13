"""Dataclasses for watchlist entries and alert records."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WatchlistEntry:
    id: int
    symbol: str
    strategy: str
    interval: str
    market: str
    created_at: int

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "strategy": self.strategy,
            "interval": self.interval,
            "market": self.market,
            "created_at": self.created_at,
        }


@dataclass
class AlertRecord:
    id: int
    symbol: str
    strategy: str
    interval: str
    market: str
    signal_type: str
    price: float
    signal_timestamp: int
    notified_at: int

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "strategy": self.strategy,
            "interval": self.interval,
            "market": self.market,
            "signal_type": self.signal_type,
            "price": self.price,
            "signal_timestamp": self.signal_timestamp,
            "notified_at": self.notified_at,
        }
