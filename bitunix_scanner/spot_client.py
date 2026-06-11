"""
Bitunix Spot Client — برای اربیتاژ مثلثی از Spot Convert استفاده می‌کنه.

دو حالت:
  ① Spot API (api.bitunix.com)  — روی دستگاه کاربر کار می‌کنه
  ② Futures API (fapi.bitunix.com) — fallback اگه Spot بلاک بود

هر دو به bid/ask دسترسی دارن.
"""

import aiohttp
import asyncio
from typing import List, Optional

SPOT_BASE    = "https://api.bitunix.com"
FUTURES_BASE = "https://fapi.bitunix.com"

_SEM: Optional[asyncio.Semaphore] = None

def _sem():
    global _SEM
    if _SEM is None:
        _SEM = asyncio.Semaphore(8)
    return _SEM


class SpotClient:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self._use_futures_fallback = False

    async def _get(self, base: str, path: str, params: dict = None) -> dict:
        async with _sem():
            url = base + path
            async with self.session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                return await r.json(content_type=None)

    async def get_tickers(self) -> List[dict]:
        """
        همه پارهای Spot با bid/ask.
        اگه Spot بلاک بود → Futures fallback (فقط USDT pairs).
        """
        # ── ① Spot API ────────────────────────────────────────────────────────
        if not self._use_futures_fallback:
            for path in [
                "/api/v1/spot/market/tickers",
                "/api/v1/spot/market/ticker",
                "/api/v1/market/tickers",
                "/api/v1/spot/tickers",
            ]:
                try:
                    data = await self._get(SPOT_BASE, path)
                    if not isinstance(data, dict):
                        continue
                    result = data.get("data") or data.get("result") or []
                    if isinstance(result, list) and len(result) > 5:
                        return result
                    for val in data.values():
                        if isinstance(val, list) and len(val) > 5:
                            return val
                except Exception:
                    continue
            self._use_futures_fallback = True

        # ── ② Futures fallback ────────────────────────────────────────────────
        try:
            data = await self._get(FUTURES_BASE, "/api/v1/futures/market/tickers")
            result = data.get("data") or []
            if isinstance(result, list):
                return result
        except Exception:
            pass

        return []

    async def get_orderbook(self, symbol: str, limit: int = 5) -> dict:
        """Order book برای محاسبه bid/ask spread"""
        # Spot orderbook
        if not self._use_futures_fallback:
            for path in [
                "/api/v1/spot/market/depth",
                "/api/v1/spot/market/orderbook",
                "/api/v1/spot/depth",
            ]:
                try:
                    data = await self._get(SPOT_BASE, path, {"symbol": symbol, "limit": limit})
                    if not isinstance(data, dict):
                        continue
                    r = data.get("data") or {}
                    if r.get("bids") or r.get("asks"):
                        return r
                    if data.get("bids") or data.get("asks"):
                        return data
                except Exception:
                    continue

        # Futures orderbook fallback
        try:
            data = await self._get(FUTURES_BASE, "/api/v1/futures/market/depth",
                                   {"symbol": symbol, "limit": limit})
            return data.get("data") or {}
        except Exception:
            pass

        return {}

    async def get_convert_quote(self, from_coin: str, to_coin: str,
                                amount: float) -> dict:
        """نرخ واقعی Convert (فقط روی Spot کار می‌کنه)"""
        for path in [
            "/api/v1/spot/convert/quote",
            "/api/v1/convert/quote",
        ]:
            try:
                data = await self._get(SPOT_BASE, path, {
                    "fromCoin": from_coin,
                    "toCoin":   to_coin,
                    "fromAmount": str(amount),
                })
                if not isinstance(data, dict):
                    continue
                result = data.get("data") or data.get("result") or {}
                if result:
                    return result
            except Exception:
                continue
        return {}
