"""Tests for volume indicators: OBV, VWAP.
Also covers registry compute() and list_indicators().
"""

from __future__ import annotations

import pandas as pd
import pytest

from indicators.registry import compute, list_indicators
from indicators.volume import obv, vwap


def _series(*values: float) -> pd.Series:
    return pd.Series(list(values), dtype=float)


class TestOBV:
    def test_increases_on_up_close(self) -> None:
        # Close goes up every bar → OBV should increase
        close = _series(10.0, 11.0, 12.0, 13.0, 14.0)
        volume = _series(100.0, 100.0, 100.0, 100.0, 100.0)
        result = obv(close, volume)
        assert (result.diff().iloc[1:] > 0).all()

    def test_decreases_on_down_close(self) -> None:
        # Close falls every bar → OBV decreases
        close = _series(14.0, 13.0, 12.0, 11.0, 10.0)
        volume = _series(100.0, 100.0, 100.0, 100.0, 100.0)
        result = obv(close, volume)
        assert (result.diff().iloc[1:] < 0).all()

    def test_flat_close_unchanged_obv(self) -> None:
        close = _series(10.0, 10.0, 10.0, 10.0)
        volume = _series(100.0, 100.0, 100.0, 100.0)
        result = obv(close, volume)
        # All diffs should be 0 after the first bar
        assert (result.diff().iloc[1:] == 0).all()

    def test_returns_series(self) -> None:
        c = _series(1.0, 2.0, 3.0)
        v = _series(10.0, 20.0, 30.0)
        assert isinstance(obv(c, v), pd.Series)

    def test_length_preserved(self) -> None:
        c = _series(*range(1, 21))
        v = _series(*([100.0] * 20))
        assert len(obv(c, v)) == 20

    def test_known_values(self) -> None:
        # OBV: start=0, close[1]>close[0]→+vol, close[2]<close[1]→-vol
        close = _series(10.0, 11.0, 9.0)
        volume = _series(100.0, 200.0, 150.0)
        result = obv(close, volume)
        assert result.iloc[0] == 0.0
        assert result.iloc[1] == 200.0
        assert result.iloc[2] == 50.0


class TestVWAP:
    def test_returns_series(self) -> None:
        n = 10
        h = _series(*([11.0] * n))
        l = _series(*([9.0] * n))
        c = _series(*([10.0] * n))
        v = _series(*([1000.0] * n))
        assert isinstance(vwap(h, l, c, v), pd.Series)

    def test_constant_price_equals_typical_price(self) -> None:
        # If H=L=C=10, typical price = 10, VWAP should be 10
        n = 20
        h = _series(*([12.0] * n))
        l = _series(*([8.0] * n))
        c = _series(*([10.0] * n))
        v = _series(*([500.0] * n))
        result = vwap(h, l, c, v)
        # typical_price = (12+8+10)/3 = 10
        assert (result - 10.0).abs().max() < 1e-10

    def test_length_preserved(self) -> None:
        n = 30
        h = _series(*([10.5] * n))
        l = _series(*([9.5] * n))
        c = _series(*([10.0] * n))
        v = _series(*([100.0] * n))
        assert len(vwap(h, l, c, v)) == n


class TestRegistry:
    def test_list_indicators_returns_all(self) -> None:
        names = list_indicators()
        expected = {"sma", "ema", "dema", "wma", "rsi", "macd", "stoch", "bb", "atr", "obv", "vwap"}
        assert expected.issubset(set(names))

    def test_compute_unknown_raises(self) -> None:
        df = pd.DataFrame({"close": [1.0, 2.0, 3.0]})
        with pytest.raises(ValueError, match="Unknown indicator"):
            compute("unknown_indicator", df)

    def test_compute_sma_default(self) -> None:
        df = pd.DataFrame({"close": [float(i) for i in range(1, 31)]})
        result = compute("sma", df)
        assert "sma" in result
        assert isinstance(result["sma"], pd.Series)

    def test_compute_sma_with_param(self) -> None:
        df = pd.DataFrame({"close": [float(i) for i in range(1, 31)]})
        result = compute("sma:5", df)
        assert result["sma"].isna().sum() == 4

    def test_compute_rsi_spec(self) -> None:
        df = pd.DataFrame({"close": [float(i) for i in range(1, 50)]})
        result = compute("rsi:7", df)
        assert "rsi" in result

    def test_compute_macd_spec(self) -> None:
        df = pd.DataFrame({"close": [50.0 + (i % 10) for i in range(60)]})
        result = compute("macd:8:21:5", df)
        assert "macd" in result
        assert "macd_signal" in result
        assert "macd_hist" in result

    def test_compute_bb_spec(self) -> None:
        df = pd.DataFrame({"close": [50.0 + (i % 5) for i in range(40)]})
        result = compute("bb:10:2", df)
        assert {"bb_upper", "bb_middle", "bb_lower"}.issubset(result)

    def test_compute_obv(self) -> None:
        df = pd.DataFrame({
            "close": [10.0, 11.0, 12.0],
            "volume": [100.0, 200.0, 300.0],
        })
        result = compute("obv", df)
        assert "obv" in result

    def test_compute_vwap(self) -> None:
        df = pd.DataFrame({
            "high": [11.0, 12.0, 13.0],
            "low": [9.0, 10.0, 11.0],
            "close": [10.0, 11.0, 12.0],
            "volume": [100.0, 200.0, 300.0],
        })
        result = compute("vwap", df)
        assert "vwap" in result

    def test_compute_atr_spec(self) -> None:
        df = pd.DataFrame({
            "high": [11.0 + i for i in range(30)],
            "low": [9.0 + i for i in range(30)],
            "close": [10.0 + i for i in range(30)],
        })
        result = compute("atr:7", df)
        assert "atr" in result
