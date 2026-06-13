"""Models for market regime detection."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Regime(str, Enum):
    TRENDING_UP   = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING       = "RANGING"
    VOLATILE      = "VOLATILE"
    UNKNOWN       = "UNKNOWN"

    def is_trending(self) -> bool:
        return self in (Regime.TRENDING_UP, Regime.TRENDING_DOWN)

    def is_bullish(self) -> bool:
        return self == Regime.TRENDING_UP

    def description(self) -> str:
        return {
            Regime.TRENDING_UP:   "Strong uptrend — momentum strategies favoured",
            Regime.TRENDING_DOWN: "Strong downtrend — avoid longs, wait for reversal",
            Regime.RANGING:       "Sideways market — mean-reversion strategies favoured",
            Regime.VOLATILE:      "Elevated volatility — reduce position size or stand aside",
            Regime.UNKNOWN:       "No clear regime — insufficient data or transitional",
        }[self]


@dataclass
class BarRegime:
    open_time: int
    regime: Regime
    adx: float
    di_plus: float
    di_minus: float
    atr_ratio: float

    def to_dict(self) -> dict:
        return {
            "open_time": self.open_time,
            "regime": self.regime.value,
            "adx": round(self.adx, 2),
            "di_plus": round(self.di_plus, 2),
            "di_minus": round(self.di_minus, 2),
            "atr_ratio": round(self.atr_ratio, 3),
        }


@dataclass
class RegimeResult:
    symbol: str
    interval: str
    market: str
    current_regime: Regime
    current_adx: float
    current_di_plus: float
    current_di_minus: float
    current_atr_ratio: float
    dominant_regime: Regime
    regime_distribution: dict[str, dict]   # regime → {count, pct}
    history: list[BarRegime] = field(default_factory=list)

    def to_dict(self, history_bars: int = 20) -> dict:
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "market": self.market,
            "current_regime": self.current_regime.value,
            "current_regime_description": self.current_regime.description(),
            "current_adx": round(self.current_adx, 2),
            "current_di_plus": round(self.current_di_plus, 2),
            "current_di_minus": round(self.current_di_minus, 2),
            "current_atr_ratio": round(self.current_atr_ratio, 3),
            "dominant_regime": self.dominant_regime.value,
            "regime_distribution": self.regime_distribution,
            "recent_history": [b.to_dict() for b in self.history[-history_bars:]],
        }
