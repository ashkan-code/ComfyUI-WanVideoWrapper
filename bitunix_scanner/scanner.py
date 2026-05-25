"""
Advanced ICT scanner — top 20 by volume, single best setup.

Flow:
  1. Fetch all tickers → top 20 by 24h volume
  2. BTC HTF bias (4H/1H/1D) — skip if neutral
  3. For each symbol (concurrent):
       a. Klines on all 6 TFs
       b. OB detection + confluence (min 2 TFs)
       c. FVG detection on 1h
       d. Liquidity sweep on 15m/5m
       e. MSS/BOS on 15m/5m
       f. OTE zone check (61.8–79% Fib)
       g. Build signal; reject if SL > 1.5% or confluence < 2
  4. Select the SINGLE highest quality_score signal
"""

import asyncio
import time
from typing import List, Optional

import aiohttp

from .client import AsyncBitunixClient
from .ict import (
    OrderBlock, ConfluentZone,
    btc_ict_bias,
    detect_order_blocks,
    find_confluence,
)
from .signals import Signal, build_signal

TIMEFRAMES      = ["1m", "5m", "15m", "1h", "4h", "1d"]
KLINE_LIMIT     = 200
TOP_N_BY_VOLUME = 100
MIN_TF_CONFLUENCE = 2   # relax to 2 for top-20 focused scan
MIN_OB_SCORE    = 6     # minimum zone score


async def _fetch_all_tf(client: AsyncBitunixClient, symbol: str,
                         timeframes: List[str]) -> dict:
    tasks  = {tf: client.get_klines(symbol, tf, KLINE_LIMIT) for tf in timeframes}
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    return {tf: (r if not isinstance(r, Exception) else [])
            for tf, r in zip(tasks.keys(), results)}


async def _scan_symbol(client: AsyncBitunixClient,
                        symbol: str,
                        current_price: float,
                        btc_bias: str,
                        btc_detail: str) -> Optional[Signal]:
    tf_klines = await _fetch_all_tf(client, symbol, TIMEFRAMES)

    tf_obs = {tf: detect_order_blocks(raw, tf) for tf, raw in tf_klines.items()}
    zones  = find_confluence(tf_obs, min_tfs=MIN_TF_CONFLUENCE)
    if not zones:
        return None

    ict_dir = btc_bias  # "bullish" or "bearish"
    zone    = next((z for z in zones if z.zone_type == ict_dir and z.score >= MIN_OB_SCORE), None)
    if not zone:
        return None

    return build_signal(
        symbol, zone, current_price, btc_bias, btc_detail,
        klines_5m  = tf_klines.get("5m",  []),
        klines_15m = tf_klines.get("15m", []),
        klines_1h  = tf_klines.get("1h",  []),
        klines_4h  = tf_klines.get("4h",  []),
    )


async def run_scan(api_key: str, secret_key: str,
                   top_n: int = TOP_N_BY_VOLUME,
                   progress: bool = True) -> List[Signal]:
    """
    Returns list of valid signals sorted by quality_score descending.
    Caller should take signals[0] as the single best trade.
    """
    async with aiohttp.ClientSession() as session:
        client = AsyncBitunixClient(api_key, secret_key, session)

        if progress:
            print("Fetching ticker list …", flush=True)
        tickers = await client.get_all_tickers()
        if not tickers:
            print("ERROR: could not fetch tickers.")
            return []

        for t in tickers:
            try:
                t["_vol"] = float(t.get("baseVol", 0))
            except Exception:
                t["_vol"] = 0.0

        top_tickers = sorted(tickers, key=lambda t: t["_vol"], reverse=True)[:top_n]
        price_map   = {t["symbol"]: float(t["lastPrice"])
                       for t in top_tickers if t.get("lastPrice")}
        symbols     = list(price_map.keys())

        if progress:
            print(f"Scanning top {len(symbols)} symbols by 24h volume …", flush=True)

        # BTC HTF bias (4H / 1H / 1D) — skip if neutral
        if progress:
            print("Analysing BTC HTF structure (4H/1H/1D) …", flush=True)
        btc_tf = await _fetch_all_tf(client, "BTCUSDT", ["1h", "4h", "1d"])
        btc_bias, btc_detail = btc_ict_bias(btc_tf)
        if progress:
            print(f"BTC Bias → {btc_bias.upper()}  [{btc_detail}]", flush=True)

        if btc_bias == "neutral":
            if progress:
                print("BTC bias is NEUTRAL — no trade this cycle.", flush=True)
            return []

        if progress:
            print(f"\nScanning {len(symbols)} symbols for {btc_bias.upper()} setups …\n",
                  flush=True)

        t0    = time.time()
        tasks = [
            _scan_symbol(client, sym, price_map[sym], btc_bias, btc_detail)
            for sym in symbols
        ]

        signals: List[Signal] = []
        done = 0
        for coro in asyncio.as_completed(tasks):
            result = await coro
            done  += 1
            if result is not None:
                signals.append(result)
            if progress and done % 5 == 0:
                print(f"  {done}/{len(symbols)}  signals: {len(signals)}"
                      f"  [{time.time()-t0:.1f}s]", flush=True)

        elapsed = time.time() - t0
        if progress:
            print(f"\nScan done in {elapsed:.1f}s → {len(signals)} valid setup(s)",
                  flush=True)

        # Best single setup at the top
        return sorted(signals, key=lambda s: s.quality_score, reverse=True)
