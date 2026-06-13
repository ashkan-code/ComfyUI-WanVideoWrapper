"""Tests for regime detection: ADX, classifier, and models."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from regime.adx import compute_adx, compute_atr_ratio, _wilder_smooth
from regime.classifier import RegimeClassifier
from regime.models import BarRegime, Regime, RegimeResult


# ─── helpers ────────────────────────────────────────────────────────────────


def _df(closes: list[float], highs: list[float] | None = None, lows: list[float] | None = None) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame({
        "open_time": [i * 3_600_000 for i in range(n)],
        "open":   closes,
        "high":   highs or [c + 2.0 for c in closes],
        "low":    lows  or [c - 2.0 for c in closes],
        "close":  closes,
        "volume": [1000.0] * n,
    })


def _trending_up(n: int = 200) -> pd.DataFrame:
    closes = [100.0 + i * 0.5 for i in range(n)]
    return _df(closes, highs=[c + 3 for c in closes], lows=[c - 0.5 for c in closes])


def _trending_down(n: int = 200) -> pd.DataFrame:
    closes = [200.0 - i * 0.5 for i in range(n)]
    return _df(closes, highs=[c + 0.5 for c in closes], lows=[c - 3 for c in closes])


def _ranging(n: int = 200) -> pd.DataFrame:
    closes = [100.0 + math.sin(i / 3) * 2 for i in range(n)]
    return _df(closes)


def _sinusoidal(n: int = 200) -> pd.DataFrame:
    closes = [50.0 + 15.0 * math.sin(i / 8) for i in range(n)]
    return _df(closes)


# ─── Wilder smoothing ────────────────────────────────────────────────────────


class TestWilderSmooth:
    def test_output_length(self) -> None:
        vals = np.arange(1.0, 21.0)
        result = _wilder_smooth(vals, 5)
        assert len(result) == 20

    def test_leading_nan(self) -> None:
        vals = np.arange(1.0, 21.0)
        result = _wilder_smooth(vals, 5)
        assert all(np.isnan(result[:4]))

    def test_first_valid_is_sum(self) -> None:
        vals = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])
        result = _wilder_smooth(vals, 5)
        assert result[4] == pytest.approx(1 + 2 + 3 + 4 + 5)

    def test_too_short_all_nan(self) -> None:
        result = _wilder_smooth(np.array([1.0, 2.0]), period=5)
        assert all(np.isnan(result))


# ─── ADX ────────────────────────────────────────────────────────────────────


class TestComputeADX:
    def test_returns_expected_columns(self) -> None:
        df = compute_adx(_trending_up())
        assert set(df.columns) == {"adx", "di_plus", "di_minus", "atr"}

    def test_length_preserved(self) -> None:
        data = _trending_up(100)
        result = compute_adx(data, period=14)
        assert len(result) == 100

    def test_adx_range(self) -> None:
        result = compute_adx(_trending_up())
        valid = result["adx"].dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()  # properly bounded with average-seeded smoothing

    def test_di_range(self) -> None:
        result = compute_adx(_trending_up())
        assert (result["di_plus"].dropna() >= 0).all()
        assert (result["di_minus"].dropna() >= 0).all()

    def test_trending_up_diplus_gt_diminus(self) -> None:
        result = compute_adx(_trending_up())
        tail = result.dropna().tail(20)
        assert (tail["di_plus"] > tail["di_minus"]).all()

    def test_trending_down_diminus_gt_diplus(self) -> None:
        result = compute_adx(_trending_down())
        tail = result.dropna().tail(20)
        assert (tail["di_minus"] > tail["di_plus"]).all()

    def test_atr_positive(self) -> None:
        result = compute_adx(_sinusoidal())
        assert (result["atr"].dropna() > 0).all()


class TestATRRatio:
    def test_returns_series(self) -> None:
        ratio = compute_atr_ratio(_trending_up())
        assert isinstance(ratio, pd.Series)

    def test_stable_market_ratio_near_one(self) -> None:
        # Constant volatility → ratio should be near 1.0
        closes = [100.0 + math.sin(i / 5) for i in range(200)]
        df = _df(closes)
        ratio = compute_atr_ratio(df)
        tail = ratio.dropna().tail(20)
        assert ((tail > 0.5) & (tail < 2.0)).all()


# ─── Classifier ─────────────────────────────────────────────────────────────


class TestRegimeClassifier:
    def test_too_few_bars_raises(self) -> None:
        clf = RegimeClassifier()
        with pytest.raises(ValueError, match="bars"):
            clf.classify(_df([100.0] * 10))

    def test_returns_regime_result(self) -> None:
        clf = RegimeClassifier()
        result = clf.classify(_trending_up(200))
        assert isinstance(result, RegimeResult)

    def test_history_length_matches_df(self) -> None:
        clf = RegimeClassifier()
        n = 200
        result = clf.classify(_trending_up(n))
        assert len(result.history) == n

    def test_trending_up_detected(self) -> None:
        clf = RegimeClassifier(trend_threshold=20.0)
        result = clf.classify(_trending_up(200))
        # Most recent bars should be TRENDING_UP
        recent_regimes = [b.regime for b in result.history[-10:]]
        assert Regime.TRENDING_UP in recent_regimes

    def test_trending_down_detected(self) -> None:
        clf = RegimeClassifier(trend_threshold=20.0)
        result = clf.classify(_trending_down(200))
        recent_regimes = [b.regime for b in result.history[-10:]]
        assert Regime.TRENDING_DOWN in recent_regimes

    def test_ranging_detected(self) -> None:
        # Very low-amplitude oscillation → DM+/DM- small and alternating → low ADX → RANGING
        closes = [100.0 + math.sin(i / 2) * 0.3 for i in range(200)]
        highs  = [c + 0.4 for c in closes]
        lows   = [c - 0.4 for c in closes]
        df = _df(closes, highs=highs, lows=lows)
        clf = RegimeClassifier(range_threshold=30.0)
        result = clf.classify(df)
        assert Regime.RANGING in result.regime_distribution

    def test_distribution_sums_to_100(self) -> None:
        clf = RegimeClassifier()
        result = clf.classify(_sinusoidal(200))
        total = sum(v["pct"] for v in result.regime_distribution.values())
        assert total == pytest.approx(100.0, abs=0.2)

    def test_dominant_regime_is_most_common(self) -> None:
        clf = RegimeClassifier()
        result = clf.classify(_trending_up(200))
        max_count = max(v["count"] for v in result.regime_distribution.values())
        dom_count = result.regime_distribution[result.dominant_regime.value]["count"]
        assert dom_count == max_count

    def test_current_regime_is_last_bar(self) -> None:
        clf = RegimeClassifier()
        result = clf.classify(_trending_up(200))
        assert result.current_regime == result.history[-1].regime

    def test_to_dict_keys(self) -> None:
        clf = RegimeClassifier()
        result = clf.classify(_sinusoidal(200), symbol="btc_usdt", interval="1h")
        d = result.to_dict()
        assert d["symbol"] == "btc_usdt"
        assert "current_regime" in d
        assert "current_regime_description" in d
        assert "dominant_regime" in d
        assert "regime_distribution" in d
        assert "recent_history" in d


# ─── Regime model ────────────────────────────────────────────────────────────


class TestRegimeModel:
    def test_is_trending(self) -> None:
        assert Regime.TRENDING_UP.is_trending()
        assert Regime.TRENDING_DOWN.is_trending()
        assert not Regime.RANGING.is_trending()
        assert not Regime.VOLATILE.is_trending()

    def test_is_bullish(self) -> None:
        assert Regime.TRENDING_UP.is_bullish()
        assert not Regime.TRENDING_DOWN.is_bullish()

    def test_description_non_empty(self) -> None:
        for r in Regime:
            assert len(r.description()) > 0

    def test_bar_regime_to_dict(self) -> None:
        b = BarRegime(
            open_time=0, regime=Regime.TRENDING_UP,
            adx=30.5, di_plus=25.0, di_minus=10.0, atr_ratio=1.1,
        )
        d = b.to_dict()
        assert d["regime"] == "TRENDING_UP"
        assert d["adx"] == pytest.approx(30.5)
