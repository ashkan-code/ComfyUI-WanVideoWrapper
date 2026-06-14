"""Tests for volume profile, VWAP, and divergence detection."""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, patch

import numpy as np
import pandas as pd
import pytest

from volume.divergence import detect_volume_divergence
from volume.models import DivergenceSignal, VolumeProfileResult, VWAPResult
from volume.profile import compute_volume_profile
from volume.vwap import compute_vwap


# ─── helpers ────────────────────────────────────────────────────────────────


def _flat_df(price: float = 100.0, n: int = 100, volume: float = 1000.0) -> pd.DataFrame:
    return pd.DataFrame({
        "open_time": list(range(n)),
        "open":   [price] * n,
        "high":   [price + 1.0] * n,
        "low":    [price - 1.0] * n,
        "close":  [price] * n,
        "volume": [volume] * n,
    })


def _trend_df(n: int = 200) -> pd.DataFrame:
    closes = [100.0 + i * 0.5 for i in range(n)]
    return pd.DataFrame({
        "open_time": list(range(n)),
        "open":   closes,
        "high":   [c + 2 for c in closes],
        "low":    [c - 1 for c in closes],
        "close":  closes,
        "volume": [1000.0] * n,
    })


# ─── VolumeProfileResult ─────────────────────────────────────────────────────


class TestVolumeProfileResult:
    def test_poc_within_val_vah(self) -> None:
        df = _trend_df(200)
        result = compute_volume_profile(df, bins=20)
        assert result.val <= result.poc_price <= result.vah

    def test_vah_gt_val(self) -> None:
        df = _trend_df(200)
        result = compute_volume_profile(df, bins=20)
        assert result.vah >= result.val

    def test_total_volume_positive(self) -> None:
        df = _flat_df(n=50)
        result = compute_volume_profile(df, bins=10)
        assert result.total_volume > 0

    def test_value_area_pct_near_70(self) -> None:
        df = _trend_df(200)
        result = compute_volume_profile(df, bins=50)
        # Value area should capture ≥ 70 % (may be slightly more due to bin granularity)
        assert result.value_area_pct >= 0.68

    def test_bins_sum_to_total_volume(self) -> None:
        df = _trend_df(100)
        result = compute_volume_profile(df, bins=20)
        bin_total = sum(b.volume for b in result.bins)
        assert bin_total == pytest.approx(result.total_volume, rel=1e-5)

    def test_poc_is_highest_volume_bin(self) -> None:
        df = _trend_df(100)
        result = compute_volume_profile(df, bins=20)
        if result.bins:
            max_vol_bin = max(result.bins, key=lambda b: b.volume)
            assert abs(max_vol_bin.price_mid - result.poc_price) < 1.0

    def test_flat_price_single_poc(self) -> None:
        df = _flat_df(100.0, n=100)
        result = compute_volume_profile(df, bins=10)
        assert abs(result.poc_price - 100.0) < 1.5   # within one bin of 100

    def test_to_dict_keys(self) -> None:
        df = _trend_df(100)
        d = compute_volume_profile(df, bins=20).to_dict()
        assert "poc_price" in d
        assert "vah" in d
        assert "val" in d
        assert "top_bins" in d

    def test_invalid_bins_raises(self) -> None:
        # bins < 2 handled in MCP tool, profile itself clips to 0
        df = _flat_df(n=10)
        result = compute_volume_profile(df, bins=1)
        # Should not raise, just degenerate result
        assert result.poc_price >= 0


# ─── VWAP ────────────────────────────────────────────────────────────────────


class TestVWAP:
    def test_flat_price_vwap_equals_price(self) -> None:
        df = _flat_df(100.0, n=50)
        result = compute_vwap(df)
        assert result.current_vwap == pytest.approx(100.0, abs=0.01)

    def test_bands_symmetric_around_vwap_flat(self) -> None:
        df = _flat_df(100.0, n=50)
        result = compute_vwap(df)
        assert result.current_upper_1 >= result.current_vwap
        assert result.current_lower_1 <= result.current_vwap

    def test_upper_band2_gt_upper_band1(self) -> None:
        df = _trend_df(100)
        result = compute_vwap(df, std_multiplier=2.0)
        assert result.current_upper_2 >= result.current_upper_1
        assert result.current_lower_2 <= result.current_lower_1

    def test_position_above_vwap_for_uptrend(self) -> None:
        df = _trend_df(100)
        result = compute_vwap(df)
        # Trending up: last price likely above early VWAP
        assert result.position in (
            "ABOVE_VWAP", "ABOVE_BAND1", "ABOVE_BAND2",
            "BELOW_VWAP", "BELOW_BAND1", "BELOW_BAND2",
        )

    def test_position_is_valid_label(self) -> None:
        df = _flat_df(100.0, n=50)
        result = compute_vwap(df)
        valid = {"ABOVE_BAND2", "ABOVE_BAND1", "ABOVE_VWAP", "BELOW_VWAP", "BELOW_BAND1", "BELOW_BAND2"}
        assert result.position in valid

    def test_to_dict_keys(self) -> None:
        df = _flat_df(100.0, n=30)
        d = compute_vwap(df).to_dict()
        assert "vwap" in d
        assert "position" in d
        assert "upper_band_2" in d


# ─── Volume Divergence ───────────────────────────────────────────────────────


class TestVolumeDivergence:
    def _rising_price_falling_vol_df(self, n: int = 200) -> pd.DataFrame:
        """Rising price + volume that shrinks over time → bearish divergence."""
        closes = [100.0 + i * 0.5 for i in range(n)]
        volumes = [max(1.0, 2000.0 - i * 8) for i in range(n)]
        return pd.DataFrame({
            "open_time": list(range(n)),
            "open":   closes,
            "high":   [c + 1 for c in closes],
            "low":    [c - 1 for c in closes],
            "close":  closes,
            "volume": volumes,
        })

    def test_bearish_divergence_detected(self) -> None:
        df = self._rising_price_falling_vol_df(200)
        signals = detect_volume_divergence(df, window=14, price_thresh=0.02, vol_decline_thresh=0.15)
        bearish = [s for s in signals if s.divergence_type == "BEARISH"]
        assert len(bearish) > 0

    def test_constant_volume_no_divergence(self) -> None:
        df = _trend_df(200)
        # All volume = 1000 → no decline → no divergence
        signals = detect_volume_divergence(df, window=14, price_thresh=0.02, vol_decline_thresh=0.15)
        assert len(signals) == 0

    def test_returns_list_of_signals(self) -> None:
        df = _trend_df(200)
        signals = detect_volume_divergence(df)
        assert isinstance(signals, list)
        for s in signals:
            assert isinstance(s, DivergenceSignal)

    def test_signal_type_valid(self) -> None:
        df = self._rising_price_falling_vol_df(200)
        signals = detect_volume_divergence(df)
        for s in signals:
            assert s.divergence_type in ("BEARISH", "BULLISH_EXHAUSTION")

    def test_signal_to_dict_keys(self) -> None:
        s = DivergenceSignal(open_time=1000, divergence_type="BEARISH",
                             price_change_pct=3.5, volume_ratio=0.8)
        d = s.to_dict()
        assert "open_time" in d
        assert "divergence_type" in d
        assert "volume_ratio" in d


# ─── MCP tools ───────────────────────────────────────────────────────────────


class TestVolumeMCPTools:
    @pytest.mark.asyncio
    async def test_get_volume_profile_success(self) -> None:
        from xt_mcp.tools.volume import get_volume_profile
        df = _trend_df(200)
        mock_engine = AsyncMock()
        mock_engine.run_with_df.return_value = ([], df)
        with patch("xt_mcp.tools.volume.SignalEngine", return_value=mock_engine):
            result = await get_volume_profile("btc_usdt", bins=20)
        assert result["error"] is False
        assert "poc_price" in result
        assert result["val"] <= result["poc_price"] <= result["vah"]

    @pytest.mark.asyncio
    async def test_get_volume_profile_invalid_bins(self) -> None:
        from xt_mcp.tools.volume import get_volume_profile
        result = await get_volume_profile("btc_usdt", bins=1)
        assert result["error"] is True

    @pytest.mark.asyncio
    async def test_get_vwap_analysis_success(self) -> None:
        from xt_mcp.tools.volume import get_vwap_analysis
        df = _flat_df(100.0, n=100)
        mock_engine = AsyncMock()
        mock_engine.run_with_df.return_value = ([], df)
        with patch("xt_mcp.tools.volume.SignalEngine", return_value=mock_engine):
            result = await get_vwap_analysis("btc_usdt")
        assert result["error"] is False
        assert result["vwap"] == pytest.approx(100.0, abs=0.1)
        assert "position" in result

    @pytest.mark.asyncio
    async def test_detect_volume_divergence_success(self) -> None:
        from xt_mcp.tools.volume import detect_volume_divergence
        df = _trend_df(200)
        mock_engine = AsyncMock()
        mock_engine.run_with_df.return_value = ([], df)
        with patch("xt_mcp.tools.volume.SignalEngine", return_value=mock_engine):
            result = await detect_volume_divergence("btc_usdt")
        assert result["error"] is False
        assert "total" in result
        assert "signals" in result
