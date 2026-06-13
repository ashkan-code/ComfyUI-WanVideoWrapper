"""Tests for data export serialisers and MCP tools."""

from __future__ import annotations

import csv
import io
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from export.serializers import (
    backtest_to_json,
    df_to_csv,
    df_to_json,
    signals_to_csv,
    signals_to_json,
    suggest_filename,
)


# ─── helpers ────────────────────────────────────────────────────────────────


def _df(n: int = 10) -> pd.DataFrame:
    return pd.DataFrame({
        "open_time": list(range(n)),
        "open":   [100.0] * n,
        "high":   [101.0] * n,
        "low":    [99.0]  * n,
        "close":  [100.5] * n,
        "volume": [1000.0] * n,
    })


def _mock_signal(ts: int, sig_type: str = "BUY", price: float = 100.0):
    sig = MagicMock()
    sig.to_dict.return_value = {
        "timestamp": ts, "signal_type": sig_type, "price": price,
        "symbol": "btc_usdt", "strategy": "rsi_reversal",
    }
    return sig


def _mock_backtest_result():
    m = MagicMock()
    m.symbol = "btc_usdt"
    m.interval = "1h"
    m.strategy = "rsi_reversal"
    m.market = "spot"
    m.initial_capital = 10_000.0
    m.final_capital = 11_500.0
    m.metrics = {"sharpe_ratio": 1.2, "total_return_pct": 15.0}
    m.trades = []
    return m


def _ohlcv_df(n: int = 200) -> pd.DataFrame:
    closes = [50_000.0 + i * 10 for i in range(n)]
    return pd.DataFrame({
        "open_time": list(range(n)),
        "open": closes, "high": [c + 200 for c in closes],
        "low":  [c - 200 for c in closes], "close": closes,
        "volume": [1.0] * n,
    })


# ─── df_to_csv ───────────────────────────────────────────────────────────────


class TestDfToCsv:
    def test_has_header(self) -> None:
        csv_str = df_to_csv(_df())
        lines = csv_str.strip().splitlines()
        assert "open_time" in lines[0]

    def test_row_count(self) -> None:
        csv_str = df_to_csv(_df(5))
        lines = csv_str.strip().splitlines()
        assert len(lines) == 6   # header + 5 rows

    def test_max_rows_respected(self) -> None:
        csv_str = df_to_csv(_df(100), max_rows=10)
        reader = csv.DictReader(io.StringIO(csv_str))
        rows = list(reader)
        assert len(rows) == 10

    def test_valid_csv(self) -> None:
        csv_str = df_to_csv(_df(5))
        reader = csv.DictReader(io.StringIO(csv_str))
        rows = list(reader)
        assert rows[0]["close"] == "100.5"


# ─── df_to_json ──────────────────────────────────────────────────────────────


class TestDfToJson:
    def test_valid_json(self) -> None:
        json_str = df_to_json(_df(5))
        data = json.loads(json_str)
        assert isinstance(data, list)
        assert len(data) == 5

    def test_has_expected_keys(self) -> None:
        data = json.loads(df_to_json(_df(3)))
        assert "close" in data[0]

    def test_max_rows_respected(self) -> None:
        data = json.loads(df_to_json(_df(100), max_rows=5))
        assert len(data) == 5


# ─── signals_to_csv ──────────────────────────────────────────────────────────


class TestSignalsToCsv:
    def test_empty_signals(self) -> None:
        assert signals_to_csv([]) == ""

    def test_has_header(self) -> None:
        sigs = [_mock_signal(i) for i in range(3)]
        csv_str = signals_to_csv(sigs)
        assert "timestamp" in csv_str.splitlines()[0]

    def test_row_count(self) -> None:
        sigs = [_mock_signal(i) for i in range(5)]
        csv_str = signals_to_csv(sigs)
        rows = list(csv.DictReader(io.StringIO(csv_str)))
        assert len(rows) == 5

    def test_max_rows(self) -> None:
        sigs = [_mock_signal(i) for i in range(20)]
        csv_str = signals_to_csv(sigs, max_rows=5)
        rows = list(csv.DictReader(io.StringIO(csv_str)))
        assert len(rows) == 5


# ─── signals_to_json ─────────────────────────────────────────────────────────


class TestSignalsToJson:
    def test_valid_json(self) -> None:
        sigs = [_mock_signal(i) for i in range(3)]
        data = json.loads(signals_to_json(sigs))
        assert len(data) == 3

    def test_empty_signals(self) -> None:
        data = json.loads(signals_to_json([]))
        assert data == []


# ─── backtest_to_json ────────────────────────────────────────────────────────


class TestBacktestToJson:
    def test_valid_json(self) -> None:
        result = _mock_backtest_result()
        data = json.loads(backtest_to_json(result))
        assert "metrics" in data

    def test_contains_expected_keys(self) -> None:
        result = _mock_backtest_result()
        data = json.loads(backtest_to_json(result))
        assert data["metrics"]["sharpe_ratio"] == pytest.approx(1.2)


# ─── suggest_filename ────────────────────────────────────────────────────────


class TestSuggestFilename:
    def test_format_extension(self) -> None:
        assert suggest_filename("btc_usdt", "1h", "ohlcv", "csv").endswith(".csv")
        assert suggest_filename("btc_usdt", "1h", "ohlcv", "json").endswith(".json")

    def test_symbol_in_filename(self) -> None:
        assert "btc_usdt" in suggest_filename("btc_usdt", "1h", "ohlcv", "csv")

    def test_slash_replaced(self) -> None:
        fname = suggest_filename("btc/usdt", "1h", "ohlcv", "csv")
        assert "/" not in fname


# ─── MCP tools ───────────────────────────────────────────────────────────────


class TestExportMCPTools:
    @pytest.mark.asyncio
    async def test_export_ohlcv_csv(self) -> None:
        from xt_mcp.tools.export_data import export_ohlcv
        df = _ohlcv_df(50)
        mock_engine = AsyncMock()
        mock_engine.run_with_df.return_value = ([], df)
        with patch("xt_mcp.tools.export_data.SignalEngine", return_value=mock_engine):
            result = await export_ohlcv("btc_usdt", format="csv")
        assert result["error"] is False
        assert result["format"] == "csv"
        assert result["rows"] == 50
        assert "open_time" in result["content"]

    @pytest.mark.asyncio
    async def test_export_ohlcv_json(self) -> None:
        from xt_mcp.tools.export_data import export_ohlcv
        df = _ohlcv_df(10)
        mock_engine = AsyncMock()
        mock_engine.run_with_df.return_value = ([], df)
        with patch("xt_mcp.tools.export_data.SignalEngine", return_value=mock_engine):
            result = await export_ohlcv("btc_usdt", format="json")
        assert result["error"] is False
        data = json.loads(result["content"])
        assert len(data) == 10

    @pytest.mark.asyncio
    async def test_export_ohlcv_invalid_format(self) -> None:
        from xt_mcp.tools.export_data import export_ohlcv
        result = await export_ohlcv("btc_usdt", format="xml")
        assert result["error"] is True

    @pytest.mark.asyncio
    async def test_export_signals_csv(self) -> None:
        from xt_mcp.tools.export_data import export_signals
        sigs = [_mock_signal(i) for i in range(5)]
        df = _ohlcv_df(100)
        mock_engine = AsyncMock()
        mock_engine.run_with_df.return_value = (sigs, df)
        with patch("xt_mcp.tools.export_data.SignalEngine", return_value=mock_engine):
            result = await export_signals("btc_usdt", format="csv")
        assert result["error"] is False
        assert result["count"] == 5
        assert "timestamp" in result["content"]

    @pytest.mark.asyncio
    async def test_export_signals_json(self) -> None:
        from xt_mcp.tools.export_data import export_signals
        sigs = [_mock_signal(i) for i in range(3)]
        df = _ohlcv_df(100)
        mock_engine = AsyncMock()
        mock_engine.run_with_df.return_value = (sigs, df)
        with patch("xt_mcp.tools.export_data.SignalEngine", return_value=mock_engine):
            result = await export_signals("btc_usdt", format="json")
        assert result["error"] is False
        data = json.loads(result["content"])
        assert len(data) == 3

    @pytest.mark.asyncio
    async def test_export_backtest_result(self) -> None:
        from xt_mcp.tools.export_data import export_backtest_result
        df = _ohlcv_df(200)
        mock_engine = AsyncMock()
        mock_engine.run_with_df.return_value = ([], df)
        with (
            patch("xt_mcp.tools.export_data.SignalEngine", return_value=mock_engine),
        ):
            result = await export_backtest_result("btc_usdt")
        assert result["error"] is False
        assert result["format"] == "json"
        assert "trade_count" in result
        data = json.loads(result["content"])
        assert "metrics" in data
        assert "trades" in data

    @pytest.mark.asyncio
    async def test_filename_in_export_ohlcv(self) -> None:
        from xt_mcp.tools.export_data import export_ohlcv
        df = _ohlcv_df(10)
        mock_engine = AsyncMock()
        mock_engine.run_with_df.return_value = ([], df)
        with patch("xt_mcp.tools.export_data.SignalEngine", return_value=mock_engine):
            result = await export_ohlcv("btc_usdt", interval="4h", format="csv")
        assert result["filename"].endswith(".csv")
        assert "btc_usdt" in result["filename"]
