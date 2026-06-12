"""
ARIA — Market Analyst Agent
Scans all timeframes, maps market structure, identifies Smart Money zones.
Outputs structured market bias every 5 minutes.
"""

import asyncio
import logging
import time
from typing import Any

import aiohttp

from config import CONFIG

logger = logging.getLogger(__name__)


class MarketAnalystAgent:
    """
    Multi-timeframe structure analysis agent.
    Outputs structured market bias reports to signal_queue.
    """

    def __init__(self, signal_queue: asyncio.Queue):
        self.signal_queue = signal_queue
        self.symbols = CONFIG["symbols"]
        self.interval = CONFIG["market_analysis_interval"]
        self.rest_url = CONFIG["bitunix_rest_url"]
        self._cache: dict[str, dict] = {}

    # ──────────────────────────────────────────────────────────
    # Main loop
    # ──────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Main analysis loop — runs every 5 minutes."""
        logger.info("MarketAnalystAgent started")
        while True:
            for symbol in self.symbols:
                try:
                    analysis = await self.analyze(symbol)
                    self._cache[symbol] = analysis
                    await self.signal_queue.put({"type": "market_analysis", "data": analysis})
                except Exception as exc:
                    logger.error("MarketAnalyst error on %s: %s", symbol, exc)
            await asyncio.sleep(self.interval)

    def get_cached(self, symbol: str) -> dict | None:
        return self._cache.get(symbol)

    # ──────────────────────────────────────────────────────────
    # Core analysis
    # ──────────────────────────────────────────────────────────

    async def analyze(self, symbol: str) -> dict:
        """
        Full multi-timeframe analysis for a symbol.

        Args:
            symbol: Trading pair e.g. "BTCUSDT"

        Returns:
            Structured market analysis dict
        """
        candles: dict[str, list] = {}
        for tf in CONFIG["all_timeframes"]:
            candles[tf] = await self._fetch_candles(symbol, tf, limit=100)
            await asyncio.sleep(0.05)

        htf_structure = self._analyze_structure(candles.get("4H", []), "4H")
        daily_structure = self._analyze_structure(candles.get("1D", []), "1D")
        ltf_structure = self._analyze_structure(candles.get("1H", []), "1H")

        order_blocks = self._find_order_blocks(candles.get("4H", []))
        fvgs = self._find_fvg(candles.get("1H", []))
        liquidity = self._map_liquidity(candles.get("4H", []))
        market_state = self._classify_market_state(htf_structure, daily_structure)
        overall_bias = self._determine_bias(htf_structure, ltf_structure)

        active_pois = []
        for ob in order_blocks[:3]:
            active_pois.append({"type": "OB", **ob})
        for fvg in fvgs[:3]:
            active_pois.append({"type": "FVG", **fvg})

        return {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "symbol": symbol,
            "market_state": market_state,
            "overall_bias": overall_bias,
            "confidence": self._confidence(htf_structure, ltf_structure),
            "htf_structure": {"daily": daily_structure, "4h": htf_structure},
            "ltf_structure": {"1h": ltf_structure},
            "active_pois": active_pois,
            "liquidity_map": liquidity,
            "killzone_active": self._active_killzone(),
            "notes": self._generate_notes(symbol, market_state, overall_bias, active_pois),
        }

    # ──────────────────────────────────────────────────────────
    # Structure detection
    # ──────────────────────────────────────────────────────────

    def _analyze_structure(self, candles: list[dict], tf: str) -> dict:
        """
        Detect BOS/CHoCH and current market structure.

        Args:
            candles: OHLCV candle list (oldest first)
            tf: Timeframe label

        Returns:
            Structure dict with bias, events, and position
        """
        if len(candles) < 20:
            return {"timeframe": tf, "structure": "unknown", "bias": "neutral"}

        highs = [c["high"] for c in candles[-20:]]
        lows = [c["low"] for c in candles[-20:]]
        closes = [c["close"] for c in candles[-20:]]

        # Detect swing points
        swing_highs = self._swing_points(highs, mode="high")
        swing_lows = self._swing_points(lows, mode="low")

        structure = "ranging"
        last_event = "None"
        bias = "neutral"

        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            hh = swing_highs[-1] > swing_highs[-2]
            hl = swing_lows[-1] > swing_lows[-2]
            lh = swing_highs[-1] < swing_highs[-2]
            ll = swing_lows[-1] < swing_lows[-2]

            if hh and hl:
                structure = "bullish"
                bias = "long"
                last_event = "BOS_UP"
            elif lh and ll:
                structure = "bearish"
                bias = "short"
                last_event = "BOS_DOWN"
            elif hh and ll:
                last_event = "CHoCH"
                bias = "neutral"
            elif lh and hl:
                last_event = "CHoCH"
                bias = "neutral"

        # Position in range (premium / discount / equilibrium)
        range_high = max(highs)
        range_low = min(lows)
        current_price = closes[-1]
        mid = (range_high + range_low) / 2
        if current_price > mid * 1.02:
            position = "premium"
        elif current_price < mid * 0.98:
            position = "discount"
        else:
            position = "equilibrium"

        return {
            "timeframe": tf,
            "structure": structure,
            "last_event": last_event,
            "current_position": position,
            "bias": bias,
            "range_high": range_high,
            "range_low": range_low,
        }

    def _swing_points(self, values: list[float], mode: str = "high", window: int = 3) -> list[float]:
        """Find swing highs or lows using a rolling window."""
        result = []
        for i in range(window, len(values) - window):
            segment = values[i - window: i + window + 1]
            pivot = values[i]
            if mode == "high" and pivot == max(segment):
                result.append(pivot)
            elif mode == "low" and pivot == min(segment):
                result.append(pivot)
        return result

    # ──────────────────────────────────────────────────────────
    # Order Blocks & FVG
    # ──────────────────────────────────────────────────────────

    def _find_order_blocks(self, candles: list[dict]) -> list[dict]:
        """
        Find unmitigated order blocks with displacement confirmation.

        Returns:
            List of OB dicts sorted by recency
        """
        obs = []
        if len(candles) < 5:
            return obs
        for i in range(2, len(candles) - 2):
            c = candles[i]
            next_c = candles[i + 1]
            prev_c = candles[i - 1]
            body_size = abs(c["close"] - c["open"])
            displacement = abs(next_c["close"] - c["close"])

            # Bullish OB: bearish candle followed by strong displacement up
            if (
                c["close"] < c["open"]          # bearish body
                and next_c["close"] > c["high"]  # displacement through OB high
                and displacement > body_size * 1.5
            ):
                obs.append({
                    "direction": "bullish",
                    "high": c["high"],
                    "low": c["low"],
                    "price": (c["high"] + c["low"]) / 2,
                    "strength": min(5, int(displacement / body_size)),
                    "index": i,
                })

            # Bearish OB: bullish candle followed by strong displacement down
            if (
                c["close"] > c["open"]           # bullish body
                and next_c["close"] < c["low"]   # displacement through OB low
                and displacement > body_size * 1.5
            ):
                obs.append({
                    "direction": "bearish",
                    "high": c["high"],
                    "low": c["low"],
                    "price": (c["high"] + c["low"]) / 2,
                    "strength": min(5, int(displacement / body_size)),
                    "index": i,
                })

        # Return most recent first, unmitigated only
        current_price = candles[-1]["close"] if candles else 0
        obs = [o for o in obs if not self._is_mitigated(o, current_price)]
        return sorted(obs, key=lambda x: x["index"], reverse=True)[:5]

    def _is_mitigated(self, ob: dict, current_price: float) -> bool:
        """Check if price has already traded through the OB."""
        if ob["direction"] == "bullish" and current_price < ob["low"]:
            return True
        if ob["direction"] == "bearish" and current_price > ob["high"]:
            return True
        return False

    def _find_fvg(self, candles: list[dict]) -> list[dict]:
        """
        Find Fair Value Gaps (3-candle imbalance zones).

        Returns:
            List of FVG dicts
        """
        fvgs = []
        for i in range(1, len(candles) - 1):
            prev_c = candles[i - 1]
            curr_c = candles[i]
            next_c = candles[i + 1]

            # Bullish FVG: gap between prev low and next high
            if next_c["low"] > prev_c["high"]:
                fvgs.append({
                    "direction": "bullish",
                    "high": next_c["low"],
                    "low": prev_c["high"],
                    "mid": (next_c["low"] + prev_c["high"]) / 2,
                    "index": i,
                })

            # Bearish FVG: gap between prev high and next low
            if next_c["high"] < prev_c["low"]:
                fvgs.append({
                    "direction": "bearish",
                    "high": prev_c["low"],
                    "low": next_c["high"],
                    "mid": (prev_c["low"] + next_c["high"]) / 2,
                    "index": i,
                })

        return sorted(fvgs, key=lambda x: x["index"], reverse=True)[:5]

    # ──────────────────────────────────────────────────────────
    # Liquidity mapping
    # ──────────────────────────────────────────────────────────

    def _map_liquidity(self, candles: list[dict]) -> dict:
        """
        Map Buy-Side (BSL) and Sell-Side (SSL) liquidity levels.

        Returns:
            Dict with 'above' (BSL) and 'below' (SSL) lists
        """
        if not candles:
            return {"above": [], "below": []}

        highs = [c["high"] for c in candles[-30:]]
        lows = [c["low"] for c in candles[-30:]]
        current = candles[-1]["close"]

        # Find equal highs/lows (within 0.1%)
        bsl = []
        ssl = []
        tolerance = 0.001

        for i, h in enumerate(highs):
            for j, h2 in enumerate(highs):
                if i != j and abs(h - h2) / h < tolerance and h > current:
                    if h not in bsl:
                        bsl.append(round(h, 4))

        for i, l in enumerate(lows):
            for j, l2 in enumerate(lows):
                if i != j and abs(l - l2) / l < tolerance and l < current:
                    if l not in ssl:
                        ssl.append(round(l, 4))

        return {
            "above": sorted(set(bsl))[:5],
            "below": sorted(set(ssl), reverse=True)[:5],
        }

    # ──────────────────────────────────────────────────────────
    # State classifiers
    # ──────────────────────────────────────────────────────────

    def _classify_market_state(self, htf: dict, daily: dict) -> str:
        if htf.get("structure") == "bullish" and daily.get("structure") == "bullish":
            return "TRENDING_BULLISH"
        if htf.get("structure") == "bearish" and daily.get("structure") == "bearish":
            return "TRENDING_BEARISH"
        if htf.get("last_event") in ("BOS_UP", "CHoCH") and htf.get("structure") == "bullish":
            return "ACCUMULATION"
        if htf.get("last_event") in ("BOS_DOWN", "CHoCH") and htf.get("structure") == "bearish":
            return "DISTRIBUTION"
        return "RANGING"

    def _determine_bias(self, htf: dict, ltf: dict) -> str:
        htf_b = htf.get("bias", "neutral")
        ltf_b = ltf.get("bias", "neutral")
        if htf_b == "long" and ltf_b == "long":
            return "long"
        if htf_b == "short" and ltf_b == "short":
            return "short"
        if htf_b in ("long", "short"):
            return htf_b
        return "neutral"

    def _confidence(self, htf: dict, ltf: dict) -> int:
        score = 40
        if htf.get("structure") != "ranging":
            score += 20
        if htf.get("bias") == ltf.get("bias"):
            score += 25
        if htf.get("current_position") in ("premium", "discount"):
            score += 15
        return min(100, score)

    def _active_killzone(self) -> str:
        hour = int(time.strftime("%H", time.gmtime()))
        if 2 <= hour < 5:
            return "london_open"
        if 7 <= hour < 9:
            return "london_close"
        if 12 <= hour < 15:
            return "ny_open"
        if 17 <= hour < 20:
            return "ny_close"
        if 22 <= hour or hour < 2:
            return "asia"
        return "none"

    def _generate_notes(self, symbol: str, state: str, bias: str, pois: list) -> str:
        poi_str = f"{len(pois)} active POIs" if pois else "no clear POIs"
        return f"{symbol}: {state} — bias {bias.upper()}, {poi_str}."

    # ──────────────────────────────────────────────────────────
    # Data fetching
    # ──────────────────────────────────────────────────────────

    async def _fetch_candles(self, symbol: str, timeframe: str, limit: int = 100) -> list[dict]:
        """
        Fetch OHLCV candles from Bitunix REST API.

        Args:
            symbol: e.g. "BTCUSDT"
            timeframe: e.g. "4H", "1H", "15m"
            limit: number of candles

        Returns:
            List of {"open","high","low","close","volume","timestamp"} dicts
        """
        tf_map = {"1D": "1d", "4H": "4h", "1H": "1h", "15m": "15m", "5m": "5m", "1W": "1w"}
        interval = tf_map.get(timeframe, timeframe.lower())
        url = f"{self.rest_url}/fapi/v1/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
            return [
                {
                    "timestamp": row[0],
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                }
                for row in data
            ]
        except Exception as exc:
            logger.warning("Candle fetch failed %s/%s: %s", symbol, timeframe, exc)
            return []
