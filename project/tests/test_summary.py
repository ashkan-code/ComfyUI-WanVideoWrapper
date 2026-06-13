"""Tests for the symbol summary report MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest


# ─── helpers ────────────────────────────────────────────────────────────────


def _df(n: int = 300) -> pd.DataFrame:
    closes = [50_000.0 + i * 10 for i in range(n)]
    return pd.DataFrame({
        "open_time": list(range(n)),
        "open":   closes,
        "high":   [c + 200 for c in closes],
        "low":    [c - 200 for c in closes],
        "close":  closes,
        "volume": [1.0] * n,
    })


def _mock_ticker() -> dict:
    return {"error": False, "symbol": "btc_usdt", "last": 52_000.0}


def _mock_engine(df: pd.DataFrame) -> AsyncMock:
    mock = AsyncMock()
    mock.run_with_df.return_value = ([], df)
    return mock


# ─── get_symbol_report ───────────────────────────────────────────────────────


class TestGetSymbolReport:
    @pytest.mark.asyncio
    async def test_basic_structure(self) -> None:
        from xt_mcp.tools.summary import get_symbol_report

        df = _df()
        with (
            patch("xt_mcp.tools.summary.SignalEngine", return_value=_mock_engine(df)),
            patch("xt_mcp.tools.summary._get_ticker", new=AsyncMock(return_value=_mock_ticker())),
        ):
            result = await get_symbol_report("btc_usdt")

        assert result["error"] is False
        assert result["symbol"] == "btc_usdt"
        assert "regime" in result
        assert "signals" in result
        assert "atr" in result
        assert "generated_at" in result

    @pytest.mark.asyncio
    async def test_ticker_included_when_success(self) -> None:
        from xt_mcp.tools.summary import get_symbol_report

        df = _df()
        with (
            patch("xt_mcp.tools.summary.SignalEngine", return_value=_mock_engine(df)),
            patch("xt_mcp.tools.summary._get_ticker", new=AsyncMock(return_value=_mock_ticker())),
        ):
            result = await get_symbol_report("btc_usdt")

        assert result["ticker"] is not None
        assert result["ticker"]["symbol"] == "btc_usdt"

    @pytest.mark.asyncio
    async def test_ticker_none_when_error(self) -> None:
        from xt_mcp.tools.summary import get_symbol_report

        df = _df()
        error_ticker = {"error": True, "message": "not found"}
        with (
            patch("xt_mcp.tools.summary.SignalEngine", return_value=_mock_engine(df)),
            patch("xt_mcp.tools.summary._get_ticker", new=AsyncMock(return_value=error_ticker)),
        ):
            result = await get_symbol_report("btc_usdt")

        assert result["ticker"] is None

    @pytest.mark.asyncio
    async def test_risk_section_absent_without_capital(self) -> None:
        from xt_mcp.tools.summary import get_symbol_report

        df = _df()
        with (
            patch("xt_mcp.tools.summary.SignalEngine", return_value=_mock_engine(df)),
            patch("xt_mcp.tools.summary._get_ticker", new=AsyncMock(return_value=_mock_ticker())),
        ):
            result = await get_symbol_report("btc_usdt")

        assert result["risk"] is None

    @pytest.mark.asyncio
    async def test_risk_section_present_with_capital(self) -> None:
        from xt_mcp.tools.summary import get_symbol_report

        df = _df()
        with (
            patch("xt_mcp.tools.summary.SignalEngine", return_value=_mock_engine(df)),
            patch("xt_mcp.tools.summary._get_ticker", new=AsyncMock(return_value=_mock_ticker())),
        ):
            result = await get_symbol_report("btc_usdt", capital=10_000.0, risk_pct=1.0)

        assert result["risk"] is not None
        risk = result["risk"]
        assert "stop_price" in risk
        assert "target_price" in risk
        assert "quantity" in risk
        assert risk["stop_price"] < risk["entry_price"]   # long stop below entry

    @pytest.mark.asyncio
    async def test_signals_section_structure(self) -> None:
        from xt_mcp.tools.summary import get_symbol_report

        df = _df()
        with (
            patch("xt_mcp.tools.summary.SignalEngine", return_value=_mock_engine(df)),
            patch("xt_mcp.tools.summary._get_ticker", new=AsyncMock(return_value=_mock_ticker())),
        ):
            result = await get_symbol_report("btc_usdt")

        sig = result["signals"]
        assert "total" in sig
        assert "buy_count" in sig
        assert "sell_count" in sig
        assert "recent" in sig
        assert isinstance(sig["recent"], list)

    @pytest.mark.asyncio
    async def test_regime_section_structure(self) -> None:
        from xt_mcp.tools.summary import get_symbol_report

        df = _df()
        with (
            patch("xt_mcp.tools.summary.SignalEngine", return_value=_mock_engine(df)),
            patch("xt_mcp.tools.summary._get_ticker", new=AsyncMock(return_value=_mock_ticker())),
        ):
            result = await get_symbol_report("btc_usdt")

        regime = result["regime"]
        assert "current" in regime
        assert "dominant" in regime

    @pytest.mark.asyncio
    async def test_atr_positive(self) -> None:
        from xt_mcp.tools.summary import get_symbol_report

        df = _df()
        with (
            patch("xt_mcp.tools.summary.SignalEngine", return_value=_mock_engine(df)),
            patch("xt_mcp.tools.summary._get_ticker", new=AsyncMock(return_value=_mock_ticker())),
        ):
            result = await get_symbol_report("btc_usdt")

        assert result["atr"] is not None
        assert result["atr"] > 0

    @pytest.mark.asyncio
    async def test_short_df_regime_unknown(self) -> None:
        """If DataFrame is too short for regime, regime section notes it gracefully."""
        from xt_mcp.tools.summary import get_symbol_report

        df = _df(n=10)   # too short for regime classifier
        with (
            patch("xt_mcp.tools.summary.SignalEngine", return_value=_mock_engine(df)),
            patch("xt_mcp.tools.summary._get_ticker", new=AsyncMock(return_value=_mock_ticker())),
        ):
            result = await get_symbol_report("btc_usdt")

        assert result["error"] is False   # tool itself does not error
        assert result["regime"]["current"] == "UNKNOWN"

    @pytest.mark.asyncio
    async def test_risk_target_gt_entry_for_long(self) -> None:
        from xt_mcp.tools.summary import get_symbol_report

        df = _df()
        with (
            patch("xt_mcp.tools.summary.SignalEngine", return_value=_mock_engine(df)),
            patch("xt_mcp.tools.summary._get_ticker", new=AsyncMock(return_value=_mock_ticker())),
        ):
            result = await get_symbol_report("btc_usdt", capital=5_000.0, risk_pct=1.0)

        risk = result["risk"]
        assert risk["target_price"] > risk["entry_price"]
        assert risk["stop_price"] < risk["entry_price"]
