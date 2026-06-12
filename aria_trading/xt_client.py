"""
ARIA — XT.com API Client
All market data uses the SPOT REST API (sapi.xt.com) which is confirmed
reachable. Futures endpoints (fapi.xt.com) return 404 and are NOT used.
Funding rate / OI return neutral defaults — spot API has no equivalents.
"""

import logging
import aiohttp
from config import CONFIG

logger = logging.getLogger(__name__)

SPOT = CONFIG["xt_rest_spot"]   # https://sapi.xt.com

# Interval mapping: internal → XT.com format
_IV = {"1d":"1d","4h":"4h","1h":"1h","15m":"15m","5m":"5m","1w":"1w",
       "4H":"4h","1H":"1h","1D":"1d"}


async def _get(url: str, params: dict = None) -> dict | list | None:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status != 200:
                    logger.warning("HTTP %d: %s params=%s", r.status, url, params)
                    return None
                return await r.json()
    except Exception as exc:
        logger.warning("GET error %s: %s", url, exc)
        return None


# ──────────────────────────────────────────────────────────
# Symbol discovery  (spot — confirmed working)
# ──────────────────────────────────────────────────────────

async def fetch_all_usdt_symbols() -> list[str]:
    """
    Fetch ALL active USDT trading pairs from XT.com spot, sorted by 24h volume.

    Returns:
        List of symbols e.g. ["btc_usdt", "eth_usdt", ...]
    """
    symbols_with_vol: list[tuple[str, float]] = []
    seen: set[str] = set()

    # Step 1: spot 24h tickers — gives volume data
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SPOT}/v4/public/ticker",
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
        for t in data.get("result", []):
            sym = str(t.get("s", ""))
            if sym.endswith("_usdt"):
                vol = float(t.get("qv", 0) or 0)
                symbols_with_vol.append((sym, vol))
                seen.add(sym)
        logger.info("Spot tickers: %d USDT pairs fetched", len(seen))
    except Exception as exc:
        logger.warning("Spot ticker fetch failed: %s", exc)

    # Step 2: symbol list — catches any pair with zero recent volume
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SPOT}/v4/public/symbol",
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
        before = len(seen)
        for item in data.get("result", {}).get("symbols", []):
            sym = str(item.get("symbol", ""))
            if (sym and sym not in seen
                    and item.get("state") == "ONLINE"
                    and str(item.get("quoteCurrency", "")).lower() == "usdt"):
                symbols_with_vol.append((sym, 0.0))
                seen.add(sym)
        logger.info("Symbol list added %d more (total %d)", len(seen) - before, len(seen))
    except Exception as exc:
        logger.warning("Symbol list fetch failed: %s", exc)

    symbols_with_vol.sort(key=lambda x: x[1], reverse=True)
    symbols = [s for s, _ in symbols_with_vol]

    if not symbols:
        logger.error("ALL symbol fetches failed — falling back to 15 hardcoded symbols!")
        symbols = [
            "btc_usdt","eth_usdt","sol_usdt","bnb_usdt","xrp_usdt",
            "doge_usdt","avax_usdt","link_usdt","arb_usdt","op_usdt",
            "inj_usdt","sui_usdt","apt_usdt","aave_usdt","uni_usdt",
        ]

    logger.info("Total symbols for scanning: %d", len(symbols))
    return symbols


async def fetch_top_symbols(n: int = 9999) -> list[str]:
    """
    Return USDT symbols sorted by 24h volume.
    n=9999 (default) → ALL symbols.
    """
    all_syms = await fetch_all_usdt_symbols()
    return all_syms if n >= 9999 else all_syms[:n]


# ──────────────────────────────────────────────────────────
# Candles  (spot kline endpoint)
# ──────────────────────────────────────────────────────────

async def get_klines(symbol: str, interval: str, limit: int = 100) -> list[dict]:
    """
    Fetch OHLCV klines from XT.com spot.

    Args:
        symbol:   e.g. "btc_usdt"
        interval: e.g. "4h", "1h", "15m"
        limit:    max candles (XT spot max is 500)

    Returns:
        List of {"timestamp","open","high","low","close","volume"} dicts
    """
    iv = _IV.get(interval, interval)
    data = await _get(
        f"{SPOT}/v4/public/kline",
        {"symbol": symbol, "interval": iv, "limit": min(limit, 500)},
    )
    if not data:
        return []

    rows = []
    try:
        # Spot kline response: {"rc":0,"result":{"list":[[ts,o,h,l,c,v,qv],...]}]
        result = data.get("result", {})
        if isinstance(result, dict):
            raw = result.get("list", [])
        elif isinstance(result, list):
            raw = result
        else:
            raw = []
        for r in raw:
            rows.append({
                "timestamp": int(r[0]),
                "open":  float(r[1]),
                "high":  float(r[2]),
                "low":   float(r[3]),
                "close": float(r[4]),
                "volume":float(r[5]),
            })
    except Exception as exc:
        logger.debug("Kline parse error %s: %s", symbol, exc)
    return rows


# ──────────────────────────────────────────────────────────
# Funding rate  (futures-only → return neutral)
# ──────────────────────────────────────────────────────────

async def get_funding_rate(symbol: str) -> float:
    """
    Funding rate is futures-only. Spot API has no equivalent.
    Returns 0.0 (neutral) so funding-rate filters don't block trades.
    """
    return 0.0


# ──────────────────────────────────────────────────────────
# Open interest  (futures-only → return neutral)
# ──────────────────────────────────────────────────────────

async def get_open_interest(symbol: str) -> dict:
    """
    Open interest is futures-only. Returns neutral dict so OI checks pass.
    """
    return {"current": 0.0, "24h_change_pct": 0.0, "signal": "neutral"}


# ──────────────────────────────────────────────────────────
# Ticker / price  (spot)
# ──────────────────────────────────────────────────────────

async def get_price(symbol: str) -> float:
    """Return latest price for a symbol using spot ticker."""
    data = await _get(f"{SPOT}/v4/public/ticker", {"symbol": symbol})
    if not data:
        return 0.0
    try:
        result = data.get("result", data)
        if isinstance(result, list):
            result = result[0]
        # Spot ticker fields: "c" = last close price, "p" = price
        return float(result.get("c", result.get("p", result.get("lastPrice", 0))))
    except Exception:
        return 0.0


async def get_all_prices(symbols: list[str]) -> dict[str, float]:
    """Fetch prices for all symbols in one spot ticker call."""
    prices = {}
    data = await _get(f"{SPOT}/v4/public/ticker")
    if data:
        try:
            items = data.get("result", [])
            if isinstance(items, list):
                for item in items:
                    s = item.get("s", "")
                    if s in symbols:
                        prices[s] = float(item.get("c", item.get("p", 0)))
        except Exception:
            pass

    # Fill any missing with individual calls
    for sym in symbols:
        if sym not in prices:
            prices[sym] = await get_price(sym)
    return prices


# ──────────────────────────────────────────────────────────
# 24h volume ticker  (spot)
# ──────────────────────────────────────────────────────────

async def get_24h_ticker(symbol: str) -> dict:
    """Return 24h volume and price change from spot ticker."""
    data = await _get(f"{SPOT}/v4/public/ticker", {"symbol": symbol})
    if not data:
        return {}
    try:
        result = data.get("result", {})
        if isinstance(result, list):
            result = result[0]
        # Spot ticker: v=base volume, qv=quote volume, r/rc=price change pct, c=last price
        return {
            "volume": float(result.get("v", result.get("volume", 0))),
            "quoteVolume": float(result.get("qv", result.get("quoteVolume", 0))),
            "priceChangePercent": float(result.get("r", result.get("rc", 0))),
            "lastPrice": float(result.get("c", result.get("p", result.get("lastPrice", 0)))),
        }
    except Exception:
        return {}
