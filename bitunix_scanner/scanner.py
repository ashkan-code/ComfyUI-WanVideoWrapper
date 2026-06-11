"""
Advanced ICT scanner — top 100 by volume, single best setup.

BTC Multi-TF bias logic:
  • BTC bullish  → scan LONG setups only
  • BTC bearish  → scan SHORT setups only
  • BTC neutral  → scan BOTH directions, pick highest quality

Flow:
  1. Fetch all tickers → top N by 24h volume
  2. BTC HTF bias (Daily/4H/1H) — determine direction
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
    _parse_klines,
    btc_ict_bias,
    detect_order_blocks,
    find_confluence,
    find_impulse_for_ote,
    find_ote_zone,
)
from .signals import Signal, build_signal

TIMEFRAMES        = ["1m", "5m", "15m", "1h", "4h", "1d"]
KLINE_LIMIT       = 200
TOP_N_BY_VOLUME   = 100
MIN_TF_CONFLUENCE = 2       # absolute min TFs overlapping
MIN_OB_SCORE      = 6       # min confluence score (TF weights summed)
HTF_REQUIRED      = {"4h", "1h"}   # zone MUST include at least one of these
OTE_MAX_DIST_PCT  = 0.03    # skip if price more than 3% away from OTE midpoint


async def _fetch_all_tf(client: AsyncBitunixClient, symbol: str,
                         timeframes: List[str]) -> dict:
    tasks   = {tf: client.get_klines(symbol, tf, KLINE_LIMIT) for tf in timeframes}
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

    # Determine which directions to try based on BTC bias
    # IMPORTANT: No trading when BTC is neutral — choppy market = 50/50 = losses
    if btc_bias == "bullish":
        directions = ["bullish"]
    elif btc_bias == "bearish":
        directions = ["bearish"]
    else:
        return None   # BTC بی‌تصمیمه → هیچ معامله‌ای نمی‌زنیم

    raw4h = tf_klines.get("4h", [])
    raw1h = tf_klines.get("1h", [])

    # ── Premium / Discount of 4H range ───────────────────────────────────
    # ICT: only LONG in discount (<50% of 60-bar range), SHORT in premium (>50%)
    pd_ok = {"bullish": True, "bearish": True}
    if raw4h:
        kl4 = _parse_klines(raw4h)
        if kl4:
            recent = kl4[-60:] if len(kl4) >= 60 else kl4
            rng_hi = max(k["high"] for k in recent)
            rng_lo = min(k["low"]  for k in recent)
            equil  = (rng_hi + rng_lo) / 2
            pd_ok["bullish"] = current_price <= equil     # discount = LONG ok
            pd_ok["bearish"] = current_price >= equil     # premium  = SHORT ok

    best: Optional[Signal] = None
    for ict_dir in directions:

        # Premium/discount filter — skip unfavorable side
        if not pd_ok.get(ict_dir, True):
            continue

        # Must have a zone that includes at least one HTF (4H or 1H)
        zone = next(
            (z for z in zones
             if z.zone_type == ict_dir
             and z.score >= MIN_OB_SCORE
             and any(tf in HTF_REQUIRED for tf in z.timeframes)),
            None
        )
        if not zone:
            continue

        # OTE proximity — skip if price too far from OTE zone midpoint
        ref_ote = raw1h or tf_klines.get("15m", [])
        if ref_ote:
            sw_lo, sw_hi = find_impulse_for_ote(ref_ote, ict_dir)
            ote_lo, ote_hi = find_ote_zone(sw_lo, sw_hi, ict_dir)
            ote_mid = (ote_lo + ote_hi) / 2
            if ote_mid > 0:
                dist = abs(current_price - ote_mid) / current_price
                if dist > OTE_MAX_DIST_PCT:
                    continue

        sig = build_signal(
            symbol, zone, current_price, btc_bias, btc_detail,
            klines_5m  = tf_klines.get("5m",  []),
            klines_15m = tf_klines.get("15m", []),
            klines_1h  = raw1h,
            klines_4h  = raw4h,
        )
        if sig is None:
            continue
        if best is None or sig.quality_score > best.quality_score:
            best = sig

    return best


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

        # BTC HTF bias — Daily / 4H / 1H
        if progress:
            print("Analysing BTC HTF structure (Daily/4H/1H) …", flush=True)
        btc_tf = await _fetch_all_tf(client, "BTCUSDT", ["1h", "4h", "1d"])
        btc_bias, btc_detail = btc_ict_bias(btc_tf)

        # Direction label for display
        if btc_bias == "neutral":
            dir_label = "SKIP — BTC بی‌تصمیمه"
        elif btc_bias == "bullish":
            dir_label = "LONG only  (BTC bullish — discount zones)"
        else:
            dir_label = "SHORT only  (BTC bearish — premium zones)"

        if progress:
            bias_icon = "🟢" if btc_bias == "bullish" else ("🔴" if btc_bias == "bearish" else "🟡")
            print(f"\n  {bias_icon} BTC → {btc_bias.upper()}", flush=True)
            print(f"     {btc_detail}", flush=True)
            if btc_bias == "neutral":
                print(f"\n  ⏸️  BTC جهت واضحی نداره — این سایکل skip میشه\n", flush=True)
            else:
                print(f"\n  → Scanning {len(symbols)} symbols | {dir_label}", flush=True)
                print(f"     Filters: HTF OB (4H/1H) + Premium/Discount + OTE ±3%\n", flush=True)

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
            if progress and done % 10 == 0:
                print(f"  {done}/{len(symbols)}  signals: {len(signals)}"
                      f"  [{time.time()-t0:.1f}s]", flush=True)

        elapsed = time.time() - t0
        if progress:
            longs  = sum(1 for s in signals if s.direction == "LONG")
            shorts = sum(1 for s in signals if s.direction == "SHORT")
            print(f"\nScan done in {elapsed:.1f}s → {len(signals)} valid setup(s)"
                  f"  (LONG: {longs}  SHORT: {shorts})", flush=True)

        return sorted(signals, key=lambda s: s.quality_score, reverse=True)
