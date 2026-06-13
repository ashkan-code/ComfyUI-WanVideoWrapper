"""MTFAnalyzer: concurrent regime + signal analysis across multiple timeframes."""

from __future__ import annotations

import asyncio
import logging

from regime.classifier import RegimeClassifier
from regime.models import Regime
from signals.engine import SignalEngine

from mtf.models import MTFResult, TimeframeSnapshot

logger = logging.getLogger(__name__)

_RECOMMENDATIONS: dict[str, str] = {
    "BULLISH_ALIGNED":   "All timeframes trending up — strong long bias.",
    "BEARISH_ALIGNED":   "All timeframes trending down — avoid longs, consider shorts.",
    "BULLISH_MAJORITY":  "Majority of timeframes trending up — cautious long bias.",
    "BEARISH_MAJORITY":  "Majority of timeframes trending down — reduce long exposure.",
    "RANGING":           "No directional trend — mean-reversion strategies preferred.",
    "MIXED":             "Conflicting signals — wait for cross-timeframe alignment.",
}


class MTFAnalyzer:
    """Runs regime detection and signals on each timeframe concurrently.

    Confluence score (0–100) measures how unanimously timeframes agree on
    direction.  Trend alignment is derived from the vote tally:
      TRENDING_UP  → +1,  TRENDING_DOWN → -1,  all others → 0.
    """

    def __init__(self, concurrency: int = 3) -> None:
        self._concurrency = concurrency

    # ── public ────────────────────────────────────────────────────────────────

    async def analyze(
        self,
        symbol: str,
        timeframes: list[str],
        strategy: str = "rsi_reversal",
        market: str = "spot",
    ) -> MTFResult:
        sem = asyncio.Semaphore(self._concurrency)

        async def _one(tf: str) -> TimeframeSnapshot | Exception:
            async with sem:
                return await self._snapshot(symbol, tf, strategy, market)

        raw = await asyncio.gather(*[_one(tf) for tf in timeframes], return_exceptions=True)

        snapshots: list[TimeframeSnapshot] = []
        for tf, outcome in zip(timeframes, raw):
            if isinstance(outcome, Exception):
                logger.warning("MTF %s/%s failed: %s", symbol, tf, outcome)
                snapshots.append(TimeframeSnapshot(
                    timeframe=tf, regime=Regime.UNKNOWN.value,
                    adx=0.0, di_plus=0.0, di_minus=0.0, atr_ratio=1.0,
                    last_signal=None, signal_count=0,
                ))
            else:
                snapshots.append(outcome)

        alignment, score = self._compute_alignment(snapshots)
        return MTFResult(
            symbol=symbol,
            market=market,
            strategy=strategy,
            timeframes=snapshots,
            confluence_score=score,
            trend_alignment=alignment,
            recommendation=_RECOMMENDATIONS[alignment],
        )

    # ── helpers ───────────────────────────────────────────────────────────────

    async def _snapshot(
        self, symbol: str, tf: str, strategy: str, market: str
    ) -> TimeframeSnapshot:
        engine = SignalEngine()
        signals, df = await engine.run_with_df(
            symbol=symbol, interval=tf, strategy_name=strategy,
            market=market, lookback=300,
        )

        classifier = RegimeClassifier()
        try:
            result = classifier.classify(df)
        except ValueError:
            return TimeframeSnapshot(
                timeframe=tf, regime=Regime.UNKNOWN.value,
                adx=0.0, di_plus=0.0, di_minus=0.0, atr_ratio=1.0,
                last_signal=None, signal_count=0,
            )

        bar = result.history[-1]
        last_sig = signals[-1].signal_type.value if signals else None
        return TimeframeSnapshot(
            timeframe=tf,
            regime=bar.regime.value,
            adx=bar.adx,
            di_plus=bar.di_plus,
            di_minus=bar.di_minus,
            atr_ratio=bar.atr_ratio,
            last_signal=last_sig,
            signal_count=len(signals),
        )

    @staticmethod
    def _compute_alignment(
        snapshots: list[TimeframeSnapshot],
    ) -> tuple[str, float]:
        if not snapshots:
            return "MIXED", 0.0

        votes = [
            1 if s.regime == Regime.TRENDING_UP.value
            else (-1 if s.regime == Regime.TRENDING_DOWN.value else 0)
            for s in snapshots
        ]
        total = sum(votes)
        n = len(votes)
        score = round(abs(total) / n * 100, 1)

        if total == n:
            alignment = "BULLISH_ALIGNED"
        elif total == -n:
            alignment = "BEARISH_ALIGNED"
        elif total > 0 and abs(total) / n >= 0.5:
            alignment = "BULLISH_MAJORITY"
        elif total < 0 and abs(total) / n >= 0.5:
            alignment = "BEARISH_MAJORITY"
        elif all(v == 0 for v in votes):
            alignment = "RANGING"
        else:
            alignment = "MIXED"

        return alignment, score
