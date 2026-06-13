"""Dataclasses for position sizing and risk report output."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PositionSize:
    method: str
    capital: float
    risk_pct: float       # fraction e.g. 0.01 = 1 %
    risk_amount: float    # capital × risk_pct
    entry_price: float
    stop_price: float
    quantity: float       # units to buy/sell
    position_value: float # quantity × entry_price

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "capital": round(self.capital, 2),
            "risk_pct": round(self.risk_pct * 100, 4),   # returned as %
            "risk_amount": round(self.risk_amount, 4),
            "entry_price": self.entry_price,
            "stop_price": round(self.stop_price, 8),
            "quantity": round(self.quantity, 8),
            "position_value": round(self.position_value, 4),
        }


@dataclass
class StopTarget:
    entry_price: float
    side: str              # "long" | "short"
    stop_price: float
    target_price: float
    stop_distance: float   # |entry - stop| in price units
    target_distance: float # |target - entry| in price units
    stop_pct: float        # fraction
    target_pct: float      # fraction
    risk_reward_ratio: float

    def to_dict(self) -> dict:
        return {
            "entry_price": self.entry_price,
            "side": self.side,
            "stop_price": round(self.stop_price, 8),
            "target_price": round(self.target_price, 8),
            "stop_pct": round(self.stop_pct * 100, 4),
            "target_pct": round(self.target_pct * 100, 4),
            "risk_reward_ratio": round(self.risk_reward_ratio, 2),
        }


@dataclass
class RiskReport:
    symbol: str
    interval: str
    market: str
    side: str
    entry_price: float
    atr: float
    atr_multiplier: float
    position_size: PositionSize
    stop_target: StopTarget
    max_loss: float    # worst-case loss in quote currency
    max_gain: float    # best-case gain in quote currency

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "market": self.market,
            "side": self.side,
            "entry_price": self.entry_price,
            "atr": round(self.atr, 8),
            "atr_multiplier": self.atr_multiplier,
            "position_size": self.position_size.to_dict(),
            "stop_target": self.stop_target.to_dict(),
            "max_loss": round(self.max_loss, 4),
            "max_gain": round(self.max_gain, 4),
        }
