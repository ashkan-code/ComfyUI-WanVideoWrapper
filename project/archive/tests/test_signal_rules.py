"""Tests for individual signal rules."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from signals.models import SignalType
from signals.rules import BBMeanRevertRule, EMACrossRule, MACDCrossRule, RSIRule, VolumeSpikeRule


def _df(closes: list[float], highs: list[float] | None = None, lows: list[float] | None = None, volumes: list[float] | None = None) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame({
        "open_time": list(range(n)),
        "open":   closes,
        "high":   highs   or [c + 0.5 for c in closes],
        "low":    lows    or [c - 0.5 for c in closes],
        "close":  closes,
        "volume": volumes or [1000.0] * n,
    })


class TestRSIRule:
    def test_buy_signal_on_oversold(self) -> None:
        # Strictly falling prices → RSI near 0 → BUY signal expected
        closes = [100.0 - i * 2 for i in range(60)]
        result = RSIRule(period=14, buy_level=30, sell_level=70).evaluate(_df(closes))
        buys = result[result == SignalType.BUY]
        assert len(buys) > 0

    def test_sell_signal_on_overbought(self) -> None:
        # Strictly rising prices → RSI near 100 → SELL signal expected
        closes = [50.0 + i * 2 for i in range(60)]
        result = RSIRule(period=14, buy_level=30, sell_level=70).evaluate(_df(closes))
        sells = result[result == SignalType.SELL]
        assert len(sells) > 0

    def test_returns_series_same_length(self) -> None:
        closes = [float(i) for i in range(1, 41)]
        result = RSIRule().evaluate(_df(closes))
        assert len(result) == 40

    def test_no_signal_in_middle_range(self) -> None:
        # Oscillating prices in normal RSI range
        import math
        closes = [50 + 5 * math.sin(i / 10) for i in range(80)]
        result = RSIRule(period=14, buy_level=20, sell_level=80).evaluate(_df(closes))
        # With tight thresholds, most bars should have no signal
        non_none = result.dropna()
        assert len(non_none) < len(result)


class TestEMACrossRule:
    def test_buy_on_golden_cross(self) -> None:
        # Prices jump → fast EMA crosses above slow EMA
        closes = [10.0] * 50 + [100.0] * 50
        result = EMACrossRule(fast=5, slow=20).evaluate(_df(closes))
        buys = result[result == SignalType.BUY]
        assert len(buys) >= 1

    def test_sell_on_death_cross(self) -> None:
        # Prices drop → fast EMA crosses below slow EMA
        closes = [100.0] * 50 + [10.0] * 50
        result = EMACrossRule(fast=5, slow=20).evaluate(_df(closes))
        sells = result[result == SignalType.SELL]
        assert len(sells) >= 1

    def test_returns_correct_length(self) -> None:
        closes = [float(i) for i in range(60)]
        assert len(EMACrossRule().evaluate(_df(closes))) == 60

    def test_no_cross_in_flat_series(self) -> None:
        closes = [50.0] * 60
        result = EMACrossRule(fast=5, slow=20).evaluate(_df(closes))
        assert result.dropna().empty


class TestMACDCrossRule:
    def test_buy_on_histogram_flip_positive(self) -> None:
        import math
        # Sine wave → MACD will cross positive during upswing
        closes = [50 + 20 * math.sin(i / 8) for i in range(100)]
        result = MACDCrossRule().evaluate(_df(closes))
        buys = result[result == SignalType.BUY]
        assert len(buys) > 0

    def test_returns_correct_length(self) -> None:
        closes = [float(50 + i % 10) for i in range(80)]
        assert len(MACDCrossRule().evaluate(_df(closes))) == 80

    def test_signals_exist_in_trending_market(self) -> None:
        import math
        closes = [50 + 15 * math.sin(i / 6) for i in range(120)]
        result = MACDCrossRule().evaluate(_df(closes))
        assert result.dropna().shape[0] > 0


class TestBBMeanRevertRule:
    def test_buy_below_lower_band(self) -> None:
        # Price drops far below average → buy signal
        closes = [50.0] * 25 + [20.0] * 5
        result = BBMeanRevertRule(period=20, std=2.0).evaluate(_df(closes))
        buys = result[result == SignalType.BUY]
        assert len(buys) > 0

    def test_sell_above_upper_band(self) -> None:
        closes = [50.0] * 25 + [80.0] * 5
        result = BBMeanRevertRule(period=20, std=2.0).evaluate(_df(closes))
        sells = result[result == SignalType.SELL]
        assert len(sells) > 0

    def test_no_signal_in_normal_range(self) -> None:
        # Constant price → no breakout → no signal
        closes = [50.0] * 40
        result = BBMeanRevertRule().evaluate(_df(closes))
        assert result.dropna().empty

    def test_correct_length(self) -> None:
        closes = [float(i % 10 + 45) for i in range(50)]
        assert len(BBMeanRevertRule().evaluate(_df(closes))) == 50


class TestVolumeSpikeRule:
    def test_buy_on_volume_spike_up(self) -> None:
        closes  = [10.0] * 30 + [11.0]  # price goes up on last bar
        volumes = [100.0] * 30 + [500.0]  # huge volume spike
        result = VolumeSpikeRule(period=20, multiplier=2.0).evaluate(
            _df(closes, volumes=volumes)
        )
        assert result.iloc[-1] == SignalType.BUY

    def test_sell_on_volume_spike_down(self) -> None:
        closes  = [11.0] * 30 + [10.0]   # price drops on last bar
        volumes = [100.0] * 30 + [500.0]
        result = VolumeSpikeRule(period=20, multiplier=2.0).evaluate(
            _df(closes, volumes=volumes)
        )
        assert result.iloc[-1] == SignalType.SELL

    def test_no_signal_without_spike(self) -> None:
        closes  = [float(10 + i % 2) for i in range(40)]
        volumes = [100.0] * 40   # flat volume — no spike
        result = VolumeSpikeRule(period=10, multiplier=3.0).evaluate(
            _df(closes, volumes=volumes)
        )
        # No bar exceeds 3× average (all bars are equal)
        assert result.dropna().empty
