"""SyncManager: orchestrates full and incremental candle syncs."""

from __future__ import annotations

import asyncio
import logging
import time

from xt_mcp.config import settings

from data_engine.collector import INTERVAL_MS, DataCollector
from data_engine.storage import CandleStore

logger = logging.getLogger(__name__)

_MS_PER_DAY = 86_400_000


class SyncManager:
    """Coordinates DataCollector → CandleStore for one or many symbols."""

    def __init__(
        self,
        store: CandleStore,
        collector: DataCollector | None = None,
    ) -> None:
        self._store = store
        self._collector = collector or DataCollector()

    # ── single-key sync ───────────────────────────────────────────────────────

    async def sync_symbol(
        self,
        symbol: str,
        interval: str,
        market: str = "spot",
        *,
        force_full: bool = False,
    ) -> int:
        """Sync one (symbol, market, interval) key.

        When *force_full* is False (the default), starts from one interval
        after the latest stored candle — or from *max_history_days* ago when
        the store is empty.  Returns the number of candles stored.
        """
        now_ms = int(time.time() * 1000)

        if not force_full:
            latest = self._store.get_latest_timestamp(symbol, market, interval)
        else:
            latest = None

        if latest is not None:
            interval_ms = INTERVAL_MS.get(interval, 3_600_000)
            start_ms = latest + interval_ms
            logger.info(
                "Incremental sync %s/%s/%s from %d", symbol, market, interval, start_ms
            )
        else:
            start_ms = now_ms - settings.max_history_days * _MS_PER_DAY
            logger.info(
                "Full sync %s/%s/%s from %d", symbol, market, interval, start_ms
            )

        end_ms = now_ms

        if start_ms >= end_ms:
            logger.debug("Nothing to sync for %s/%s/%s", symbol, market, interval)
            return 0

        candles = await self._collector.fetch_candles(
            symbol=symbol,
            interval=interval,
            market=market,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        stored = self._store.upsert_candles(candles)
        logger.info(
            "Stored %d candles for %s/%s/%s", stored, symbol, market, interval
        )
        return stored

    # ── batch sync helpers ────────────────────────────────────────────────────

    async def _run_all(
        self,
        symbols: list[str],
        timeframes: list[str],
        market: str,
        force_full: bool,
    ) -> dict[str, int]:
        sem = asyncio.Semaphore(settings.sync_concurrency)

        async def _bounded(sym: str, tf: str) -> tuple[str, int]:
            async with sem:
                count = await self.sync_symbol(
                    sym, tf, market=market, force_full=force_full
                )
                return f"{sym}/{tf}", count

        tasks = [_bounded(s, t) for s in symbols for t in timeframes]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        summary: dict[str, int] = {}
        for item in results:
            if isinstance(item, BaseException):
                logger.error("Sync task failed: %s", item)
            else:
                key, count = item
                summary[key] = count
        return summary

    async def full_sync(
        self,
        symbols: list[str] | None = None,
        timeframes: list[str] | None = None,
        market: str = "spot",
    ) -> dict[str, int]:
        """Full historical sync, ignoring any existing data in the store."""
        return await self._run_all(
            symbols or settings.default_symbols,
            timeframes or settings.default_timeframes,
            market,
            force_full=True,
        )

    async def incremental_sync(
        self,
        symbols: list[str] | None = None,
        timeframes: list[str] | None = None,
        market: str = "spot",
    ) -> dict[str, int]:
        """Incremental sync — only fetches bars newer than what is stored."""
        return await self._run_all(
            symbols or settings.default_symbols,
            timeframes or settings.default_timeframes,
            market,
            force_full=False,
        )
