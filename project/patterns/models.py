"""Dataclasses for candlestick pattern detection results."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PatternOccurrence:
    open_time: int
    pattern: str
    close: float
    signal_bias: str   # "bullish" | "bearish" | "neutral"

    def to_dict(self) -> dict:
        return {
            "open_time": self.open_time,
            "pattern": self.pattern,
            "close": self.close,
            "signal_bias": self.signal_bias,
        }


@dataclass
class PatternResult:
    symbol: str
    interval: str
    market: str
    lookback_bars: int
    total_bars: int
    patterns_found: dict[str, int] = field(default_factory=dict)
    recent_occurrences: list[PatternOccurrence] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "market": self.market,
            "lookback_bars": self.lookback_bars,
            "total_bars": self.total_bars,
            "patterns_found": self.patterns_found,
            "recent_occurrences": [o.to_dict() for o in self.recent_occurrences],
        }
