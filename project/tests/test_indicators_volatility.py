"""Tests for volatility indicators: Bollinger Bands, ATR."""

from __future__ import annotations

import pandas as pd
import pytest

from indicators.volatility import atr, bollinger_bands


def _series(*values: float) -> pd.Series:
    return pd.Series(list(values), dtype=float)


class TestBollingerBands:
    def _close(self, n: int = 50) -> pd.Series:
        return _series(*[50.0 + (i % 10) for i in range(n)])

    def test_returns_three_columns(self) -> None:
        result = bollinger_bands(self._close())
        assert set(result.columns) == {"bb_upper", "bb_middle", "bb_lower"}

    def test_upper_above_lower(self) -> None:
        result = bollinger_bands(self._close()).dropna()
        assert (result["bb_upper"] > result["bb_lower"]).all()

    def test_middle_is_sma(self) -> None:
        close = self._close(60)
        result = bollinger_bands(close, period=20)
        sma = close.rolling(window=20, min_periods=20).mean()
        diff = (result["bb_middle"] - sma).dropna().abs()
        assert diff.max() < 1e-10

    def test_nan_count(self) -> None:
        close = self._close(50)
        result = bollinger_bands(close, period=20)
        assert result["bb_middle"].isna().sum() == 19

    def test_length_preserved(self) -> None:
        close = self._close(40)
        assert len(bollinger_bands(close, period=10)) == 40

    def test_constant_series_zero_width(self) -> None:
        # Constant price → std=0 → upper == middle == lower
        close = _series(*([10.0] * 30))
        result = bollinger_bands(close, period=10).dropna()
        assert (result["bb_upper"] == result["bb_middle"]).all()
        assert (result["bb_lower"] == result["bb_middle"]).all()

    def test_custom_std(self) -> None:
        close = self._close(50)
        r1 = bollinger_bands(close, period=10, std=1.0).dropna()
        r2 = bollinger_bands(close, period=10, std=3.0).dropna()
        # Wider std → wider bands
        width1 = (r1["bb_upper"] - r1["bb_lower"]).mean()
        width2 = (r2["bb_upper"] - r2["bb_lower"]).mean()
        assert width2 == pytest.approx(width1 * 3.0, rel=1e-6)


class TestATR:
    def _hlc(self, n: int = 50) -> tuple[pd.Series, pd.Series, pd.Series]:
        high = _series(*[10.5 + (i % 5) * 0.1 for i in range(n)])
        low = _series(*[9.5 + (i % 5) * 0.1 for i in range(n)])
        close = _series(*[10.0 + (i % 5) * 0.1 for i in range(n)])
        return high, low, close

    def test_non_negative(self) -> None:
        h, l, c = self._hlc()
        result = atr(h, l, c, period=14).dropna()
        assert (result >= 0.0).all()

    def test_length_preserved(self) -> None:
        h, l, c = self._hlc(60)
        assert len(atr(h, l, c, period=14)) == 60

    def test_high_volatility_gives_larger_atr(self) -> None:
        # Series 1: small range bars
        n = 50
        h1 = _series(*[10.1] * n)
        l1 = _series(*[9.9] * n)
        c1 = _series(*[10.0] * n)

        # Series 2: large range bars
        h2 = _series(*[12.0] * n)
        l2 = _series(*[8.0] * n)
        c2 = _series(*[10.0] * n)

        atr1 = atr(h1, l1, c1, period=14).iloc[-1]
        atr2 = atr(h2, l2, c2, period=14).iloc[-1]
        assert atr2 > atr1

    def test_includes_gap(self) -> None:
        # A gap between sessions inflates true range beyond high-low
        high = _series(*([10.5] * 20))
        low = _series(*([9.5] * 20))
        # Previous close was 9.5, today opens at 12 → gap contributes to TR
        high.iloc[-1] = 12.5
        low.iloc[-1] = 12.0
        close = _series(*([10.0] * 19 + [12.2]))
        result = atr(high, low, close, period=5)
        # ATR should be elevated at the end due to the gap
        assert result.iloc[-1] > result.iloc[-3]
