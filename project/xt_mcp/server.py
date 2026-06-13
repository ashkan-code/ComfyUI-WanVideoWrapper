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

configure_logging()
logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="xt-exchange",
    instructions=(
        "Read-only market data server for XT Exchange (spot + perpetual futures). "
        "Available: symbols, tickers, order books, OHLCV candles, "
        "funding rates, open interest, and technical indicators (RSI, MACD, "
        "Bollinger Bands, ATR, Stochastic, OBV, VWAP, SMA, EMA, DEMA, WMA). "
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

if __name__ == "__main__":
    logger.info("Starting XT MCP server v%s (stdio transport)", "0.1.0")
    mcp.run(transport="stdio")
