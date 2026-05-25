"""
Multi-symbol async scanner.

Flow:
  1. Fetch all 632 futures tickers → filter top N by 24h volume
  2. Fetch BTC klines on all TFs → compute ICT bias
  3. For each symbol (concurrent, rate-limited):
       a. Fetch klines on 6 TFs
       b. Detect OBs per TF
       c. Find multi-TF confluent zones (≥ 3 TFs)
  4. Build signals; keep only those aligned with BTC bias
  5. Sort by OB score descending
"""

import asyncio
import time
from typing import Dict, List, Optional, Tuple

import aiohttp

from .client import AsyncBitunixClient
from .ict import (
    OrderBlock,
    ConfluentZone,
    btc_ict_bias,
    detect_order_blocks,
    find_confluence,
)
from .signals import Signal, build_signal

TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]
KLINE_LIMIT = 200          # candles per TF
TOP_N_BY_VOLUME = 150      # scan only top N symbols by 24h volume
MIN_TF_CONFLUENCE = 3      # minimum distinct TFs for a valid zone
MIN_OB_SCORE = 9           # 3 TFs minimum weighted score (e.g. 1h+4h+1d = 15)
# Accept both aligned AND neutral-BTC signals
REQUIRE_ALIGNMENT = True   # set False to include divergent signals too


async def _fetch_all_tf(client: AsyncBitunixClient, symbol: str,
                         timeframes: List[str]) -> Dict[str, list]:
    tasks = {tf: client.get_klines(symbol, tf, KLINE_LIMIT)
             for tf in timeframes}
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    return {tf: (r if not isinstance(r, Exception) else [])
            for tf, r in zip(tasks.keys(), results)}


async def _scan_symbol(client: AsyncBitunixClient,
                        symbol: str,
                        current_price: float,
                        btc_bias: str,
                        btc_detail: str) -> Optional[Signal]:
    tf_klines = await _fetch_all_tf(client, symbol, TIMEFRAMES)

    # Detect OBs on each TF
    tf_obs: Dict[str, List[OrderBlock]] = {}
    for tf, raw in tf_klines.items():
        tf_obs[tf] = detect_order_blocks(raw, tf)

    # Find confluent zones
    zones = find_confluence(tf_obs, min_tfs=MIN_TF_CONFLUENCE)
    if not zones:
        return None

    best = zones[0]          # highest score
    if best.score < MIN_OB_SCORE:
        return None

    sig = build_signal(symbol, best, current_price, btc_bias, btc_detail)

    if REQUIRE_ALIGNMENT and not sig.aligned:
        return None

    return sig


async def run_scan(api_key: str, secret_key: str,
                   top_n: int = TOP_N_BY_VOLUME,
                   progress: bool = True) -> List[Signal]:
    """
    Main entry point. Returns list of signals sorted by OB score.
    """
    async with aiohttp.ClientSession() as session:
        client = AsyncBitunixClient(api_key, secret_key, session)

        # ── Step 1: Get all tickers, sort by quote volume ─────────────────
        if progress:
            print("Fetching ticker list …", flush=True)
        tickers = await client.get_all_tickers()
        if not tickers:
            print("ERROR: could not fetch tickers.")
            return []

        # baseVol in Bitunix is the dollar volume (confusingly named)
        for t in tickers:
            try:
                t["_vol"] = float(t.get("baseVol", 0))
            except Exception:
                t["_vol"] = 0.0

        tickers_sorted = sorted(tickers, key=lambda t: t["_vol"], reverse=True)
        top_tickers = tickers_sorted[:top_n]
        price_map = {t["symbol"]: float(t["lastPrice"])
                     for t in top_tickers if t.get("lastPrice")}
        symbols = list(price_map.keys())

        if progress:
            print(f"Total symbols available : {len(tickers)}", flush=True)
            print(f"Scanning top {len(symbols)} by 24h volume …", flush=True)

        # ── Step 2: BTC ICT bias ───────────────────────────────────────────
        if progress:
            print("Analysing BTC multi-TF structure …", flush=True)
        btc_tf_klines = await _fetch_all_tf(client, "BTCUSDT",
                                             ["1h", "4h", "1d"])
        btc_bias, btc_detail = btc_ict_bias(btc_tf_klines)
        if progress:
            print(f"BTC Bias → {btc_bias.upper()}  [{btc_detail}]", flush=True)

        # ── Step 3: Scan symbols concurrently ─────────────────────────────
        if progress:
            print(f"\nScanning {len(symbols)} symbols …", flush=True)

        t0 = time.time()
        tasks = [
            _scan_symbol(client, sym, price_map[sym], btc_bias, btc_detail)
            for sym in symbols
        ]

        signals: List[Signal] = []
        done = 0
        for coro in asyncio.as_completed(tasks):
            result = await coro
            done += 1
            if result is not None:
                signals.append(result)
            if progress and done % 20 == 0:
                elapsed = time.time() - t0
                pct = done / len(symbols) * 100
                print(f"  {done}/{len(symbols)}  ({pct:.0f}%)  "
                      f"signals so far: {len(signals)}  "
                      f"[{elapsed:.1f}s]", flush=True)

        elapsed = time.time() - t0
        if progress:
            print(f"\nScan complete in {elapsed:.1f}s  "
                  f"→  {len(signals)} signal(s) found", flush=True)

        return sorted(signals, key=lambda s: s.zone.score, reverse=True)
