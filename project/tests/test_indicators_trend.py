"""Tests for trend indicators: SMA, EMA, DEMA, WMA."""

from __future__ import annotations

import pandas as pd
import pytest

from indicators.trend import dema, ema, sma, wma


def _series(*values: float) -> pd.Series:
    return pd.Series(list(values), dtype=float)


class TestSMA:
    def test_basic_values(self) -> None:
        s = _series(1, 2, 3, 4, 5)
        result = sma(s, period=3)
        assert result.isna().sum() == 2        # first two NaN
        assert result.iloc[2] == pytest.approx(2.0)
        assert result.iloc[3] == pytest.approx(3.0)
        assert result.iloc[4] == pytest.approx(4.0)

    def test_nan_count_equals_period_minus_one(self) -> None:
        s = _series(*range(1, 11))
        assert sma(s, period=5).isna().sum() == 4

    def test_period_1_returns_same(self) -> None:
        s = _series(10.0, 20.0, 30.0)
        result = sma(s, period=1)
        assert result.tolist() == pytest.approx([10.0, 20.0, 30.0])

    def test_length_preserved(self) -> None:
        s = _series(*range(50))
        assert len(sma(s, period=10)) == 50

    def test_constant_series(self) -> None:
        s = _series(*([5.0] * 10))
        result = sma(s, period=3).dropna()
        assert all(v == pytest.approx(5.0) for v in result)


class TestEMA:
    def test_no_leading_nan(self) -> None:
        s = _series(1, 2, 3, 4, 5)
        result = ema(s, period=3)
        # EMA with adjust=False starts from the first value — no NaN
        assert result.isna().sum() == 0

    def test_ema_converges_to_constant(self) -> None:
        s = _series(*([100.0] * 50))
        result = ema(s, period=10)
        assert result.iloc[-1] == pytest.approx(100.0, rel=1e-6)

    def test_ema_reacts_faster_than_sma(self) -> None:
        # One bar after a price jump, EMA has already moved up more than SMA
        # because SMA still has 4 old bars dragging it down.
        values = [10.0] * 20 + [100.0] * 20
        s = _series(*values)
        e = ema(s, period=5)
        m = sma(s, period=5)
        # Index 21 = 2nd bar of the new 100 level
        # EMA ≈ 60, SMA = (10+10+10+100+100)/5 = 46
        assert e.iloc[21] > m.iloc[21]

    def test_length_preserved(self) -> None:
        s = _series(*range(30))
        assert len(ema(s, period=10)) == 30


class TestDEMA:
    def test_length_preserved(self) -> None:
        s = _series(*range(1, 51))
        assert len(dema(s, period=10)) == 50

    def test_dema_reacts_faster_than_ema(self) -> None:
        values = [10.0] * 30 + [100.0] * 30
        s = _series(*values)
        d = dema(s, period=5)
        e = ema(s, period=5)
        # DEMA should react faster — higher value shortly after jump
        assert d.iloc[35] >= e.iloc[35]

    def test_constant_series(self) -> None:
        s = _series(*([7.0] * 40))
        result = dema(s, period=5)
        assert result.iloc[-1] == pytest.approx(7.0, rel=1e-5)


class TestWMA:
    def test_known_values(self) -> None:
        # WMA period=2: weights [1, 2], sum=3
        # WMA[1] = (1*1 + 2*2) / 3 = 5/3
        # WMA[2] = (1*2 + 2*3) / 3 = 8/3
        s = _series(1.0, 2.0, 3.0)
        result = wma(s, period=2)
        assert result.isna().sum() == 1
        assert result.iloc[1] == pytest.approx(5 / 3)
        assert result.iloc[2] == pytest.approx(8 / 3)

    def test_nan_count(self) -> None:
        s = _series(*range(1, 11))
        assert wma(s, period=4).isna().sum() == 3

    def test_length_preserved(self) -> None:
        s = _series(*range(20))
        assert len(wma(s, period=5)) == 20

    def test_constant_series(self) -> None:
        s = _series(*([3.0] * 10))
        result = wma(s, period=3).dropna()
        assert all(v == pytest.approx(3.0) for v in result)
