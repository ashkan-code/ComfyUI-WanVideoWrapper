"""Tests for realized volatility metrics and volatility cone."""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, patch

import numpy as np
import pandas as pd
import pytest

from volatility.metrics import (
    _ann_factor,
    atr_percentile,
    current_hv,
    realized_volatility,
    volatility_cone,
    volatility_regime,
)


# ─── helpers ────────────────────────────────────────────────────────────────


def _close_series(values: list[float]) -> pd.Series:
    return pd.Series(values, name="close")


def _flat_close(n: int = 200, price: float = 100.0) -> pd.Series:
    return _close_series([price] * n)


def _volatile_close(n: int = 200) -> pd.Series:
    rng = np.random.default_rng(42)
    returns = rng.normal(0, 0.02, n)
    prices = [100.0]
    for r in returns:
        prices.append(prices[-1] * math.exp(r))
    return _close_series(prices[:n])


def _df(n: int = 200) -> pd.DataFrame:
    closes = [100.0 + i * 0.3 for i in range(n)]
    return pd.DataFrame({
        "open_time": list(range(n)),
        "open":   closes,
        "high":   [c + 2 for c in closes],
        "low":    [c - 2 for c in closes],
        "close":  closes,
        "volume": [1000.0] * n,
    })


# ─── annualisation factor ─────────────────────────────────────────────────────


class TestAnnFactor:
    def test_known_intervals(self) -> None:
        assert _ann_factor("1h")  == 252 * 24
        assert _ann_factor("1d")  == 252
        assert _ann_factor("4h")  == 252 * 6
        assert _ann_factor("1m")  == 252 * 24 * 60

    def test_unknown_returns_default(self) -> None:
        assert _ann_factor("3h") == 252 * 24   # default = 1h


# ─── realized_volatility ─────────────────────────────────────────────────────


class TestRealizedVolatility:
    def test_constant_price_gives_zero(self) -> None:
        close = _flat_close(50)
        rv = realized_volatility(close, window=10, interval="1d")
        assert rv.dropna().abs().max() == pytest.approx(0.0, abs=1e-10)

    def test_volatile_series_positive(self) -> None:
        close = _volatile_close(100)
        rv = realized_volatility(close, window=10, interval="1d").dropna()
        assert (rv > 0).all()

    def test_output_length_matches_input(self) -> None:
        close = _volatile_close(50)
        rv = realized_volatility(close, window=10, interval="1h")
        assert len(rv) == 50

    def test_higher_volatility_series_gives_higher_hv(self) -> None:
        low_vol  = _close_series([100.0 + 0.01 * i for i in range(100)])
        high_vol = _volatile_close(100)
        hv_low  = realized_volatility(low_vol, 10, "1d").dropna().mean()
        hv_high = realized_volatility(high_vol, 10, "1d").dropna().mean()
        assert hv_high > hv_low


# ─── current_hv ──────────────────────────────────────────────────────────────


class TestCurrentHV:
    def test_returns_float_for_sufficient_data(self) -> None:
        close = _volatile_close(100)
        v = current_hv(close, window=14, interval="1h")
        assert v is not None
        assert v > 0

    def test_returns_none_for_insufficient_data(self) -> None:
        close = _flat_close(5)
        v = current_hv(close, window=20, interval="1h")
        assert v is None

    def test_constant_price_returns_zero(self) -> None:
        close = _flat_close(50)
        v = current_hv(close, window=10, interval="1d")
        assert v == pytest.approx(0.0, abs=1e-8)


# ─── atr_percentile ──────────────────────────────────────────────────────────


class TestATRPercentile:
    def test_returns_value_in_range(self) -> None:
        df = _df(200)
        pct = atr_percentile(df, period=14)
        assert 0.0 <= pct <= 100.0

    def test_type_is_float(self) -> None:
        df = _df(100)
        assert isinstance(atr_percentile(df), float)


# ─── volatility_regime ───────────────────────────────────────────────────────


class TestVolatilityRegime:
    def test_calm(self) -> None:
        assert volatility_regime(10.0) == "CALM"

    def test_normal(self) -> None:
        assert volatility_regime(40.0) == "NORMAL"

    def test_elevated(self) -> None:
        assert volatility_regime(60.0) == "ELEVATED"

    def test_high(self) -> None:
        assert volatility_regime(80.0) == "HIGH"

    def test_boundaries(self) -> None:
        assert volatility_regime(25.0) == "NORMAL"
        assert volatility_regime(50.0) == "ELEVATED"
        assert volatility_regime(75.0) == "HIGH"


# ─── volatility_cone ─────────────────────────────────────────────────────────


class TestVolatilityCone:
    def test_returns_dict_with_windows(self) -> None:
        close = _volatile_close(200)
        cone = volatility_cone(close, windows=(5, 10, 21), interval="1h")
        assert "5" in cone
        assert "10" in cone
        assert "21" in cone

    def test_cone_entry_keys(self) -> None:
        close = _volatile_close(200)
        cone = volatility_cone(close, windows=(10,), interval="1h")
        entry = cone["10"]
        for k in ("window", "min", "p25", "p50", "p75", "max", "current", "percentile"):
            assert k in entry

    def test_percentiles_ordered(self) -> None:
        close = _volatile_close(200)
        cone = volatility_cone(close, windows=(21,), interval="1h")
        e = cone["21"]
        assert e["min"] <= e["p25"] <= e["p50"] <= e["p75"] <= e["max"]

    def test_current_percentile_in_range(self) -> None:
        close = _volatile_close(200)
        cone = volatility_cone(close, windows=(10,), interval="1h")
        assert 0.0 <= cone["10"]["percentile"] <= 100.0

    def test_skips_window_with_no_data(self) -> None:
        close = _flat_close(5)  # too short for window=21
        cone = volatility_cone(close, windows=(21,), interval="1h")
        assert "21" not in cone


# ─── MCP tools ───────────────────────────────────────────────────────────────


class TestVolatilityMCPTools:
    @pytest.mark.asyncio
    async def test_get_volatility_metrics_success(self) -> None:
        from xt_mcp.tools.volatility import get_volatility_metrics
        df = _df(300)
        mock_engine = AsyncMock()
        mock_engine.run_with_df.return_value = ([], df)
        with patch("xt_mcp.tools.volatility.SignalEngine", return_value=mock_engine):
            result = await get_volatility_metrics("btc_usdt")
        assert result["error"] is False
        assert "realized_hv" in result
        assert "atr_percentile" in result
        assert result["volatility_regime"] in ("CALM", "NORMAL", "ELEVATED", "HIGH")

    @pytest.mark.asyncio
    async def test_get_volatility_cone_success(self) -> None:
        from xt_mcp.tools.volatility import get_volatility_cone
        df = _df(500)
        mock_engine = AsyncMock()
        mock_engine.run_with_df.return_value = ([], df)
        with patch("xt_mcp.tools.volatility.SignalEngine", return_value=mock_engine):
            result = await get_volatility_cone("btc_usdt")
        assert result["error"] is False
        assert "cone" in result
        assert isinstance(result["cone"], dict)

    @pytest.mark.asyncio
    async def test_get_volatility_metrics_hv_keys(self) -> None:
        from xt_mcp.tools.volatility import get_volatility_metrics
        df = _df(300)
        mock_engine = AsyncMock()
        mock_engine.run_with_df.return_value = ([], df)
        with patch("xt_mcp.tools.volatility.SignalEngine", return_value=mock_engine):
            result = await get_volatility_metrics("btc_usdt")
        hv = result["realized_hv"]
        assert "7bar" in hv
        assert "14bar" in hv
        assert "30bar" in hv
        assert "60bar" in hv
