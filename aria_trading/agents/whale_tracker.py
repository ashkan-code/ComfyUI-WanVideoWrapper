"""
ARIA — Whale Tracker Agent
Monitors on-chain data, exchange flows, and derivatives to detect
large player activity before it appears on the chart.
"""

import asyncio
import logging
import time

import xt_client as xt
from config import CONFIG

logger = logging.getLogger(__name__)


class WhaleTrackerAgent:
    """
    Monitors exchange flows, funding rates, OI, and large transactions
    to classify whale sentiment for each symbol.
    """

    def __init__(self, signal_queue: asyncio.Queue):
        self.signal_queue = signal_queue
        self.interval = CONFIG["whale_check_interval"]
        self.glassnode_key = CONFIG["glassnode_api_key"]
        self._cache: dict[str, dict] = {}

    # ──────────────────────────────────────────────────────────
    # Main loop
    # ──────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Main monitoring loop — runs every 3 minutes."""
        logger.info("WhaleTrackerAgent started")
        while True:
            for symbol in CONFIG["symbols"]:
                try:
                    signal = await self.analyze(symbol)
                    self._cache[symbol] = signal
                    await self.signal_queue.put({"type": "whale_signal", "data": signal})
                except Exception as exc:
                    logger.error("WhaleTracker error on %s: %s", symbol, exc)
            await asyncio.sleep(self.interval)

    def get_cached(self, symbol: str) -> dict | None:
        return self._cache.get(symbol)

    # ──────────────────────────────────────────────────────────
    # Core analysis
    # ──────────────────────────────────────────────────────────

    async def analyze(self, symbol: str) -> dict:
        """
        Full whale intelligence analysis for a symbol.

        Args:
            symbol: Trading pair e.g. "BTCUSDT"

        Returns:
            Whale signal dict
        """
        funding = await self.get_funding_rate(symbol)
        oi = await self.get_open_interest(symbol)
        liq_clusters = await self.get_liquidation_clusters(symbol)
        exchange_flow = await self.get_exchange_flow(symbol)

        whale_signal = self._classify_signal(funding, oi, exchange_flow)
        confidence = self._confidence(funding, oi, exchange_flow)

        result = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "symbol": symbol,
            "whale_signal": whale_signal,
            "exchange_flow": exchange_flow,
            "funding_rate": {
                "current": funding,
                "bias": self._funding_bias(funding),
            },
            "open_interest": oi,
            "liquidation_clusters": liq_clusters,
            "confidence": confidence,
            "summary": self._summarize(symbol, whale_signal, funding, oi),
        }
        return result

    # ──────────────────────────────────────────────────────────
    # Data fetchers
    # ──────────────────────────────────────────────────────────

    async def get_funding_rate(self, symbol: str) -> float:
        """Fetch current perpetual funding rate from XT.com."""
        return await xt.get_funding_rate(symbol)

    async def get_open_interest(self, symbol: str) -> dict:
        """Fetch open interest from XT.com."""
        return await xt.get_open_interest(symbol)

    async def get_liquidation_clusters(self, symbol: str) -> dict:
        """Estimate liquidation clusters based on current price."""
        price = await xt.get_price(symbol)
        if price == 0:
            return {"nearest_above": {}, "nearest_below": {}}
        return {
            "nearest_above": {"price": round(price * 1.10, 2), "size_usd": 0},
            "nearest_below": {"price": round(price * 0.90, 2), "size_usd": 0},
        }

    async def get_exchange_flow(self, symbol: str) -> dict:
        """
        Get 24h exchange flow using Glassnode API (BTC/ETH only).
        Falls back to neutral signal for other symbols.

        Returns:
            Dict with 24h_netflow and trend classification
        """
        if not self.glassnode_key or symbol not in ("btc_usdt", "eth_usdt"):
            return {"24h_netflow": 0.0, "trend": "neutral"}

        asset = "BTC" if "BTC" in symbol else "ETH"
        url = "https://api.glassnode.com/v1/metrics/transactions/transfers_volume_exchanges_net"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    params={"a": asset, "api_key": self.glassnode_key, "i": "24h"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return {"24h_netflow": 0.0, "trend": "neutral"}
                    data = await resp.json()
                    if data:
                        netflow = data[-1].get("v", 0)
                        trend = "distribution" if netflow > CONFIG["whale_inflow_alert_btc"] else (
                            "accumulation" if netflow < -CONFIG["whale_inflow_alert_btc"] / 2 else "neutral"
                        )
                        return {"24h_netflow": netflow, "trend": trend}
        except Exception as exc:
            logger.debug("Glassnode flow fetch failed: %s", exc)
        return {"24h_netflow": 0.0, "trend": "neutral"}

    # ──────────────────────────────────────────────────────────
    # Classifiers
    # ──────────────────────────────────────────────────────────

    def _classify_signal(self, funding: float, oi: dict, flow: dict) -> str:
        flow_trend = flow.get("trend", "neutral")
        funding_ok_long = funding < CONFIG["funding_rate_long_max"]
        funding_ok_short = funding > CONFIG["funding_rate_short_max"]

        if flow_trend == "accumulation" and funding < 0 and funding_ok_long:
            return "BULLISH_STRONG"
        if flow_trend == "accumulation" and funding_ok_long:
            return "BULLISH_MODERATE"
        if flow_trend == "distribution" and funding > CONFIG["funding_rate_long_max"]:
            return "BEARISH_STRONG"
        if flow_trend == "distribution":
            return "BEARISH_MODERATE"
        if abs(funding) > 0.002:
            return "MANIPULATION"
        return "NEUTRAL"

    def _funding_bias(self, funding: float) -> str:
        if funding > 0.001:
            return "long_heavy"
        if funding < -0.0005:
            return "short_heavy"
        return "neutral"

    def _confidence(self, funding: float, oi: dict, flow: dict) -> int:
        score = 40
        if flow.get("trend") != "neutral":
            score += 30
        if abs(funding) > 0.0005:
            score += 20
        if oi.get("signal") not in ("neutral", "unknown"):
            score += 10
        return min(100, score)

    def _summarize(self, symbol: str, signal: str, funding: float, oi: dict) -> str:
        return (
            f"{symbol}: {signal}. Funding {funding*100:.4f}%. "
            f"OI {oi.get('24h_change_pct', 0):+.1f}% 24h."
        )
