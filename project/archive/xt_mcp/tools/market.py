"""MCP tool implementations for spot and futures market data.

Each function is registered onto the FastMCP instance in server.py.
Tools return plain dicts (not Pydantic models) so FastMCP can serialize them
directly without any additional mapping.

Error handling: exceptions are caught and returned as an error envelope dict
so MCP clients receive parseable error info rather than an opaque MCP error.
"""

from __future__ import annotations

import logging

from xt_mcp.clients.futures import XTFuturesClient
from xt_mcp.clients.spot import XTSpotClient
from xt_mcp.exceptions import XTMCPError
from xt_mcp.models.common import Market

logger = logging.getLogger(__name__)

# Lazily initialized per-process singletons
_spot: XTSpotClient | None = None
_futures: XTFuturesClient | None = None


def _get_spot() -> XTSpotClient:
    global _spot
    if _spot is None:
        _spot = XTSpotClient()
    return _spot


def _get_futures() -> XTFuturesClient:
    global _futures
    if _futures is None:
        _futures = XTFuturesClient()
    return _futures


def _error(exc: Exception) -> dict:
    logger.error("%s: %s", type(exc).__name__, exc)
    return {"error": True, "code": type(exc).__name__, "message": str(exc)}


async def get_symbols(market: str = "spot") -> dict:
    """
    List available trading pairs.

    Args:
        market: 'spot' or 'futures'

    Returns:
        Dict with 'result' list of symbol objects, or error envelope.
    """
    try:
        if market == Market.SPOT:
            resp = await _get_spot().get_symbols()
        else:
            resp = await _get_futures().get_symbols()
        return resp.model_dump()
    except XTMCPError as exc:
        return _error(exc)


async def get_ticker(symbol: str, market: str = "spot") -> dict:
    """
    Get current ticker (price, volume, 24h stats) for a symbol.

    Args:
        symbol: Trading pair e.g. 'btc_usdt'
        market: 'spot' or 'futures'

    Returns:
        Dict with ticker fields, or error envelope.
    """
    try:
        if market == Market.SPOT:
            resp = await _get_spot().get_ticker(symbol)
        else:
            resp = await _get_futures().get_ticker(symbol)
        return resp.model_dump()
    except XTMCPError as exc:
        return _error(exc)


async def get_orderbook(symbol: str, limit: int = 20) -> dict:
    """
    Get spot order book depth (bids and asks).

    Args:
        symbol: Trading pair e.g. 'btc_usdt'
        limit: Number of price levels per side (max 200)

    Returns:
        Dict with 'bids' and 'asks' lists of [price, quantity] pairs.
    """
    try:
        resp = await _get_spot().get_depth(symbol, limit)
        return resp.model_dump()
    except XTMCPError as exc:
        return _error(exc)


async def get_ohlcv(
    symbol: str,
    interval: str = "1h",
    limit: int = 100,
    market: str = "spot",
) -> dict:
    """
    Get OHLCV candlestick bars.

    Args:
        symbol: Trading pair e.g. 'btc_usdt'
        interval: Candle interval — '1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w'
        limit: Number of bars to return (max 1500)
        market: 'spot' or 'futures'

    Returns:
        Dict with 'result' list of OHLCV bars, or error envelope.
    """
    try:
        if market == Market.SPOT:
            resp = await _get_spot().get_kline(symbol, interval, limit)
        else:
            resp = await _get_futures().get_kline(symbol, interval, limit)
        return resp.model_dump()
    except XTMCPError as exc:
        return _error(exc)


async def get_market_info(symbol: str, market: str = "spot") -> dict:
    """
    Get detailed specification for a single trading pair (tick sizes, lot sizes).

    Args:
        symbol: Trading pair e.g. 'btc_usdt'
        market: 'spot' or 'futures'

    Returns:
        Dict with 'symbol' and 'info' (symbol spec), or error envelope.
    """
    try:
        if market == Market.SPOT:
            resp = await _get_spot().get_symbols()
            matches = [s for s in (resp.result or []) if s.symbol == symbol]
        else:
            resp = await _get_futures().get_symbols()
            matches = [s for s in (resp.result or []) if s.symbol == symbol]
        return {
            "symbol": symbol,
            "market": market,
            "info": matches[0].model_dump() if matches else None,
        }
    except XTMCPError as exc:
        return _error(exc)
