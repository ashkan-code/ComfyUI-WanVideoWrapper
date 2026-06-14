"""Tests for multi-timeframe analysis."""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from mtf.analyzer import MTFAnalyzer
from mtf.models import MTFResult, TimeframeSnapshot
from regime.models import Regime


# ─── helpers ────────────────────────────────────────────────────────────────


def _snap(regime: str, tf: str = "1h") -> TimeframeSnapshot:
    return TimeframeSnapshot(
        timeframe=tf, regime=regime,
        adx=30.0, di_plus=25.0, di_minus=10.0, atr_ratio=1.0,
        last_signal="BUY", signal_count=5,
    )


def _trending_df(n: int = 200) -> pd.DataFrame:
    closes = [100.0 + i * 0.5 for i in range(n)]
    return pd.DataFrame({
        "open_time": list(range(n)),
        "open":   closes,
        "high":   [c + 3 for c in closes],
        "low":    [c - 0.5 for c in closes],
        "close":  closes,
        "volume": [1000.0] * n,
    })


# ─── TimeframeSnapshot ───────────────────────────────────────────────────────


class TestTimeframeSnapshot:
    def test_to_dict_keys(self) -> None:
        s = _snap("TRENDING_UP", "4h")
        d = s.to_dict()
        assert d["timeframe"] == "4h"
        assert d["regime"] == "TRENDING_UP"
        assert "adx" in d
        assert "last_signal" in d


# ─── MTFResult ───────────────────────────────────────────────────────────────


class TestMTFResult:
    def test_to_dict(self) -> None:
        result = MTFResult(
            symbol="btc_usdt", market="spot", strategy="rsi_reversal",
            timeframes=[_snap("TRENDING_UP", "1h"), _snap("TRENDING_UP", "4h")],
            confluence_score=100.0, trend_alignment="BULLISH_ALIGNED",
            recommendation="All timeframes trending up — strong long bias.",
        )
        d = result.to_dict()
        assert d["symbol"] == "btc_usdt"
        assert len(d["timeframes"]) == 2
        assert d["confluence_score"] == 100.0


# ─── Alignment logic ─────────────────────────────────────────────────────────


class TestComputeAlignment:
    def test_all_trending_up(self) -> None:
        snaps = [_snap("TRENDING_UP") for _ in range(4)]
        alignment, score = MTFAnalyzer._compute_alignment(snaps)
        assert alignment == "BULLISH_ALIGNED"
        assert score == pytest.approx(100.0)

    def test_all_trending_down(self) -> None:
        snaps = [_snap("TRENDING_DOWN") for _ in range(4)]
        alignment, score = MTFAnalyzer._compute_alignment(snaps)
        assert alignment == "BEARISH_ALIGNED"
        assert score == pytest.approx(100.0)

    def test_majority_bullish(self) -> None:
        snaps = [_snap("TRENDING_UP")] * 3 + [_snap("RANGING")]
        alignment, score = MTFAnalyzer._compute_alignment(snaps)
        assert alignment == "BULLISH_MAJORITY"
        assert score == pytest.approx(75.0)

    def test_majority_bearish(self) -> None:
        snaps = [_snap("TRENDING_DOWN")] * 3 + [_snap("RANGING")]
        alignment, score = MTFAnalyzer._compute_alignment(snaps)
        assert alignment == "BEARISH_MAJORITY"

    def test_all_ranging(self) -> None:
        snaps = [_snap("RANGING")] * 4
        alignment, score = MTFAnalyzer._compute_alignment(snaps)
        assert alignment == "RANGING"
        assert score == pytest.approx(0.0)

    def test_mixed(self) -> None:
        snaps = [_snap("TRENDING_UP"), _snap("TRENDING_DOWN"), _snap("RANGING"), _snap("RANGING")]
        alignment, score = MTFAnalyzer._compute_alignment(snaps)
        assert alignment == "MIXED"

    def test_empty_snapshots(self) -> None:
        alignment, score = MTFAnalyzer._compute_alignment([])
        assert alignment == "MIXED"
        assert score == 0.0

    def test_single_trending_up(self) -> None:
        alignment, score = MTFAnalyzer._compute_alignment([_snap("TRENDING_UP")])
        assert alignment == "BULLISH_ALIGNED"

    def test_confluence_score_partial(self) -> None:
        # 2/4 = 50% trending up → exactly 50%, but not >= 50% condition (needs > 50 %)
        # Wait, condition is abs(total)/n >= 0.5 → 2/4 = 0.5 → True → BULLISH_MAJORITY
        snaps = [_snap("TRENDING_UP")] * 2 + [_snap("RANGING")] * 2
        alignment, score = MTFAnalyzer._compute_alignment(snaps)
        assert alignment == "BULLISH_MAJORITY"
        assert score == pytest.approx(50.0)


# ─── MTFAnalyzer integration (mocked engine + classifier) ─────────────────


class TestMTFAnalyzerMocked:
    @pytest.mark.asyncio
    async def test_analyze_bullish_aligned(self) -> None:
        df = _trending_df(300)
        mock_engine = AsyncMock()
        mock_engine.run_with_df.return_value = ([], df)

        with patch("mtf.analyzer.SignalEngine", return_value=mock_engine):
            analyzer = MTFAnalyzer(concurrency=2)
            result = await analyzer.analyze("btc_usdt", ["1h", "4h"], market="spot")

        assert isinstance(result, MTFResult)
        assert len(result.timeframes) == 2
        assert result.trend_alignment in (
            "BULLISH_ALIGNED", "BULLISH_MAJORITY", "MIXED", "RANGING",
        )

    @pytest.mark.asyncio
    async def test_analyze_handles_failed_timeframe(self) -> None:
        mock_engine = AsyncMock()
        mock_engine.run_with_df.side_effect = Exception("API error")

        with patch("mtf.analyzer.SignalEngine", return_value=mock_engine):
            analyzer = MTFAnalyzer()
            result = await analyzer.analyze("btc_usdt", ["1h", "4h"])

        # Failed timeframes become UNKNOWN snapshots
        assert all(s.regime == "UNKNOWN" for s in result.timeframes)

    @pytest.mark.asyncio
    async def test_analyze_result_has_recommendation(self) -> None:
        df = _trending_df(300)
        mock_engine = AsyncMock()
        mock_engine.run_with_df.return_value = ([], df)

        with patch("mtf.analyzer.SignalEngine", return_value=mock_engine):
            result = await MTFAnalyzer().analyze("btc_usdt", ["1h"])

        assert len(result.recommendation) > 0


# ─── MCP tool ────────────────────────────────────────────────────────────────


class TestMTFTool:
    @pytest.mark.asyncio
    async def test_analyze_multi_timeframe_success(self) -> None:
        from xt_mcp.tools.mtf import analyze_multi_timeframe

        mock_result = MTFResult(
            symbol="btc_usdt", market="spot", strategy="rsi_reversal",
            timeframes=[_snap("TRENDING_UP", "1h")],
            confluence_score=100.0, trend_alignment="BULLISH_ALIGNED",
            recommendation="Test.",
        )
        mock_analyzer = AsyncMock()
        mock_analyzer.analyze.return_value = mock_result

        with patch("xt_mcp.tools.mtf.MTFAnalyzer", return_value=mock_analyzer):
            result = await analyze_multi_timeframe("btc_usdt", timeframes=["1h"])

        assert result["error"] is False
        assert result["symbol"] == "btc_usdt"
        assert result["confluence_score"] == 100.0

    @pytest.mark.asyncio
    async def test_empty_timeframes_returns_error(self) -> None:
        from xt_mcp.tools.mtf import analyze_multi_timeframe
        result = await analyze_multi_timeframe("btc_usdt", timeframes=[])
        assert result["error"] is True

    @pytest.mark.asyncio
    async def test_default_timeframes_used_when_none(self) -> None:
        from xt_mcp.tools.mtf import analyze_multi_timeframe, _DEFAULT_TIMEFRAMES

        mock_result = MTFResult(
            symbol="btc_usdt", market="spot", strategy="rsi_reversal",
            timeframes=[], confluence_score=0.0,
            trend_alignment="MIXED", recommendation="",
        )
        mock_analyzer = AsyncMock()
        mock_analyzer.analyze.return_value = mock_result

        with patch("xt_mcp.tools.mtf.MTFAnalyzer", return_value=mock_analyzer):
            await analyze_multi_timeframe("btc_usdt", timeframes=None)

        call_args = mock_analyzer.analyze.call_args
        assert call_args.args[1] == _DEFAULT_TIMEFRAMES
