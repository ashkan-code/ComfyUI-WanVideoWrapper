"""MarketScanner: runs a signal strategy across multiple symbols concurrently."""

from __future__ import annotations

import asyncio
import logging
import time

from signals.engine import SignalEngine
from signals.models import SignalType
from scanner.models import ScanResult, SymbolResult

logger = logging.getLogger(__name__)

_MAX_SYMBOLS = 50   # hard cap to avoid hammering the API


class MarketScanner:
    """Scans a list of symbols in parallel and ranks them by signal activity."""

    def __init__(
        self,
        concurrency: int = 5,
        lookback: int = 200,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        self.concurrency = concurrency
        self.lookback = min(lookback, 1000)

    async def scan(
        self,
        symbols: list[str],
        strategy_name: str,
        interval: str = "1h",
        market: str = "spot",
    ) -> ScanResult:
        """Run *strategy_name* on each symbol concurrently and aggregate results.

        Symbols that fail (network error, invalid pair) are recorded with
        error=True and do not abort the scan.

        Returns:
            ScanResult with per-symbol results sorted by total_signals descending
            (active symbols first), then alphabetically.
        """
        capped = symbols[:_MAX_SYMBOLS]
        t0 = time.monotonic()

        semaphore = asyncio.Semaphore(self.concurrency)
        engine = SignalEngine()

        tasks = [
            self._scan_one(engine, semaphore, sym, strategy_name, interval, market)
            for sym in capped
        ]
        symbol_results: list[SymbolResult] = await asyncio.gather(*tasks)

        succeeded = sum(1 for r in symbol_results if r.error is None)
        failed = len(symbol_results) - succeeded

        # Sort: active (has signals) first by signal count desc, then error-free,
        # then alphabetically.
        symbol_results.sort(key=lambda r: (-r.total_signals, r.error is not None, r.symbol))

        return ScanResult(
            strategy=strategy_name,
            interval=interval,
            market=market,
            scanned=len(capped),
            succeeded=succeeded,
            failed=failed,
            results=symbol_results,
            elapsed_ms=(time.monotonic() - t0) * 1000.0,
        )

    async def _scan_one(
        self,
        engine: SignalEngine,
        semaphore: asyncio.Semaphore,
        symbol: str,
        strategy_name: str,
        interval: str,
        market: str,
    ) -> SymbolResult:
        async with semaphore:
            t0 = time.monotonic()
            try:
                signals = await engine.run(
                    symbol=symbol,
                    interval=interval,
                    strategy_name=strategy_name,
                    market=market,
                    lookback=self.lookback,
                )
                buys = sum(1 for s in signals if s.signal_type == SignalType.BUY)
                sells = sum(1 for s in signals if s.signal_type == SignalType.SELL)
                latest = signals[-1] if signals else None
                return SymbolResult(
                    symbol=symbol,
                    market=market,
                    interval=interval,
                    strategy=strategy_name,
                    total_signals=len(signals),
                    buy_signals=buys,
                    sell_signals=sells,
                    latest_signal=latest,
                    elapsed_ms=(time.monotonic() - t0) * 1000.0,
                )
            except Exception as exc:
                logger.warning("scan_one %s failed: %s", symbol, exc)
                return SymbolResult(
                    symbol=symbol,
                    market=market,
                    interval=interval,
                    strategy=strategy_name,
                    total_signals=0,
                    buy_signals=0,
                    sell_signals=0,
                    latest_signal=None,
                    error=str(exc),
                    elapsed_ms=(time.monotonic() - t0) * 1000.0,
                )
