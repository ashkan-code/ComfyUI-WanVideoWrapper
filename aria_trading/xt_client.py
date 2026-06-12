"""
ARIA — XT.com API Client
Handles all REST calls to XT.com spot and futures endpoints.
"""

import logging
import aiohttp
from config import CONFIG

logger = logging.getLogger(__name__)

SPOT    = CONFIG["xt_rest_spot"]
FUTURES = CONFIG["xt_rest_futures"]

# Interval mapping: internal → XT.com format
_IV = {"1d":"1d","4h":"4h","1h":"1h","15m":"15m","5m":"5m","1w":"1w","4H":"4h","1H":"1h","1D":"1d"}


async def _get(url: str, params: dict = None) -> dict | list | None:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    logger.debug("HTTP %d: %s", r.status, url)
                    return None
                return await r.json()
    except Exception as exc:
        logger.debug("GET error %s: %s", url, exc)
        return None


# ──────────────────────────────────────────────────────────
# Symbol discovery
# ──────────────────────────────────────────────────────────

async def fetch_all_usdt_symbols() -> list[str]:
    """
    Fetch ALL active USDT trading pairs from XT.com, sorted by 24h volume.

    Strategy (mirrors xt_scanner which is confirmed working):
      1. GET /v4/public/ticker  → spot 24h tickers with volume, field 's'
      2. GET /v4/public/symbol  → full symbol list for any pair with zero volume

    Returns:
        Full list of symbols e.g. ["btc_usdt", "eth_usdt", ...]
    """
    symbols_with_vol: list[tuple[str, float]] = []
    seen: set[str] = set()

    # ── Step 1: Spot 24h tickers (confirmed format: result=[{"s":"btc_usdt","qv":"..."}])
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SPOT}/v4/public/ticker",
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
        tickers = data.get("result", [])
        if isinstance(tickers, list):
            for t in tickers:
                sym = str(t.get("s", ""))
                if sym.endswith("_usdt"):
                    vol = float(t.get("qv", 0) or 0)
                    symbols_with_vol.append((sym, vol))
                    seen.add(sym)
        logger.info("Spot tickers: %d USDT pairs", len(seen))
    except Exception as exc:
        logger.warning("Spot ticker fetch failed: %s", exc)

    # ── Step 2: Full symbol list for any pair missing from tickers
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
            state = str(item.get("state", ""))
            quote = str(item.get("quoteCurrency", "")).lower()
            if sym and sym not in seen and state == "ONLINE" and quote == "usdt":
                symbols_with_vol.append((sym, 0.0))
                seen.add(sym)
        logger.info("Symbol list added %d more pairs (total %d)", len(seen) - before, len(seen))
    except Exception as exc:
        logger.warning("Spot symbol list fetch failed: %s", exc)

    # Sort by volume descending
    symbols_with_vol.sort(key=lambda x: x[1], reverse=True)
    symbols = [s for s, _ in symbols_with_vol]

    if not symbols:
        logger.error("All symbol fetches failed — using 15-symbol hardcoded fallback!")
        symbols = [
            "btc_usdt","eth_usdt","sol_usdt","bnb_usdt","xrp_usdt",
            "doge_usdt","avax_usdt","link_usdt","arb_usdt","op_usdt",
            "inj_usdt","sui_usdt","apt_usdt","aave_usdt","uni_usdt",
        ]

    logger.info("Total symbols for scanning: %d", len(symbols))
    return symbols


async def fetch_top_symbols(n: int = 9999) -> list[str]:
    """
    Fetch USDT symbols from XT.com sorted by 24h quote volume.
    n=9999 (default) returns ALL available symbols.

    Returns:
        List of symbols in XT format e.g. ["btc_usdt", "eth_usdt", ...]
    """
    all_syms = await fetch_all_usdt_symbols()
    return all_syms if n >= 9999 else all_syms[:n]


# ──────────────────────────────────────────────────────────
# Candles  (XT futures)
# ──────────────────────────────────────────────────────────

async def get_klines(symbol: str, interval: str, limit: int = 100) -> list[dict]:
    """
    Fetch OHLCV klines from XT.com futures.

    Args:
        symbol:   e.g. "btc_usdt"
        interval: e.g. "4h", "1h", "15m"
        limit:    max candles

    Returns:
        List of {"timestamp","open","high","low","close","volume"} dicts
    """
    iv = _IV.get(interval, interval)
    data = await _get(
        f"{FUTURES}/future/market/v2/public/q/kline",
        {"symbol": symbol, "interval": iv, "limit": limit},
    )
    if not data:
        return []

    # XT kline response: {"returnCode":0,"result":{"list":[[ts,o,h,l,c,v,...]]}}
    rows = []
    try:
        raw = data.get("result", {}).get("list", data if isinstance(data, list) else [])
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
# Funding rate
# ──────────────────────────────────────────────────────────

async def get_funding_rate(symbol: str) -> float:
    """Return current perpetual funding rate (e.g. 0.0001 = 0.01%)."""
    data = await _get(
        f"{FUTURES}/future/market/v2/public/q/funding-rate",
        {"symbol": symbol},
    )
    if not data:
        return 0.0
    try:
        result = data.get("result", data)
        if isinstance(result, list):
            return float(result[-1].get("fundingRate", 0))
        return float(result.get("fundingRate", 0))
    except Exception:
        return 0.0


# ──────────────────────────────────────────────────────────
# Open interest
# ──────────────────────────────────────────────────────────

async def get_open_interest(symbol: str) -> dict:
    """Return open interest dict."""
    data = await _get(
        f"{FUTURES}/future/market/v2/public/q/open-interest",
        {"symbol": symbol},
    )
    if not data:
        return {"current": 0.0, "24h_change_pct": 0.0, "signal": "unknown"}
    try:
        result = data.get("result", {})
        oi = float(result.get("openInterest", 0))
        return {"current": oi, "24h_change_pct": 0.0, "signal": "neutral"}
    except Exception:
        return {"current": 0.0, "24h_change_pct": 0.0, "signal": "unknown"}


# ──────────────────────────────────────────────────────────
# Ticker / price
# ──────────────────────────────────────────────────────────

async def get_price(symbol: str) -> float:
    """Return latest mark/last price for a symbol."""
    data = await _get(
        f"{FUTURES}/future/market/v2/public/q/ticker",
        {"symbol": symbol},
    )
    if not data:
        # Fallback to spot
        data = await _get(
            f"{SPOT}/v4/public/ticker/price",
            {"symbol": symbol},
        )
    if not data:
        return 0.0
    try:
        result = data.get("result", data)
        if isinstance(result, list):
            result = result[0]
        return float(result.get("lastPrice", result.get("p", 0)))
    except Exception:
        return 0.0


async def get_all_prices(symbols: list[str]) -> dict[str, float]:
    """Fetch prices for multiple symbols in one call if possible."""
    prices = {}
    data = await _get(f"{FUTURES}/future/market/v2/public/q/ticker")
    if data:
        try:
            items = data.get("result", [])
            if isinstance(items, list):
                for item in items:
                    s = item.get("symbol", "")
                    if s in symbols:
                        prices[s] = float(item.get("lastPrice", 0))
        except Exception:
            pass

    # Fill missing with individual calls
    for sym in symbols:
        if sym not in prices:
            prices[sym] = await get_price(sym)
    return prices


# ──────────────────────────────────────────────────────────
# 24h volume ticker (for GemHunter)
# ──────────────────────────────────────────────────────────

async def get_24h_ticker(symbol: str) -> dict:
    """Return 24h volume and price change for a symbol."""
    data = await _get(
        f"{FUTURES}/future/market/v2/public/q/ticker",
        {"symbol": symbol},
    )
    if not data:
        return {}
    try:
        result = data.get("result", {})
        if isinstance(result, list):
            result = result[0]
        return {
            "volume": float(result.get("volume", 0)),
            "quoteVolume": float(result.get("quoteVolume", result.get("qv", 0))),
            "priceChangePercent": float(result.get("priceChangePercent", result.get("rc", 0))),
            "lastPrice": float(result.get("lastPrice", 0)),
        }
    except Exception:
        return {}
