"""MCP tool implementations for futures derivatives data.

Covers: funding rates and open interest.
See tools/market.py for the error-handling convention.
"""

from __future__ import annotations

import logging

from xt_mcp.clients.futures import XTFuturesClient
from xt_mcp.exceptions import XTMCPError

logger = logging.getLogger(__name__)

_futures: XTFuturesClient | None = None


def _get_futures() -> XTFuturesClient:
    global _futures
    if _futures is None:
        _futures = XTFuturesClient()
    return _futures


def _error(exc: Exception) -> dict:
    logger.error("%s: %s", type(exc).__name__, exc)
    return {"error": True, "code": type(exc).__name__, "message": str(exc)}


async def get_funding_rates(symbol: str, limit: int = 10) -> dict:
    """
    Get historical funding rate records for a perpetual futures symbol.

    Funding is settled every 8 hours (00:00, 08:00, 16:00 UTC).

    Args:
        symbol: Futures symbol e.g. 'btc_usdt'
        limit: Number of historical records to return (default 10)

    Returns:
        Dict with 'result' list of funding rate records, or error envelope.
    """
    try:
        resp = await _get_futures().get_funding_rate(symbol, limit)
        return resp.model_dump()
    except XTMCPError as exc:
        return _error(exc)


async def get_open_interest(symbol: str) -> dict:
    """
    Get current open interest for a perpetual futures symbol.

    Args:
        symbol: Futures symbol e.g. 'btc_usdt'

    Returns:
        Dict with open interest count and USD value, or error envelope.
    """
    try:
        resp = await _get_futures().get_open_interest(symbol)
        return resp.model_dump()
    except XTMCPError as exc:
        return _error(exc)
