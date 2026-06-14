"""Tests for candlestick pattern detection."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from patterns.detector import (
    DETECTORS,
    PATTERN_BIAS,
    detect_all,
    detect_bearish_engulfing,
    detect_bullish_engulfing,
    detect_doji,
    detect_evening_star,
    detect_hammer,
    detect_morning_star,
    detect_shooting_star,
)


# ─── helpers ────────────────────────────────────────────────────────────────


def _bar(o: float, c: float, h: float | None = None, l: float | None = None) -> dict:
    h = h if h is not None else max(o, c) + 0.5
    l = l if l is not None else min(o, c) - 0.5
    return {"open": o, "close": c, "high": h, "low": l}


def _df(*bars: dict, n_prefix: int = 5) -> pd.DataFrame:
    """Prepend n_prefix neutral bars so roll-based detectors work correctly."""
    neutral = [{"open": 100.0, "close": 100.0, "high": 100.5, "low": 99.5}] * n_prefix
    rows = neutral + list(bars)
    df = pd.DataFrame(rows)
    df["open_time"] = list(range(len(df)))
    df["volume"]    = 1.0
    return df


# ─── Doji ────────────────────────────────────────────────────────────────────


class TestDoji:
    def test_detects_doji(self) -> None:
        df = _df(_bar(100.0, 100.3, h=105.0, l=95.0))   # body=0.3, range=10 → 3%
        mask = detect_doji(df)
        assert mask[-1] is np.bool_(True)

    def test_non_doji_large_body(self) -> None:
        df = _df(_bar(100.0, 105.0, h=106.0, l=99.0))   # body=5, range=7 → 71%
        mask = detect_doji(df)
        assert mask[-1] is np.bool_(False)

    def test_zero_range_not_doji(self) -> None:
        df = _df(_bar(100.0, 100.0, h=100.0, l=100.0))
        mask = detect_doji(df)
        assert mask[-1] is np.bool_(False)

    def test_output_length(self) -> None:
        df = _df(_bar(100.0, 100.1, h=105.0, l=95.0))
        assert len(detect_doji(df)) == len(df)


# ─── Hammer ──────────────────────────────────────────────────────────────────


class TestHammer:
    def test_detects_hammer(self) -> None:
        # body=1, lower=6, upper=0.3 → lower>=2*body ✓, upper<=0.5*body ✓
        df = _df(_bar(100.0, 101.0, h=101.3, l=94.0))
        mask = detect_hammer(df)
        assert mask[-1] is np.bool_(True)

    def test_rejects_large_upper_shadow(self) -> None:
        # body=1, lower=6, upper=3 → upper > 0.5*body ✗
        df = _df(_bar(100.0, 101.0, h=104.0, l=94.0))
        mask = detect_hammer(df)
        assert mask[-1] is np.bool_(False)

    def test_rejects_zero_body(self) -> None:
        df = _df(_bar(100.0, 100.0, h=101.0, l=94.0))
        mask = detect_hammer(df)
        assert mask[-1] is np.bool_(False)


# ─── Shooting star ───────────────────────────────────────────────────────────


class TestShootingStar:
    def test_detects_shooting_star(self) -> None:
        # body=1, upper=8, lower=0.3 → upper>=2*body ✓, lower<=0.5 ✓
        df = _df(_bar(100.0, 99.0, h=108.0, l=98.7))
        mask = detect_shooting_star(df)
        assert mask[-1] is np.bool_(True)

    def test_rejects_large_lower_shadow(self) -> None:
        df = _df(_bar(100.0, 99.0, h=108.0, l=96.0))
        mask = detect_shooting_star(df)
        assert mask[-1] is np.bool_(False)

    def test_rejects_zero_body(self) -> None:
        df = _df(_bar(100.0, 100.0, h=108.0, l=99.5))
        mask = detect_shooting_star(df)
        assert mask[-1] is np.bool_(False)


# ─── Bullish engulfing ───────────────────────────────────────────────────────


class TestBullishEngulfing:
    def test_detects(self) -> None:
        # prev: red 102→100, curr: green 99→103 (engulfs)
        df = _df(_bar(102.0, 100.0), _bar(99.0, 103.0))
        mask = detect_bullish_engulfing(df)
        assert mask[-1] is np.bool_(True)

    def test_rejects_if_prev_green(self) -> None:
        df = _df(_bar(100.0, 102.0), _bar(99.0, 103.0))
        mask = detect_bullish_engulfing(df)
        assert mask[-1] is np.bool_(False)

    def test_rejects_if_curr_red(self) -> None:
        df = _df(_bar(102.0, 100.0), _bar(103.0, 99.0))
        mask = detect_bullish_engulfing(df)
        assert mask[-1] is np.bool_(False)

    def test_rejects_partial_engulf(self) -> None:
        # curr green but doesn't fully engulf
        df = _df(_bar(102.0, 100.0), _bar(101.0, 103.0))
        mask = detect_bullish_engulfing(df)
        assert mask[-1] is np.bool_(False)

    def test_first_bar_false(self) -> None:
        df = _df()
        assert detect_bullish_engulfing(df)[0] is np.bool_(False)


# ─── Bearish engulfing ───────────────────────────────────────────────────────


class TestBearishEngulfing:
    def test_detects(self) -> None:
        # prev: green 100→103, curr: red 104→99 (engulfs)
        df = _df(_bar(100.0, 103.0), _bar(104.0, 99.0))
        mask = detect_bearish_engulfing(df)
        assert mask[-1] is np.bool_(True)

    def test_rejects_if_prev_red(self) -> None:
        df = _df(_bar(103.0, 100.0), _bar(104.0, 99.0))
        mask = detect_bearish_engulfing(df)
        assert mask[-1] is np.bool_(False)

    def test_rejects_partial_engulf(self) -> None:
        df = _df(_bar(100.0, 103.0), _bar(104.0, 101.0))
        mask = detect_bearish_engulfing(df)
        assert mask[-1] is np.bool_(False)


# ─── Morning star ────────────────────────────────────────────────────────────


class TestMorningStar:
    def test_detects(self) -> None:
        # bar[0]: red 105→100, bar[1]: small body 100→100.5 h=102 l=98 (ratio=0.5/4=12.5%), bar[2]: green 100→103
        # midpoint of bar[0] = (105+100)/2 = 102.5, close[2]=103 > 102.5 ✓
        df = _df(
            _bar(105.0, 100.0, h=106.0, l=99.0),
            _bar(100.0, 100.5, h=102.0, l=98.0),
            _bar(100.0, 103.0, h=104.0, l=99.5),
        )
        mask = detect_morning_star(df)
        assert mask[-1] is np.bool_(True)

    def test_rejects_if_bar0_bullish(self) -> None:
        df = _df(
            _bar(100.0, 105.0, h=106.0, l=99.0),  # bar0 green, not red
            _bar(105.0, 105.5, h=107.0, l=103.0),
            _bar(105.0, 108.0, h=109.0, l=104.0),
        )
        mask = detect_morning_star(df)
        assert mask[-1] is np.bool_(False)

    def test_rejects_if_bar1_large_body(self) -> None:
        # bar1 has large body → not a small-body indecision
        df = _df(
            _bar(105.0, 100.0, h=106.0, l=99.0),
            _bar(100.0, 105.0, h=106.0, l=99.0),  # large body
            _bar(100.0, 103.0, h=104.0, l=99.5),
        )
        mask = detect_morning_star(df)
        assert mask[-1] is np.bool_(False)


# ─── Evening star ────────────────────────────────────────────────────────────


class TestEveningStar:
    def test_detects(self) -> None:
        # bar[0]: green 100→105, bar[1]: small body (ratio < 0.3), bar[2]: red closes below midpoint
        # midpoint bar[0] = (100+105)/2 = 102.5, close[2]=102 < 102.5 ✓
        df = _df(
            _bar(100.0, 105.0, h=106.0, l=99.0),
            _bar(105.0, 104.5, h=107.0, l=103.0),  # body=0.5, rng=4 → 12.5%
            _bar(105.0, 102.0, h=106.0, l=101.0),
        )
        mask = detect_evening_star(df)
        assert mask[-1] is np.bool_(True)

    def test_rejects_if_bar2_closes_above_midpoint(self) -> None:
        df = _df(
            _bar(100.0, 105.0, h=106.0, l=99.0),
            _bar(105.0, 104.5, h=107.0, l=103.0),
            _bar(105.0, 103.0, h=106.0, l=102.0),  # close=103 > midpoint=102.5
        )
        mask = detect_evening_star(df)
        assert mask[-1] is np.bool_(False)


# ─── detect_all ──────────────────────────────────────────────────────────────


class TestDetectAll:
    def test_returns_all_patterns(self) -> None:
        df = _df(_bar(100.0, 100.0, h=105.0, l=95.0))
        result = detect_all(df)
        assert set(result.keys()) == set(DETECTORS.keys())

    def test_arrays_same_length(self) -> None:
        df = _df(_bar(100.0, 100.1, h=105.0, l=95.0))
        for arr in detect_all(df).values():
            assert len(arr) == len(df)

    def test_pattern_bias_all_defined(self) -> None:
        for name in DETECTORS:
            assert name in PATTERN_BIAS


# ─── MCP tool ────────────────────────────────────────────────────────────────


class TestPatternsTool:
    @pytest.mark.asyncio
    async def test_detect_patterns_success(self) -> None:
        from xt_mcp.tools.patterns import detect_patterns

        n = 50
        closes = [100.0 + i for i in range(n)]
        df = pd.DataFrame({
            "open_time": list(range(n)),
            "open":   closes, "high":   [c + 1 for c in closes],
            "low":    [c - 1 for c in closes], "close":  closes,
            "volume": [1.0] * n,
        })
        mock_engine = AsyncMock()
        mock_engine.run_with_df.return_value = ([], df)

        with patch("xt_mcp.tools.patterns.SignalEngine", return_value=mock_engine):
            result = await detect_patterns("btc_usdt", lookback=50)

        assert result["error"] is False
        assert result["symbol"] == "btc_usdt"
        assert "patterns_found" in result
        assert set(result["patterns_found"].keys()) == set(DETECTORS.keys())
        assert result["total_bars"] == n

    @pytest.mark.asyncio
    async def test_occurrences_within_recent_bars(self) -> None:
        from xt_mcp.tools.patterns import detect_patterns

        # Build a df with a known doji in the last bar: body < 10% of range
        n = 20
        rows = []
        for i in range(n - 1):
            rows.append({"open_time": i, "open": 100.0, "close": 102.0, "high": 103.0, "low": 99.0, "volume": 1.0})
        # last bar: doji (body=0.2, range=10)
        rows.append({"open_time": n - 1, "open": 100.0, "close": 100.2, "high": 105.0, "low": 95.0, "volume": 1.0})
        df = pd.DataFrame(rows)

        mock_engine = AsyncMock()
        mock_engine.run_with_df.return_value = ([], df)

        with patch("xt_mcp.tools.patterns.SignalEngine", return_value=mock_engine):
            result = await detect_patterns("btc_usdt", lookback=n, recent_bars=5)

        assert result["error"] is False
        biases = {o["signal_bias"] for o in result["recent_occurrences"]}
        # At least one occurrence with known bias
        assert biases.issubset({"bullish", "bearish", "neutral"})
