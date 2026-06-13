"""Built-in signal rules.

Each Rule subclass implements evaluate(df) → pd.Series[SignalType | None].
The series has the same index as *df*; None means no signal for that bar.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from signals.models import SignalType


class Rule(ABC):
    """Abstract base for all signal rules."""

    @abstractmethod
    def evaluate(self, df: pd.DataFrame) -> pd.Series:
        """Return a Series aligned to df.index with SignalType or None per bar."""
        ...

    def _empty(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series([None] * len(df), index=df.index, dtype=object)


# ── RSI Reversal ──────────────────────────────────────────────────────────────

class RSIRule(Rule):
    """BUY when RSI drops below *buy_level*; SELL when it rises above *sell_level*."""

    def __init__(
        self,
        period: int = 14,
        buy_level: float = 30.0,
        sell_level: float = 70.0,
    ) -> None:
        self.period = period
        self.buy_level = buy_level
        self.sell_level = sell_level

    def evaluate(self, df: pd.DataFrame) -> pd.Series:
        from indicators.momentum import rsi
        r = rsi(df["close"], self.period)
        result = self._empty(df)
        result[r < self.buy_level] = SignalType.BUY
        result[r > self.sell_level] = SignalType.SELL
        return result


# ── EMA Cross ────────────────────────────────────────────────────────────────

class EMACrossRule(Rule):
    """BUY on golden cross (fast EMA crosses above slow); SELL on death cross."""

    def __init__(self, fast: int = 9, slow: int = 21) -> None:
        self.fast = fast
        self.slow = slow

    def evaluate(self, df: pd.DataFrame) -> pd.Series:
        from indicators.trend import ema
        fast = ema(df["close"], self.fast)
        slow = ema(df["close"], self.slow)
        prev_fast = fast.shift(1)
        prev_slow = slow.shift(1)
        result = self._empty(df)
        # Cross up: fast was below/equal slow, now above
        result[(fast > slow) & (prev_fast <= prev_slow)] = SignalType.BUY
        # Cross down: fast was above/equal slow, now below
        result[(fast < slow) & (prev_fast >= prev_slow)] = SignalType.SELL
        return result


# ── MACD Cross ───────────────────────────────────────────────────────────────

class MACDCrossRule(Rule):
    """BUY when MACD histogram flips positive; SELL when it flips negative."""

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
        self.fast = fast
        self.slow = slow
        self.signal = signal

    def evaluate(self, df: pd.DataFrame) -> pd.Series:
        from indicators.momentum import macd
        m = macd(df["close"], self.fast, self.slow, self.signal)
        hist = m["macd_hist"]
        prev = hist.shift(1)
        result = self._empty(df)
        result[(hist > 0) & (prev <= 0)] = SignalType.BUY
        result[(hist < 0) & (prev >= 0)] = SignalType.SELL
        return result


# ── Bollinger Band Mean Reversion ─────────────────────────────────────────────

class BBMeanRevertRule(Rule):
    """BUY when close falls below lower band; SELL when close rises above upper band."""

    def __init__(self, period: int = 20, std: float = 2.0) -> None:
        self.period = period
        self.std = std

    def evaluate(self, df: pd.DataFrame) -> pd.Series:
        from indicators.volatility import bollinger_bands
        bb = bollinger_bands(df["close"], self.period, self.std)
        result = self._empty(df)
        result[df["close"] < bb["bb_lower"]] = SignalType.BUY
        result[df["close"] > bb["bb_upper"]] = SignalType.SELL
        return result


# ── Volume Spike ─────────────────────────────────────────────────────────────

class VolumeSpikeRule(Rule):
    """Confirms direction when volume exceeds *multiplier* × rolling average."""

    def __init__(self, period: int = 20, multiplier: float = 2.0) -> None:
        self.period = period
        self.multiplier = multiplier

    def evaluate(self, df: pd.DataFrame) -> pd.Series:
        avg_vol = df["volume"].rolling(window=self.period, min_periods=1).mean()
        spike = df["volume"] > (self.multiplier * avg_vol)
        price_up = df["close"] > df["close"].shift(1)
        result = self._empty(df)
        result[spike & price_up] = SignalType.BUY
        result[spike & ~price_up] = SignalType.SELL
        return result
