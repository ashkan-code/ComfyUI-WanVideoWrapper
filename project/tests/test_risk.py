"""Tests for risk management: sizing functions, RiskManager, and MCP tools."""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from risk.manager import RiskManager
from risk.models import PositionSize, RiskReport, StopTarget
from risk.sizing import (
    atr_stop_price,
    atr_target_price,
    kelly_fraction,
    size_from_fixed_stop,
)


# ─── kelly_fraction ──────────────────────────────────────────────────────────


class TestKellyFraction:
    def test_basic_positive(self) -> None:
        # p=0.6, b=1.5/1.0 → f* = (0.6*2.5 - 1)/1.5 = 0.5/1.5 ≈ 0.333, half=0.167
        f = kelly_fraction(win_rate=0.6, avg_win=1.5, avg_loss=1.0)
        assert f == pytest.approx(0.1667, abs=1e-3)

    def test_negative_expectancy_returns_zero(self) -> None:
        # p=0.3, b=1.0 → f* = (0.3*2 - 1)/1 = -0.4 → 0
        f = kelly_fraction(win_rate=0.3, avg_win=1.0, avg_loss=1.0)
        assert f == 0.0

    def test_capped_at_cap(self) -> None:
        # Very favorable: p=0.9, b=10 → huge kelly; capped at 0.25
        f = kelly_fraction(win_rate=0.9, avg_win=10.0, avg_loss=1.0, cap=0.25)
        assert f == pytest.approx(0.25)

    def test_win_rate_zero_returns_zero(self) -> None:
        assert kelly_fraction(0.0, 2.0, 1.0) == 0.0

    def test_win_rate_one_returns_zero(self) -> None:
        assert kelly_fraction(1.0, 2.0, 1.0) == 0.0

    def test_avg_loss_zero_returns_zero(self) -> None:
        assert kelly_fraction(0.6, 2.0, 0.0) == 0.0

    def test_avg_win_zero_returns_zero(self) -> None:
        assert kelly_fraction(0.6, 0.0, 1.0) == 0.0

    def test_half_kelly_not_full(self) -> None:
        # full kelly for p=0.55, b=2 is (0.55*3-1)/2 = 0.325; half = 0.1625
        f = kelly_fraction(0.55, 2.0, 1.0, cap=1.0)
        assert f == pytest.approx(0.1625, abs=1e-4)


# ─── size_from_fixed_stop ────────────────────────────────────────────────────


class TestSizeFromFixedStop:
    def test_basic(self) -> None:
        # capital=10000, risk=1%, entry=100, stop=98 → risk_amount=100, per_unit=2 → qty=50
        qty = size_from_fixed_stop(10_000, 0.01, 100.0, 98.0)
        assert qty == pytest.approx(50.0)

    def test_zero_stop_distance_returns_zero(self) -> None:
        assert size_from_fixed_stop(10_000, 0.01, 100.0, 100.0) == 0.0

    def test_zero_capital_returns_zero(self) -> None:
        assert size_from_fixed_stop(0, 0.01, 100.0, 98.0) == 0.0

    def test_short_side_same_formula(self) -> None:
        # short: entry=100, stop=102 → distance=2 → same quantity as long
        qty = size_from_fixed_stop(10_000, 0.01, 100.0, 102.0)
        assert qty == pytest.approx(50.0)


# ─── ATR stop / target ───────────────────────────────────────────────────────


class TestATRPrices:
    def test_long_stop_below_entry(self) -> None:
        stop = atr_stop_price(100.0, "long", atr=2.0, multiplier=2.0)
        assert stop == pytest.approx(96.0)

    def test_short_stop_above_entry(self) -> None:
        stop = atr_stop_price(100.0, "short", atr=2.0, multiplier=2.0)
        assert stop == pytest.approx(104.0)

    def test_long_target_above_entry(self) -> None:
        target = atr_target_price(100.0, "long", atr=2.0, multiplier=2.0, reward_ratio=2.0)
        assert target == pytest.approx(108.0)   # entry + 2*2*2

    def test_short_target_below_entry(self) -> None:
        target = atr_target_price(100.0, "short", atr=2.0, multiplier=2.0, reward_ratio=2.0)
        assert target == pytest.approx(92.0)

    def test_reward_ratio_scales_target(self) -> None:
        t1 = atr_target_price(100.0, "long", atr=2.0, multiplier=1.0, reward_ratio=3.0)
        t2 = atr_target_price(100.0, "long", atr=2.0, multiplier=1.0, reward_ratio=6.0)
        assert t2 - 100.0 == pytest.approx(2.0 * (t1 - 100.0))


# ─── RiskManager ─────────────────────────────────────────────────────────────


class TestRiskManager:
    def test_size_fixed_basic(self) -> None:
        mgr = RiskManager()
        pos = mgr.size_fixed(10_000.0, 0.01, 100.0, 98.0)
        assert isinstance(pos, PositionSize)
        assert pos.method == "fixed_fraction"
        assert pos.quantity == pytest.approx(50.0)
        assert pos.position_value == pytest.approx(5_000.0)
        assert pos.risk_amount == pytest.approx(100.0)

    def test_size_kelly_basic(self) -> None:
        mgr = RiskManager()
        pos = mgr.size_kelly(10_000.0, 0.6, 1.5, 1.0, 100.0, 98.0)
        assert pos.method == "kelly"
        assert pos.risk_pct > 0
        assert pos.quantity > 0

    def test_size_kelly_negative_expectancy_zero_qty(self) -> None:
        mgr = RiskManager()
        pos = mgr.size_kelly(10_000.0, 0.3, 1.0, 1.0, 100.0, 98.0)
        assert pos.quantity == 0.0

    def test_stops_from_atr_long(self) -> None:
        mgr = RiskManager(default_atr_multiplier=2.0, default_reward_ratio=3.0)
        st = mgr.stops_from_atr(50_000.0, "long", atr=500.0)
        assert st.stop_price == pytest.approx(49_000.0)   # 50000 - 2*500
        assert st.target_price == pytest.approx(53_000.0)  # 50000 + 2*500*3
        assert st.risk_reward_ratio == pytest.approx(3.0)

    def test_stops_from_atr_short(self) -> None:
        mgr = RiskManager()
        st = mgr.stops_from_atr(50_000.0, "short", atr=500.0, atr_multiplier=2.0, reward_ratio=2.0)
        assert st.stop_price == pytest.approx(51_000.0)
        assert st.target_price == pytest.approx(48_000.0)

    def test_stops_from_pct_long(self) -> None:
        mgr = RiskManager()
        st = mgr.stops_from_pct(100.0, "long", stop_pct=0.02, target_pct=0.04)
        assert st.stop_price == pytest.approx(98.0)
        assert st.target_price == pytest.approx(104.0)
        assert st.risk_reward_ratio == pytest.approx(2.0)

    def test_stops_from_pct_short(self) -> None:
        mgr = RiskManager()
        st = mgr.stops_from_pct(100.0, "short", stop_pct=0.02, target_pct=0.04)
        assert st.stop_price == pytest.approx(102.0)
        assert st.target_price == pytest.approx(96.0)

    def test_full_report_structure(self) -> None:
        mgr = RiskManager()
        report = mgr.full_report(
            symbol="btc_usdt", interval="1h", market="spot",
            capital=10_000.0, risk_pct=0.01, entry_price=50_000.0,
            side="long", atr=500.0,
        )
        assert isinstance(report, RiskReport)
        assert report.max_loss > 0
        assert report.max_gain > report.max_loss  # default R:R = 2

    def test_full_report_max_loss_equals_risk_amount(self) -> None:
        mgr = RiskManager()
        report = mgr.full_report(
            symbol="btc_usdt", interval="1h", market="spot",
            capital=10_000.0, risk_pct=0.01, entry_price=50_000.0,
            side="long", atr=500.0, atr_multiplier=2.0,
        )
        assert report.max_loss == pytest.approx(report.position_size.risk_amount, rel=1e-5)

    def test_full_report_kelly(self) -> None:
        mgr = RiskManager()
        report = mgr.full_report(
            symbol="btc_usdt", interval="1h", market="spot",
            capital=10_000.0, risk_pct=0.01, entry_price=50_000.0,
            side="long", atr=500.0, method="kelly",
            win_rate=0.55, avg_win=2.0, avg_loss=1.0,
        )
        assert report.position_size.method == "kelly"


# ─── to_dict ─────────────────────────────────────────────────────────────────


class TestModelsToDict:
    def test_position_size_to_dict(self) -> None:
        mgr = RiskManager()
        pos = mgr.size_fixed(10_000.0, 0.01, 100.0, 98.0)
        d = pos.to_dict()
        assert d["method"] == "fixed_fraction"
        assert d["risk_pct"] == pytest.approx(1.0)   # returned as %
        assert d["quantity"] == pytest.approx(50.0)

    def test_stop_target_to_dict(self) -> None:
        mgr = RiskManager()
        st = mgr.stops_from_atr(100.0, "long", atr=2.0)
        d = st.to_dict()
        assert "stop_price" in d
        assert "target_price" in d
        assert "risk_reward_ratio" in d
        assert d["stop_pct"] > 0

    def test_risk_report_to_dict(self) -> None:
        mgr = RiskManager()
        report = mgr.full_report(
            symbol="eth_usdt", interval="4h", market="futures",
            capital=5_000.0, risk_pct=0.02, entry_price=3_000.0,
            side="short", atr=60.0,
        )
        d = report.to_dict()
        assert d["symbol"] == "eth_usdt"
        assert "position_size" in d
        assert "stop_target" in d
        assert d["max_gain"] > d["max_loss"]


# ─── MCP tools ───────────────────────────────────────────────────────────────


class TestRiskMCPTools:
    @pytest.mark.asyncio
    async def test_calculate_position_size_fixed(self) -> None:
        from xt_mcp.tools.risk import calculate_position_size
        result = await calculate_position_size(
            capital=10_000.0, entry_price=100.0, stop_price=98.0, risk_pct=1.0
        )
        assert result["error"] is False
        assert result["quantity"] == pytest.approx(50.0)

    @pytest.mark.asyncio
    async def test_calculate_position_size_kelly(self) -> None:
        from xt_mcp.tools.risk import calculate_position_size
        result = await calculate_position_size(
            capital=10_000.0, entry_price=100.0, stop_price=98.0,
            method="kelly", win_rate=0.6, avg_win=1.5, avg_loss=1.0,
        )
        assert result["error"] is False
        assert result["method"] == "kelly"
        assert result["quantity"] > 0

    @pytest.mark.asyncio
    async def test_calculate_position_size_kelly_missing_params(self) -> None:
        from xt_mcp.tools.risk import calculate_position_size
        result = await calculate_position_size(
            capital=10_000.0, entry_price=100.0, stop_price=98.0,
            method="kelly",  # no win_rate etc.
        )
        assert result["error"] is True

    @pytest.mark.asyncio
    async def test_calculate_position_size_bad_capital(self) -> None:
        from xt_mcp.tools.risk import calculate_position_size
        result = await calculate_position_size(
            capital=-100.0, entry_price=100.0, stop_price=98.0
        )
        assert result["error"] is True

    @pytest.mark.asyncio
    async def test_calculate_risk_report(self) -> None:
        from xt_mcp.tools.risk import calculate_risk_report

        # Build a minimal DataFrame that compute_adx can process
        n = 100
        prices = [50_000.0 + i * 10 for i in range(n)]
        df = pd.DataFrame({
            "open_time": list(range(n)),
            "open":   prices,
            "high":   [p + 200 for p in prices],
            "low":    [p - 200 for p in prices],
            "close":  prices,
            "volume": [1.0] * n,
        })

        mock_engine = AsyncMock()
        mock_engine.run_with_df.return_value = ([], df)

        with patch("xt_mcp.tools.risk.SignalEngine", return_value=mock_engine):
            result = await calculate_risk_report(
                symbol="btc_usdt",
                capital=10_000.0,
                entry_price=50_000.0,
                side="long",
                risk_pct=1.0,
            )

        assert result["error"] is False
        assert result["symbol"] == "btc_usdt"
        assert "position_size" in result
        assert "stop_target" in result
        assert result["stop_target"]["stop_price"] < 50_000.0  # long stop below entry

    @pytest.mark.asyncio
    async def test_calculate_risk_report_short(self) -> None:
        from xt_mcp.tools.risk import calculate_risk_report

        n = 100
        prices = [3_000.0] * n
        df = pd.DataFrame({
            "open_time": list(range(n)),
            "open": prices, "high": [p + 50 for p in prices],
            "low":  [p - 50 for p in prices], "close": prices,
            "volume": [1.0] * n,
        })
        mock_engine = AsyncMock()
        mock_engine.run_with_df.return_value = ([], df)

        with patch("xt_mcp.tools.risk.SignalEngine", return_value=mock_engine):
            result = await calculate_risk_report(
                symbol="eth_usdt", capital=5_000.0,
                entry_price=3_000.0, side="short", risk_pct=1.0,
            )

        assert result["error"] is False
        assert result["stop_target"]["stop_price"] > 3_000.0  # short stop above entry

    @pytest.mark.asyncio
    async def test_calculate_risk_report_invalid_side(self) -> None:
        from xt_mcp.tools.risk import calculate_risk_report
        result = await calculate_risk_report(
            symbol="btc_usdt", capital=10_000.0,
            entry_price=50_000.0, side="sideways",
        )
        assert result["error"] is True
