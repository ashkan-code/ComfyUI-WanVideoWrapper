"""
ARIA — Gem Hunter Agent
Scans all tradeable assets every 10 minutes to find coins about
to make a significant move before everyone else notices.
"""

import asyncio
import logging
import time

import xt_client as xt
from config import CONFIG

logger = logging.getLogger(__name__)

# Narrative momentum scores — updated manually or via news agent
NARRATIVE_SCORES: dict[str, tuple[str, int]] = {
    "AI": 8, "RWA": 7, "DeFi": 6, "L2": 7, "Meme": 5,
}

SYMBOL_NARRATIVES: dict[str, str] = {
    "INJUSDT": "AI", "FETUSDT": "AI", "AGIXUSDT": "AI",
    "ARBUSDT": "L2", "OPUSDT": "L2", "STXUSDT": "RWA",
    "AAVEUSDT": "DeFi", "UNIUSDT": "DeFi",
    "PEPEUSDT": "Meme", "SHIBUSDT": "Meme",
}


class GemHunterAgent:
    """
    Scans assets for Wyckoff patterns, volume anomalies, and
    smart money accumulation to identify high-probability gem setups.
    """

    def __init__(self, signal_queue: asyncio.Queue, market_analyst=None, whale_tracker=None):
        self.signal_queue = signal_queue
        self.market_analyst = market_analyst
        self.whale_tracker = whale_tracker
        self.interval = CONFIG["gem_scan_interval"]
        self._volume_baseline: dict[str, float] = {}

    # ──────────────────────────────────────────────────────────
    # Main loop
    # ──────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Main scan loop — runs every 10 minutes."""
        logger.info("GemHunterAgent started")
        while True:
            gems = await self.scan_all()
            for gem in gems:
                await self.signal_queue.put({"type": "gem_candidate", "data": gem})
                logger.info("GEM: %s score=%d priority=%s", gem["symbol"], gem["gem_score"], gem["priority"])
            await asyncio.sleep(self.interval)

    # ──────────────────────────────────────────────────────────
    # Scanning
    # ──────────────────────────────────────────────────────────

    async def scan_all(self) -> list[dict]:
        """
        Scan all configured symbols and return gem candidates.

        Returns:
            List of gem dicts sorted by score descending
        """
        gems = []
        for symbol in CONFIG["symbols"]:
            try:
                result = await self.evaluate(symbol)
                if result and result["gem_score"] >= CONFIG["gem_score_min"]:
                    gems.append(result)
            except Exception as exc:
                logger.error("GemHunter scan error %s: %s", symbol, exc)
            await asyncio.sleep(0.1)

        return sorted(gems, key=lambda x: x["gem_score"], reverse=True)

    async def evaluate(self, symbol: str) -> dict | None:
        """
        Full gem evaluation for a single symbol.

        Args:
            symbol: Trading pair

        Returns:
            Gem report dict or None if score too low
        """
        candles_4h = await self._fetch_candles(symbol, "4H", 60)
        candles_1h = await self._fetch_candles(symbol, "1H", 100)

        if len(candles_4h) < 20:
            return None

        volume_signal = self._analyze_volume(symbol, candles_1h)
        wyckoff = self._detect_wyckoff(candles_4h)
        technical = self._technical_setup(candles_4h, candles_1h)
        narrative = self._narrative_score(symbol)
        whale_sig = self.whale_tracker.get_cached(symbol) if self.whale_tracker else {}
        market_sig = self.market_analyst.get_cached(symbol) if self.market_analyst else {}

        score = self._compute_gem_score(wyckoff, volume_signal, technical, narrative, whale_sig)
        if score < CONFIG["gem_score_min"]:
            return None

        direction = self._gem_direction(wyckoff, market_sig)
        current_price = candles_4h[-1]["close"]
        sl, tp1, tp2 = self._suggest_levels(current_price, direction, candles_4h)
        rr = abs(tp1 - current_price) / abs(current_price - sl) if sl != current_price else 0

        return {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "symbol": symbol,
            "gem_score": score,
            "priority": "HIGH" if score >= CONFIG["gem_score_high"] else "MEDIUM",
            "direction": direction,
            "wyckoff": wyckoff,
            "whale_activity": {
                "signal": whale_sig.get("whale_signal", "NEUTRAL") if whale_sig else "NEUTRAL",
            },
            "technical": technical,
            "narrative": narrative,
            "risk_flags": self._risk_flags(whale_sig, candles_4h),
            "summary": self._summarize(symbol, score, wyckoff, direction),
            "suggested_entry": round(current_price, 6),
            "suggested_sl": round(sl, 6),
            "suggested_tp1": round(tp1, 6),
            "suggested_tp2": round(tp2, 6),
            "rr_ratio": round(rr, 2),
        }

    # ──────────────────────────────────────────────────────────
    # Wyckoff detection
    # ──────────────────────────────────────────────────────────

    def _detect_wyckoff(self, candles: list[dict]) -> dict:
        """
        Detect Wyckoff phase from candle structure.

        Returns:
            Dict with phase, event, and confidence
        """
        if len(candles) < 30:
            return {"phase": "unknown", "event": "none", "confidence": 0}

        highs = [c["high"] for c in candles[-30:]]
        lows = [c["low"] for c in candles[-30:]]
        volumes = [c["volume"] for c in candles[-30:]]
        closes = [c["close"] for c in candles[-30:]]

        range_high = max(highs[:-5])
        range_low = min(lows[:-5])
        current_low = min(lows[-5:])
        current_close = closes[-1]
        avg_vol = sum(volumes[:-5]) / max(len(volumes[:-5]), 1)
        recent_vol = sum(volumes[-5:]) / 5

        # Phase C — Spring: price breaks below range then recovers
        spring = current_low < range_low and current_close > range_low
        # Phase C — UTAD: price breaks above range then reverses
        utad = max(highs[-5:]) > range_high and current_close < range_high

        if spring:
            return {
                "phase": "C",
                "event": "Spring",
                "confidence": 80 if recent_vol > avg_vol * 1.5 else 55,
                "range_high": range_high,
                "range_low": range_low,
            }
        if utad:
            return {
                "phase": "C",
                "event": "UTAD",
                "confidence": 75 if recent_vol > avg_vol * 1.5 else 50,
                "range_high": range_high,
                "range_low": range_low,
            }

        # Phase D — Sign of Strength: breakout above range with volume
        if current_close > range_high and recent_vol > avg_vol * 2:
            return {"phase": "D", "event": "SOS", "confidence": 70,
                    "range_high": range_high, "range_low": range_low}

        # Phase B — range building (less interesting)
        if range_low <= current_close <= range_high:
            return {"phase": "B", "event": "ranging", "confidence": 40,
                    "range_high": range_high, "range_low": range_low}

        return {"phase": "unknown", "event": "none", "confidence": 20,
                "range_high": range_high, "range_low": range_low}

    # ──────────────────────────────────────────────────────────
    # Volume analysis
    # ──────────────────────────────────────────────────────────

    def _analyze_volume(self, symbol: str, candles: list[dict]) -> dict:
        if len(candles) < 14:
            return {"anomaly": False, "ratio": 1.0}
        recent = sum(c["volume"] for c in candles[-3:]) / 3
        baseline = sum(c["volume"] for c in candles[-14:-3]) / 11
        ratio = recent / baseline if baseline > 0 else 1.0
        self._volume_baseline[symbol] = baseline
        return {
            "anomaly": ratio >= CONFIG["volume_spike_multiplier"],
            "ratio": round(ratio, 2),
        }

    # ──────────────────────────────────────────────────────────
    # Technical setup
    # ──────────────────────────────────────────────────────────

    def _technical_setup(self, candles_4h: list[dict], candles_1h: list[dict]) -> dict:
        current = candles_4h[-1]["close"] if candles_4h else 0
        highs = [c["high"] for c in candles_4h[-20:]]
        lows = [c["low"] for c in candles_4h[-20:]]
        mid = (max(highs) + min(lows)) / 2 if highs and lows else current

        htf_bias = "bullish" if current > mid else "bearish"
        entry_zone = {"low": round(current * 0.995, 6), "high": round(current * 1.005, 6)}

        return {
            "htf_bias": htf_bias,
            "entry_zone": entry_zone,
            "nearest_liquidity_target": round(max(highs) if htf_bias == "bullish" else min(lows), 6),
            "key_level_type": "OB",
        }

    # ──────────────────────────────────────────────────────────
    # Scoring
    # ──────────────────────────────────────────────────────────

    def _compute_gem_score(self, wyckoff: dict, volume: dict, technical: dict,
                           narrative: dict, whale: dict) -> int:
        score = 0

        # Wyckoff (25 pts)
        if wyckoff.get("event") in ("Spring", "UTAD"):
            score += int(25 * wyckoff.get("confidence", 50) / 100)
        elif wyckoff.get("event") == "SOS":
            score += 15

        # Whale (20 pts)
        whale_sig = (whale or {}).get("whale_signal", "NEUTRAL")
        whale_pts = {"BULLISH_STRONG": 20, "BULLISH_MODERATE": 12,
                     "BEARISH_STRONG": 20, "BEARISH_MODERATE": 12}.get(whale_sig, 0)
        score += whale_pts

        # Volume (15 pts)
        if volume.get("anomaly"):
            score += 15
        elif volume.get("ratio", 1) > 1.5:
            score += 8

        # Technical (15 pts)
        score += 10  # baseline for valid technical

        # Narrative (10 pts)
        score += narrative.get("momentum_score", 0)

        return min(100, score)

    def _narrative_score(self, symbol: str) -> dict:
        category = SYMBOL_NARRATIVES.get(symbol, "Other")
        momentum = NARRATIVE_SCORES.get(category, 3)
        return {"category": category, "momentum_score": momentum}

    def _gem_direction(self, wyckoff: dict, market: dict) -> str:
        if wyckoff.get("event") == "Spring":
            return "long"
        if wyckoff.get("event") == "UTAD":
            return "short"
        return (market or {}).get("overall_bias", "long")

    def _suggest_levels(self, price: float, direction: str, candles: list) -> tuple:
        lows = [c["low"] for c in candles[-10:]]
        highs = [c["high"] for c in candles[-10:]]
        if direction == "long":
            sl = min(lows) * (1 - CONFIG["sl_buffer_pct"])
            tp1 = price + (price - sl) * 2
            tp2 = price + (price - sl) * 3
        else:
            sl = max(highs) * (1 + CONFIG["sl_buffer_pct"])
            tp1 = price - (sl - price) * 2
            tp2 = price - (sl - price) * 3
        return sl, tp1, tp2

    def _risk_flags(self, whale: dict | None, candles: list) -> list[str]:
        flags = []
        if whale and whale.get("funding_rate", {}).get("current", 0) > 0.002:
            flags.append("High funding rate — crowded long")
        return flags

    def _summarize(self, symbol: str, score: int, wyckoff: dict, direction: str) -> str:
        return (
            f"{symbol} scored {score}/100. "
            f"Wyckoff {wyckoff.get('phase','?')}/{wyckoff.get('event','?')} "
            f"({wyckoff.get('confidence',0)}% conf). "
            f"Direction: {direction.upper()}."
        )

    # ──────────────────────────────────────────────────────────
    # Data fetching
    # ──────────────────────────────────────────────────────────

    async def _fetch_candles(self, symbol: str, tf: str, limit: int) -> list[dict]:
        """Fetch OHLCV candles from XT.com."""
        return await xt.get_klines(symbol, tf, limit)
