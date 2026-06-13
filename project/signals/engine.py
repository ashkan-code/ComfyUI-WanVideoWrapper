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
        signals, _ = await self.run_with_df(
            symbol=symbol,
            interval=interval,
            strategy_name=strategy_name,
            market=market,
            lookback=lookback,
        )
        return signals

    async def run_with_df(
        self,
        symbol: str,
        interval: str,
        strategy_name: str,
        market: str = "spot",
        lookback: int = 500,
    ) -> tuple[list[Signal], pd.DataFrame]:
        """Fetch candles and generate signals; return both signals and the DataFrame.

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
        signals = strategy.generate(df, symbol=symbol, market=market, interval=interval)
        return signals, df

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
