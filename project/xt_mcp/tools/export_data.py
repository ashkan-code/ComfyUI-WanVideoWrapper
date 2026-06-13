"""MCP tools for exporting OHLCV, signals, and backtest results to CSV/JSON."""

from __future__ import annotations

import logging

from backtesting.engine import Backtester
from export.serializers import (
    backtest_to_json,
    df_to_csv,
    df_to_json,
    signals_to_csv,
    signals_to_json,
    suggest_filename,
)
from signals.engine import SignalEngine
from xt_mcp.exceptions import XTMCPError

logger = logging.getLogger(__name__)

_VALID_FORMATS = {"csv", "json"}


def _error(exc: Exception) -> dict:
    logger.error("%s: %s", type(exc).__name__, exc)
    return {"error": True, "code": type(exc).__name__, "message": str(exc)}


async def export_ohlcv(
    symbol: str,
    interval: str = "1h",
    market: str = "spot",
    lookback: int = 500,
    format: str = "csv",
) -> dict:
    """
    Export OHLCV candle data for a symbol as CSV or JSON.

    Args:
        symbol:   Trading pair e.g. 'btc_usdt'.
        interval: Candle interval (default '1h').
        market:   'spot' or 'futures'.
        lookback: Number of bars (max 1000, default 500).
        format:   Output format: 'csv' or 'json' (default 'csv').

    Returns:
        filename (suggested), rows (count), content (full data as string).
    """
    try:
        fmt = format.lower()
        if fmt not in _VALID_FORMATS:
            raise ValueError(f"format must be one of {sorted(_VALID_FORMATS)}")

        engine = SignalEngine()
        _, df = await engine.run_with_df(
            symbol=symbol, interval=interval,
            strategy_name="rsi_reversal", market=market,
            lookback=min(lookback, 1000),
        )

        content  = df_to_csv(df) if fmt == "csv" else df_to_json(df)
        filename = suggest_filename(symbol, interval, "ohlcv", fmt)

        return {
            "error":    False,
            "symbol":   symbol,
            "interval": interval,
            "market":   market,
            "format":   fmt,
            "filename": filename,
            "rows":     len(df),
            "content":  content,
        }
    except ValueError as exc:
        return _error(exc)
    except XTMCPError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("export_ohlcv failed")
        return _error(exc)


async def export_signals(
    symbol: str,
    strategy: str = "rsi_reversal",
    interval: str = "1h",
    market: str = "spot",
    lookback: int = 500,
    format: str = "csv",
) -> dict:
    """
    Export trading signals for a symbol+strategy as CSV or JSON.

    Args:
        symbol:   Trading pair e.g. 'btc_usdt'.
        strategy: Signal strategy name (default 'rsi_reversal').
        interval: Candle interval (default '1h').
        market:   'spot' or 'futures'.
        lookback: Historical bars to scan (max 1000, default 500).
        format:   'csv' or 'json'.

    Returns:
        filename, signal count, and the serialised signal data.
    """
    try:
        fmt = format.lower()
        if fmt not in _VALID_FORMATS:
            raise ValueError(f"format must be one of {sorted(_VALID_FORMATS)}")

        engine = SignalEngine()
        signals, _ = await engine.run_with_df(
            symbol=symbol, interval=interval,
            strategy_name=strategy, market=market,
            lookback=min(lookback, 1000),
        )

        content  = signals_to_csv(signals) if fmt == "csv" else signals_to_json(signals)
        filename = suggest_filename(symbol, interval, f"signals_{strategy}", fmt)

        return {
            "error":    False,
            "symbol":   symbol,
            "strategy": strategy,
            "interval": interval,
            "market":   market,
            "format":   fmt,
            "filename": filename,
            "count":    len(signals),
            "content":  content,
        }
    except ValueError as exc:
        return _error(exc)
    except XTMCPError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("export_signals failed")
        return _error(exc)


async def export_backtest_result(
    symbol: str,
    strategy: str = "rsi_reversal",
    interval: str = "1h",
    market: str = "spot",
    lookback: int = 500,
    commission_pct: float = 0.1,
) -> dict:
    """
    Run a backtest and export the full result as JSON.

    Includes equity curve, trade log, and performance metrics (Sharpe, max
    drawdown, win rate, profit factor).

    Args:
        symbol:         Trading pair e.g. 'btc_usdt'.
        strategy:       Signal strategy name (default 'rsi_reversal').
        interval:       Candle interval (default '1h').
        market:         'spot' or 'futures'.
        lookback:       Historical bars (max 1000, default 500).
        commission_pct: Round-trip commission percentage (default 0.1 = 0.1 %).

    Returns:
        filename, trade count, and full JSON backtest report.
    """
    try:
        engine = SignalEngine()
        signals, df = await engine.run_with_df(
            symbol=symbol, interval=interval,
            strategy_name=strategy, market=market,
            lookback=min(lookback, 1000),
        )

        bt = Backtester(commission_pct=commission_pct)
        result = bt.run(df, signals)

        content  = backtest_to_json(result)
        filename = suggest_filename(symbol, interval, f"backtest_{strategy}", "json")

        return {
            "error":        False,
            "symbol":       symbol,
            "strategy":     strategy,
            "interval":     interval,
            "market":       market,
            "format":       "json",
            "filename":     filename,
            "trade_count":  len(result.trades),
            "content":      content,
        }
    except XTMCPError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("export_backtest_result failed")
        return _error(exc)
