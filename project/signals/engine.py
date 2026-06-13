"""SignalEngine: fetches candles from the XT API and runs a strategy."""

from __future__ import annotations

import logging

import pandas as pd

from signals.models import Signal
from signals.registry import get_strategy
from xt_mcp.clients.futures import XTFuturesClient
from xt_mcp.clients.spot import XTSpotClient

logger = logging.getLogger(__name__)


class SignalEngine:
    """Fetches live candle data and runs a named strategy to produce signals."""

    def __init__(
        self,
        spot_client: XTSpotClient | None = None,
        futures_client: XTFuturesClient | None = None,
    ) -> None:
        self._spot = spot_client or XTSpotClient()
        self._futures = futures_client or XTFuturesClient()

    async def run(
        self,
        symbol: str,
        interval: str,
        strategy_name: str,
        market: str = "spot",
        lookback: int = 500,
    ) -> list[Signal]:
        """Fetch *lookback* candles and generate signals with *strategy_name*.

        Args:
            symbol:        Trading pair e.g. 'btc_usdt'
            interval:      Candle interval e.g. '1h', '4h', '1d'
            strategy_name: One of the registered strategy names
            market:        'spot' or 'futures'
            lookback:      Number of historical bars to analyse (min 50)

        Returns:
            List of Signal objects, ordered by timestamp ascending.

        Raises:
            ValueError: Unknown strategy name or market.
            XTMCPError: API connectivity issue.
        """
        strategy = get_strategy(strategy_name)
        df = await self._fetch_df(symbol, interval, market, min(lookback, 1000))
        logger.debug(
            "SignalEngine: %d bars for %s/%s/%s strategy=%s",
            len(df), symbol, market, interval, strategy_name,
        )
        return strategy.generate(df, symbol=symbol, market=market, interval=interval)

    async def _fetch_df(
        self,
        symbol: str,
        interval: str,
        market: str,
        limit: int,
    ) -> pd.DataFrame:
        if market == "spot":
            resp = await self._spot.get_kline(symbol, interval, limit)
            bars = resp.result or []
            return pd.DataFrame(
                [
                    {
                        "open_time": b.open_time,
                        "open": float(b.open),
                        "high": float(b.high),
                        "low": float(b.low),
                        "close": float(b.close),
                        "volume": float(b.volume),
                    }
                    for b in bars
                ]
            )
        elif market == "futures":
            resp = await self._futures.get_kline(symbol, interval, limit)
            bars = resp.result or []
            return pd.DataFrame(
                [
                    {
                        "open_time": b.open_time,
                        "open": float(b.open),
                        "high": float(b.high),
                        "low": float(b.low),
                        "close": float(b.close),
                        "volume": float(b.volume),
                    }
                    for b in bars
                ]
            )
        else:
            raise ValueError(f"Unknown market: {market!r}")
