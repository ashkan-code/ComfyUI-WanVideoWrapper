"""DataCollector: fetches paginated OHLCV candles from the XT Exchange API."""

from __future__ import annotations

import logging

from xt_mcp.clients.futures import XTFuturesClient
from xt_mcp.clients.spot import XTSpotClient
from xt_mcp.config import settings

from data_engine.models import Candle

logger = logging.getLogger(__name__)

# Duration of each interval in milliseconds — used to advance the pagination
# cursor after each batch.
INTERVAL_MS: dict[str, int] = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
    "3d": 259_200_000,
    "1w": 604_800_000,
}


class DataCollector:
    """Fetches candles from XT REST API, paging through large date ranges."""

    def __init__(
        self,
        spot_client: XTSpotClient | None = None,
        futures_client: XTFuturesClient | None = None,
    ) -> None:
        self._spot = spot_client or XTSpotClient()
        self._futures = futures_client or XTFuturesClient()

    async def fetch_candles(
        self,
        symbol: str,
        interval: str,
        market: str = "spot",
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> list[Candle]:
        """Fetch all candles in [start_ms, end_ms] for the given symbol.

        Pages through the API using *settings.batch_size* per request.
        Stops when the API returns fewer bars than requested (end of data).
        """
        if market not in ("spot", "futures"):
            raise ValueError(f"Unknown market: {market!r}. Must be 'spot' or 'futures'.")

        batch_size = settings.batch_size
        interval_ms = INTERVAL_MS.get(interval, 3_600_000)
        candles: list[Candle] = []
        current_start = start_ms

        while True:
            if market == "spot":
                resp = await self._spot.get_kline(
                    symbol=symbol,
                    interval=interval,
                    limit=batch_size,
                    start_time=current_start,
                    end_time=end_ms,
                )
                bars = resp.result or []
                for bar in bars:
                    candles.append(
                        Candle(
                            symbol=symbol,
                            market=market,
                            interval=interval,
                            open_time=bar.open_time,
                            open=float(bar.open),
                            high=float(bar.high),
                            low=float(bar.low),
                            close=float(bar.close),
                            volume=float(bar.volume),
                            quote_volume=float(bar.quote_volume),
                            close_time=bar.close_time,
                        )
                    )
            else:  # futures
                resp = await self._futures.get_kline(
                    symbol=symbol,
                    interval=interval,
                    limit=batch_size,
                    start_time=current_start,
                    end_time=end_ms,
                )
                bars = resp.result or []
                for bar in bars:
                    candles.append(
                        Candle(
                            symbol=symbol,
                            market=market,
                            interval=interval,
                            open_time=bar.open_time,
                            open=float(bar.open),
                            high=float(bar.high),
                            low=float(bar.low),
                            close=float(bar.close),
                            volume=float(bar.volume),
                            quote_volume=float(bar.quote_volume),
                            close_time=0,
                        )
                    )

            logger.debug(
                "Fetched %d bars for %s/%s/%s (start=%s)",
                len(bars), symbol, market, interval, current_start,
            )

            if not bars or len(bars) < batch_size:
                break

            # Advance past the last received candle by one interval
            current_start = bars[-1].open_time + interval_ms
            if end_ms is not None and current_start > end_ms:
                break

        return candles
