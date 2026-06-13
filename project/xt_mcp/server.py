"""XT Exchange MCP Server entrypoint.

Run from the project/ directory:
    python -m xt_mcp.server

Or via scripts/run_server.sh (Termux):
    bash scripts/run_server.sh

Transport: stdio (compatible with Claude Desktop, Claude Code, and all MCP clients).
Phase 1: read-only market data. Trading endpoints are disabled.
"""

from __future__ import annotations

import logging

from fastmcp import FastMCP

from xt_mcp.logging_setup import configure_logging
from xt_mcp.tools.analysis import get_indicators, list_available_indicators
from xt_mcp.tools.derivatives import get_funding_rates, get_open_interest
from xt_mcp.tools.market import (
    get_market_info,
    get_ohlcv,
    get_orderbook,
    get_symbols,
    get_ticker,
)
from xt_mcp.tools.backtest import run_backtest
from xt_mcp.tools.optimizer import list_optimization_templates, optimize_strategy
from xt_mcp.tools.portfolio import find_pairs, get_correlation_matrix, portfolio_backtest
from xt_mcp.tools.regime import detect_regime, regime_filtered_signals
from xt_mcp.tools.scanner import list_scanner_presets, scan_market
from xt_mcp.tools.watchlist import (
    add_to_watchlist,
    check_watchlist_signals,
    get_recent_alerts,
    list_watchlist,
    remove_from_watchlist,
)
from xt_mcp.tools.signals import list_signal_strategies, run_strategy
from xt_mcp.tools.walk_forward import walk_forward_validate

configure_logging()
logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="xt-exchange",
    instructions=(
        "Read-only market data + quantitative analysis server for XT Exchange. "
        "Market data: symbols, tickers, order books, OHLCV candles, funding rates, open interest. "
        "Technical analysis: RSI, MACD, Bollinger Bands, ATR, Stochastic, OBV, VWAP, SMA, EMA. "
        "Signal generation: BUY/SELL signals from 9 built-in strategies "
        "(rsi_reversal, ema_cross, macd_cross, bb_mean_revert, combined_momentum, …). "
        "Backtesting: simulate long-only strategies on historical candles with commission, "
        "equity curve, Sharpe ratio, max drawdown, and trade log. "
        "All trading actions are disabled."
    ),
)

# Phase 1 — market data
mcp.tool()(get_symbols)
mcp.tool()(get_ticker)
mcp.tool()(get_orderbook)
mcp.tool()(get_ohlcv)
mcp.tool()(get_market_info)
mcp.tool()(get_funding_rates)
mcp.tool()(get_open_interest)

# Phase 3 — technical indicators
mcp.tool()(get_indicators)
mcp.tool()(list_available_indicators)

# Phase 4 — signal generation
mcp.tool()(run_strategy)
mcp.tool()(list_signal_strategies)

# Phase 5 — backtesting
mcp.tool()(run_backtest)

# Phase 6 — market scanner
mcp.tool()(scan_market)
mcp.tool()(list_scanner_presets)

# Phase 7 — strategy optimizer
mcp.tool()(optimize_strategy)
mcp.tool()(list_optimization_templates)

# Phase 8 — walk-forward validation
mcp.tool()(walk_forward_validate)

# Phase 9 — portfolio & correlation
mcp.tool()(get_correlation_matrix)
mcp.tool()(find_pairs)
mcp.tool()(portfolio_backtest)

# Phase 10 — regime detection
mcp.tool()(detect_regime)
mcp.tool()(regime_filtered_signals)

# Phase 11 — watchlist & alerts
mcp.tool()(add_to_watchlist)
mcp.tool()(remove_from_watchlist)
mcp.tool()(list_watchlist)
mcp.tool()(check_watchlist_signals)
mcp.tool()(get_recent_alerts)

if __name__ == "__main__":
    logger.info("Starting XT MCP server v%s (stdio transport)", "0.1.0")
    mcp.run(transport="stdio")
