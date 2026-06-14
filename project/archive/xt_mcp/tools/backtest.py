"""MCP tool for backtesting signal strategies on live OHLCV data."""

from __future__ import annotations

import logging

import pandas as pd

from backtesting.engine import Backtester
from signals.engine import SignalEngine
from xt_mcp.exceptions import XTMCPError

logger = logging.getLogger(__name__)


def _error(exc: Exception) -> dict:
    logger.error("%s: %s", type(exc).__name__, exc)
    return {"error": True, "code": type(exc).__name__, "message": str(exc)}


async def run_backtest(
    symbol: str,
    strategy: str = "rsi_reversal",
    interval: str = "1h",
    market: str = "spot",
    lookback: int = 1000,
    initial_capital: float = 10_000.0,
    commission_pct: float = 0.001,
) -> dict:
    """
    Backtest a signal strategy on recent OHLCV candles from XT Exchange.

    Fetches historical candles, generates BUY/SELL signals via the chosen
    strategy, simulates long-only trading with commission, and returns
    performance metrics plus the equity curve.

    Args:
        symbol:          Trading pair e.g. 'btc_usdt'
        strategy:        Strategy name — use list_signal_strategies to see options.
        interval:        Candle interval: '1m','5m','15m','1h','4h','1d'
        market:          'spot' or 'futures'
        lookback:        Number of historical bars (max 1000). More = better indicator warmup.
        initial_capital: Starting capital in USD (default 10 000).
        commission_pct:  Round-trip commission per leg as a fraction (default 0.001 = 0.1%).

    Returns:
        Dict with metrics, equity_curve summary, recent trades, and strategy info.
    """
    try:
        engine = SignalEngine()
        signals, df = await engine.run_with_df(
            symbol=symbol,
            interval=interval,
            strategy_name=strategy,
            market=market,
            lookback=lookback,
        )

        backtester = Backtester(
            initial_capital=initial_capital,
            commission_pct=commission_pct,
        )
        result = backtester.run(
            df=df,
            signals=signals,
            symbol=symbol,
            interval=interval,
            strategy=strategy,
            market=market,
        )

        recent_trades = [t.to_dict() for t in result.trades[-20:]]
        equity_summary = _equity_summary(result.equity_curve)

        return {
            "error": False,
            "symbol": symbol,
            "interval": interval,
            "market": market,
            "strategy": strategy,
            "candles_analysed": len(df),
            "initial_capital": initial_capital,
            "final_capital": result.final_capital,
            "metrics": result.metrics,
            "equity_summary": equity_summary,
            "recent_trades": recent_trades,
            "total_trades": len(result.trades),
        }

    except ValueError as exc:
        return _error(exc)
    except XTMCPError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("run_backtest failed")
        return _error(exc)


def _equity_summary(curve: list[float]) -> dict:
    if not curve:
        return {}
    return {
        "start": curve[0],
        "end": curve[-1],
        "peak": max(curve),
        "trough": min(curve),
        "num_bars": len(curve),
    }
