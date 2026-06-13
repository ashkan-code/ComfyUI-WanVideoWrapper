"""XT futures market API client (fapi.xt.com/future/market/v1/public/*)."""

from __future__ import annotations

from xt_mcp.clients.base import XTBaseClient
from xt_mcp.config import settings
from xt_mcp.http_client import create_async_client
from xt_mcp.models.futures import (
    FundingRateResponse,
    FuturesKlineResponse,
    FuturesSymbolListResponse,
    FuturesTickerResponse,
    OpenInterestResponse,
)
from xt_mcp.rate_limiter import get_futures_limiter


class XTFuturesClient(XTBaseClient):
    """Client for XT perpetual futures public endpoints. All methods are read-only."""

    def __init__(self) -> None:
        super().__init__(
            http=create_async_client(settings.futures_base_url),
            limiter=get_futures_limiter(),
        )

    async def get_symbols(self) -> FuturesSymbolListResponse:
        """List all active perpetual futures contracts."""
        raw = await self._get("/future/market/v1/public/symbol/detail")
        return FuturesSymbolListResponse.model_validate(raw)

    async def get_ticker(self, symbol: str) -> FuturesTickerResponse:
        """Get current ticker for a futures symbol (e.g. 'btc_usdt')."""
        raw = await self._get(
            "/future/market/v1/public/q/tickers",
            params={"symbol": symbol},
        )
        return FuturesTickerResponse.model_validate(raw)

    async def get_kline(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 100,
    ) -> FuturesKlineResponse:
        """Get OHLCV candlestick bars for a futures symbol."""
        raw = await self._get(
            "/future/market/v1/public/q/kline",
            params={"symbol": symbol, "interval": interval, "limit": limit},
        )
        return FuturesKlineResponse.model_validate(raw)

    async def get_funding_rate(
        self,
        symbol: str,
        limit: int = 10,
    ) -> FundingRateResponse:
        """Get historical funding rate records (settled every 8 hours)."""
        raw = await self._get(
            "/future/market/v1/public/q/funding-rate-record",
            params={"symbol": symbol, "limit": limit},
        )
        return FundingRateResponse.model_validate(raw)

    async def get_open_interest(self, symbol: str) -> OpenInterestResponse:
        """Get current open interest (contracts + USD value) for a symbol."""
        raw = await self._get(
            "/future/market/v1/public/contract/open-interest",
            params={"symbol": symbol},
        )
        return OpenInterestResponse.model_validate(raw)
