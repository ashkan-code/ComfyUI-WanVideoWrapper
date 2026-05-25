"""Async Bitunix REST client with rate-limiting."""

import asyncio
import hashlib
import json
import time
import uuid
from typing import Dict, List, Optional

import aiohttp

BASE_URL = "https://fapi.bitunix.com"
# keep well under 10 req/sec/IP limit
_SEMAPHORE: Optional[asyncio.Semaphore] = None


def _get_semaphore() -> asyncio.Semaphore:
    global _SEMAPHORE
    if _SEMAPHORE is None:
        _SEMAPHORE = asyncio.Semaphore(8)
    return _SEMAPHORE


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _make_headers(api_key: str, secret_key: str,
                  query_str: str = "", body_str: str = "") -> dict:
    nonce = uuid.uuid4().hex
    ts = str(int(time.time() * 1000))
    digest = _sha256(nonce + ts + api_key + query_str + body_str)
    sign = _sha256(digest + secret_key)
    return {
        "api-key": api_key,
        "nonce": nonce,
        "timestamp": ts,
        "sign": sign,
        "Content-Type": "application/json",
    }


def _sort_params(params: dict) -> str:
    """Produce sorted concatenated key-value string for signing."""
    return "".join(f"{k}{v}" for k, v in sorted(params.items()))


class AsyncBitunixClient:
    def __init__(self, api_key: str, secret_key: str,
                 session: Optional[aiohttp.ClientSession] = None):
        self.api_key = api_key
        self.secret_key = secret_key
        self._session = session
        self._owned = session is None

    async def __aenter__(self):
        if self._owned:
            self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *_):
        if self._owned and self._session:
            await self._session.close()

    async def _get_public(self, path: str, params: dict = None) -> dict:
        sem = _get_semaphore()
        async with sem:
            url = BASE_URL + path
            async with self._session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as r:
                return await r.json(content_type=None)

    async def _get_private(self, path: str, params: dict = None) -> dict:
        params = params or {}
        qs = _sort_params(params)
        headers = _make_headers(self.api_key, self.secret_key, qs, "")
        sem = _get_semaphore()
        async with sem:
            url = BASE_URL + path
            async with self._session.get(url, headers=headers, params=params,
                                          timeout=aiohttp.ClientTimeout(total=15)) as r:
                return await r.json(content_type=None)

    # ── Public endpoints ───────────────────────────────────────────────────

    async def get_all_tickers(self) -> List[dict]:
        data = await self._get_public("/api/v1/futures/market/tickers")
        return data.get("data") or []

    async def get_klines(self, symbol: str, interval: str,
                         limit: int = 200) -> List[dict]:
        data = await self._get_public("/api/v1/futures/market/kline", {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        })
        return data.get("data") or []

    # ── Private endpoints ──────────────────────────────────────────────────

    async def get_account(self, margin_coin: str = "USDT") -> dict:
        data = await self._get_private("/api/v1/futures/account",
                                        {"marginCoin": margin_coin})
        return data.get("data") or {}

    async def get_positions(self) -> List[dict]:
        data = await self._get_private(
            "/api/v1/futures/position/get_pending_positions")
        return data.get("data") or []

    async def _post(self, path: str, body: dict = None) -> dict:
        body_str = json.dumps(body, separators=(",", ":")) if body else ""
        headers = _make_headers(self.api_key, self.secret_key, "", body_str)
        sem = _get_semaphore()
        async with sem:
            url = BASE_URL + path
            async with self._session.post(url, headers=headers, data=body_str,
                                           timeout=aiohttp.ClientTimeout(total=15)) as r:
                return await r.json(content_type=None)

    async def cancel_orders(self, symbol: str, order_ids: List[str]) -> dict:
        return await self._post("/api/v1/futures/trade/cancel_orders",
                                {"symbol": symbol, "orderIds": order_ids})
