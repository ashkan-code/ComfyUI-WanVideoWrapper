"""XT spot market API client (sapi.xt.com/v4/public/*)."""

from __future__ import annotations

from xt_mcp.clients.base import XTBaseClient
from xt_mcp.config import settings
from xt_mcp.http_client import create_async_client
from xt_mcp.models.spot import (
    SpotDepthResponse,
    SpotKlineResponse,
    SpotSymbolListResponse,
    SpotTickerResponse,
)
from xt_mcp.rate_limiter import get_spot_limiter


class XTSpotClient(XTBaseClient):
    """Client for XT spot market public endpoints. All methods are read-only."""

    def __init__(self) -> None:
        super().__init__(
            http=create_async_client(settings.spot_base_url),
            limiter=get_spot_limiter(),
        )

    async def get_symbols(self) -> SpotSymbolListResponse:
        """List all active spot trading pairs."""
        raw = await self._get("/v4/public/symbol")
        return SpotSymbolListResponse.model_validate(raw)

    async def get_ticker(self, symbol: str) -> SpotTickerResponse:
        """Get current ticker for a symbol (e.g. 'btc_usdt')."""
        raw = await self._get("/v4/public/ticker", params={"symbol": symbol})
        return SpotTickerResponse.model_validate(raw)

    async def get_depth(self, symbol: str, limit: int = 20) -> SpotDepthResponse:
        """Get order book depth. limit: number of price levels per side."""
        raw = await self._get(
            "/v4/public/depth",
            params={"symbol": symbol, "limit": limit},
        )
        return SpotDepthResponse.model_validate(raw)

    async def get_kline(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 100,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> SpotKlineResponse:
        """Get OHLCV candlestick bars.

        Args:
            symbol: Trading pair e.g. 'btc_usdt'
            interval: Candle interval e.g. '1m', '5m', '1h', '1d'
            limit: Max bars to return (max 1500)
            start_time: Start of range in Unix milliseconds (inclusive)
            end_time: End of range in Unix milliseconds (inclusive)
        """
        params: dict = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        raw = await self._get("/v4/public/kline", params=params)
        return SpotKlineResponse.model_validate(raw)
