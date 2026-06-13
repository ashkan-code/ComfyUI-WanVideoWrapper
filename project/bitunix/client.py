"""Bitunix public REST API client — no auth required."""

from __future__ import annotations

import logging
import httpx
import pandas as pd

logger = logging.getLogger(__name__)

_BASE = "https://fapi.bitunix.com/api/v1/futures"
_TIMEOUT = 15.0

# Bitunix interval strings
_INTERVAL_MAP = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h", "12h": "12h",
    "1d": "1d", "1w": "1w",
}


def _to_symbol(sym: str) -> str:
    """btc_usdt -> BTCUSDT"""
    return sym.upper().replace("_", "")


async def _get(path: str, params: dict) -> dict:
    url = f"{_BASE}{path}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url, params=params,
                                headers={"Content-Type": "application/json"})
        resp.raise_for_status()
        return resp.json()


async def get_kline(symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
    """Return OHLCV DataFrame from Bitunix kline endpoint."""
    bsym = _to_symbol(symbol)
    bint = _INTERVAL_MAP.get(interval, "1h")
    data = await _get("/market/kline", {"symbol": bsym, "interval": bint, "limit": limit})

    # response: {"code":0, "data": {"list": [{...}]}}
    code = data.get("code", -1)
    if code != 0:
        raise RuntimeError(f"Bitunix error {code}: {data.get('msg', data)}")

    rows = data.get("data", {})
    if isinstance(rows, dict):
        rows = rows.get("list", rows.get("klines", rows.get("data", [])))
    if not rows:
        raise RuntimeError(f"No kline data for {bsym}")

    records = []
    for bar in rows:
        if isinstance(bar, list):
            # [time, open, high, low, close, volume]
            records.append({
                "open_time": int(bar[0]),
                "open":   float(bar[1]),
                "high":   float(bar[2]),
                "low":    float(bar[3]),
                "close":  float(bar[4]),
                "volume": float(bar[5]),
            })
        else:
            records.append({
                "open_time": int(bar.get("time", bar.get("t", 0))),
                "open":   float(bar.get("open",  bar.get("o", 0))),
                "high":   float(bar.get("high",  bar.get("h", 0))),
                "low":    float(bar.get("low",   bar.get("l", 0))),
                "close":  float(bar.get("close", bar.get("c", 0))),
                "volume": float(bar.get("volume",bar.get("v", 0))),
            })

    df = pd.DataFrame(records)
    if not df.empty:
        df = df.sort_values("open_time").reset_index(drop=True)
    return df


async def get_symbols(limit: int = 200) -> list[str]:
    """Return list of USDT-margined symbol names in btc_usdt format."""
    try:
        data = await _get("/market/trading_pairs", {})
        code = data.get("code", -1)
        if code != 0:
            raise RuntimeError(f"Bitunix error {code}: {data.get('msg', data)}")
        pairs = data.get("data", [])
        if isinstance(pairs, dict):
            pairs = pairs.get("list", pairs.get("data", []))
        syms = []
        for p in pairs:
            sym = p.get("symbol", p.get("pair", "")) if isinstance(p, dict) else str(p)
            if sym.upper().endswith("USDT"):
                syms.append(sym.upper().replace("USDT", "_usdt").lower())
        return syms[:limit]
    except Exception as exc:
        logger.warning("get_symbols failed: %s", exc)
        return []


async def get_ticker(symbol: str) -> dict:
    """Return ticker dict with 'last' price."""
    bsym = _to_symbol(symbol)
    data = await _get("/market/tickers", {"symbols": bsym})
    code = data.get("code", -1)
    if code != 0:
        raise RuntimeError(f"Bitunix error {code}: {data.get('msg', data)}")
    tickers = data.get("data", [])
    if isinstance(tickers, dict):
        tickers = tickers.get("list", [tickers])
    if not tickers:
        return {"last": 0.0}
    t = tickers[0]
    return {
        "last":   float(t.get("lastPrice", t.get("last", t.get("close", 0)))),
        "volume": float(t.get("volume24h", t.get("volume", 0))),
        "change": float(t.get("priceChange24h", t.get("change", 0))),
    }
