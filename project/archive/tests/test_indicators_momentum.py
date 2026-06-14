"""Tests for momentum indicators: RSI, MACD, Stochastic."""

from __future__ import annotations

import pandas as pd
import pytest

from indicators.momentum import macd, rsi, stochastic


def _series(*values: float) -> pd.Series:
    return pd.Series(list(values), dtype=float)


class TestRSI:
    def test_range_0_to_100(self) -> None:
        import random
        random.seed(42)
        prices = [100.0]
        for _ in range(99):
            prices.append(prices[-1] * (1 + random.uniform(-0.02, 0.02)))
        result = rsi(_series(*prices), period=14).dropna()
        assert (result >= 0.0).all()
        assert (result <= 100.0).all()

    def test_all_up_gives_high_rsi(self) -> None:
        # Strictly increasing prices → RSI near 100
        prices = [float(i) for i in range(1, 60)]
        result = rsi(_series(*prices), period=14)
        assert result.iloc[-1] > 90.0

    def test_all_down_gives_low_rsi(self) -> None:
        # Strictly decreasing prices → RSI near 0
        prices = [float(60 - i) for i in range(60)]
        result = rsi(_series(*prices), period=14)
        assert result.iloc[-1] < 10.0

    def test_length_preserved(self) -> None:
        prices = [float(i) for i in range(50)]
        result = rsi(_series(*prices), period=14)
        assert len(result) == 50

    def test_constant_series(self) -> None:
        # No gains, no losses → RSI is NaN (0/0 edge case)
        s = _series(*([50.0] * 30))
        result = rsi(s, period=14)
        # After first diff, all deltas are 0 → avg_loss = 0 → we get NaN
        assert result.dropna().empty or (result.dropna() == 100.0).all()


class TestMACD:
    def _prices(self, n: int = 100) -> pd.Series:
        import math
        return _series(*[50 + 10 * math.sin(i / 5.0) for i in range(n)])

    def test_returns_three_columns(self) -> None:
        result = macd(self._prices())
        assert set(result.columns) == {"macd", "macd_signal", "macd_hist"}

    def test_histogram_equals_macd_minus_signal(self) -> None:
        result = macd(self._prices())
        diff = (result["macd"] - result["macd_signal"] - result["macd_hist"]).abs()
        assert diff.max() < 1e-10

    def test_length_preserved(self) -> None:
        result = macd(self._prices(80))
        assert len(result) == 80

    def test_custom_params(self) -> None:
        p = self._prices(100)
        result = macd(p, fast=8, slow=21, signal=5)
        assert set(result.columns) == {"macd", "macd_signal", "macd_hist"}

    def test_no_nan_at_end(self) -> None:
        # With 100 bars and standard (12,26,9), no NaN at bar 100
        result = macd(self._prices(100))
        assert not result.iloc[-1].isna().any()


class TestStochastic:
    def _hlc(self, n: int = 50) -> tuple[pd.Series, pd.Series, pd.Series]:
        high = _series(*[10.0 + i * 0.1 for i in range(n)])
        low = _series(*[9.0 + i * 0.1 for i in range(n)])
        close = _series(*[9.5 + i * 0.1 for i in range(n)])
        return high, low, close

    def test_returns_two_columns(self) -> None:
        h, l, c = self._hlc()
        result = stochastic(h, l, c)
        assert set(result.columns) == {"stoch_k", "stoch_d"}

    def test_k_range_0_to_100(self) -> None:
        h, l, c = self._hlc()
        k = stochastic(h, l, c)["stoch_k"].dropna()
        assert (k >= 0.0).all()
        assert (k <= 100.0).all()

    def test_uptrend_gives_high_k(self) -> None:
        # close is right at the high → K should be near 100
        n = 40
        high  = _series(*[10.0 + i for i in range(n)])
        low   = _series(*[9.0  + i for i in range(n)])
        close = _series(*[9.99 + i for i in range(n)])   # close ≈ high
        k = stochastic(high, low, close, k_period=5)["stoch_k"].dropna()
        assert k.iloc[-1] > 90.0

    def test_length_preserved(self) -> None:
        h, l, c = self._hlc(60)
        assert len(stochastic(h, l, c)) == 60

    def test_d_is_smoothed_k(self) -> None:
        import math
        n = 50
        # Oscillating series so K varies and D lags
        high  = _series(*[10.0 + abs(math.sin(i / 3.0)) * 2 for i in range(n)])
        low   = _series(*[9.0  - abs(math.sin(i / 3.0))      for i in range(n)])
        close = _series(*[9.5  + math.sin(i / 3.0) * 1.5     for i in range(n)])
        result = stochastic(high, low, close, k_period=5, d_period=3)
        # Use only the rows where both K and D are valid
        both = result.dropna()
        assert not (both["stoch_k"].values == both["stoch_d"].values).all()
