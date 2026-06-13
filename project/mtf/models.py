"""Dataclasses for multi-timeframe analysis results."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TimeframeSnapshot:
    timeframe: str
    regime: str
    adx: float
    di_plus: float
    di_minus: float
    atr_ratio: float
    last_signal: str | None    # "BUY", "SELL", or None
    signal_count: int

    def to_dict(self) -> dict:
        return {
            "timeframe": self.timeframe,
            "regime": self.regime,
            "adx": round(self.adx, 2),
            "di_plus": round(self.di_plus, 2),
            "di_minus": round(self.di_minus, 2),
            "atr_ratio": round(self.atr_ratio, 3),
            "last_signal": self.last_signal,
            "signal_count": self.signal_count,
        }


@dataclass
class MTFResult:
    symbol: str
    market: str
    strategy: str
    timeframes: list[TimeframeSnapshot] = field(default_factory=list)
    confluence_score: float = 0.0     # 0–100; higher = stronger alignment
    trend_alignment: str = "MIXED"
    recommendation: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "market": self.market,
            "strategy": self.strategy,
            "timeframes": [s.to_dict() for s in self.timeframes],
            "confluence_score": self.confluence_score,
            "trend_alignment": self.trend_alignment,
            "recommendation": self.recommendation,
        }
