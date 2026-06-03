#!/usr/bin/env python3
"""
Wyckoff Spring / Upthrust Scanner -- all Bitunix symbols.
Display only. NO orders.

Run:  python wyckoff.py
"""
import asyncio, os, sys, ssl, time
import aiohttp
sys.path.insert(0, os.path.dirname(__file__))

from bitunix_scanner.client import AsyncBitunixClient
from bitunix_scanner.spring_scanner import (
    _scan_one, _format_spring, _bar, BATCH_SIZE, SHOW_TOP, kind_name
)
from bitunix_scanner.ict import btc_ict_bias

API_KEY    = os.getenv("BITUNIX_API_KEY",    "68f0a1765f124bacb847afa8db78e480")
SECRET_KEY = os.getenv("BITUNIX_SECRET_KEY", "159808597389a1cd1fc429f9f469209b")


async def main():
    print("""
+====================================================+
|   Wyckoff Spring / Upthrust Scanner                |
|   All Bitunix symbols -- display only, no orders   |
+====================================================+
""")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode    = ssl.CERT_NONE
    conn = aiohttp.TCPConnector(ssl=ssl_ctx)

    async with aiohttp.ClientSession(connector=conn) as session:
        client = AsyncBitunixClient(API_KEY, SECRET_KEY, session)

        print("  BTC analysis ...", flush=True)
        btc_tf = {tf: await client.get_klines("BTCUSDT", tf, 100)
                  for tf in ("4h", "1h", "1d")}
        btc_bias, btc_detail = btc_ict_bias(btc_tf)

        bias_tag = "BULL" if btc_bias == "bullish" else ("BEAR" if btc_bias == "bearish" else "NEUT")
        print(f"  BTC -> {bias_tag}")
        print(f"     {btc_detail}\n")

        if btc_bias == "neutral":
            print("  BTC neutral -- scanning both directions\n")
            dirs = [("LONG", "bullish"), ("SHORT", "bearish")]
        else:
            direction = "LONG" if btc_bias == "bullish" else "SHORT"
            ict_dir   = "bullish" if direction == "LONG" else "bearish"
            dirs      = [(direction, ict_dir)]

        tickers = await client.get_all_tickers()
        for t in tickers:
            try: t["_vol"] = float(t.get("baseVol", 0))
            except: t["_vol"] = 0.0

        price_map = {t["symbol"]: float(t["lastPrice"])
                     for t in tickers
                     if t.get("lastPrice") and float(t.get("lastPrice", 0)) > 0}
        symbols = list(price_map.keys())
        print(f"  Scanning {len(symbols)} symbols ...\n", flush=True)

        t0    = time.time()
        found = []

        for direction, ict_dir in dirs:
            for i in range(0, len(symbols), BATCH_SIZE):
                batch   = symbols[i: i + BATCH_SIZE]
                tasks   = [_scan_one(client, sym, price_map[sym],
                                     btc_bias, btc_detail, direction, ict_dir)
                           for sym in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for r in results:
                    if hasattr(r, "symbol"):
                        found.append(r)
                done = i + len(batch)
                print(f"  {done}/{len(symbols)}  found: {len(found)}"
                      f"  [{time.time()-t0:.0f}s]", flush=True)

        elapsed = time.time() - t0
        print(f"\n{'='*56}")
        print(f"  Done -- {len(found)} springs from {len(symbols)} symbols  [{elapsed:.0f}s]")
        print(f"{'='*56}\n")

        if not found:
            print("  No spring found.\n")
            return

        found.sort(key=lambda s: s.score, reverse=True)

        print(f"\n{'='*60}")
        print(f"  Results -- {len(found)} valid springs from {len(symbols)} symbols")
        print(f"{'='*60}")
        print(f"  {'#':<4} {'symbol':<16} {'dir':<7} {'TF':<5} {'score':<10}"
              f" {'RRR':<7} {'SL%':<7} {'TP%':<8} {'Pierce'}")
        print("  " + "-"*65)
        for i, s in enumerate(found, 1):
            tp_pct  = (s.tp - s.entry) / s.entry * 100
            pierce  = s.detail.get("pierce", 0)
            marker  = "  <- TOP" if s.score >= 70 else ("  <- OK" if s.score >= 55 else "")
            print(f"  #{i:<3} {s.symbol:<16} {s.direction:<7} {s.tf:<5}"
                  f" {s.score:>5.0f}/100  1:{s.rr:.1f}   {s.loss_pct:.1f}%   "
                  f"{tp_pct:+.1f}%   {pierce:.2f}%{marker}")

        print(f"\n{'='*60}")
        print(f"  Full analysis top {min(SHOW_TOP, len(found))}:")
        print(f"{'='*60}\n")

        for rank, sig in enumerate(found[:SHOW_TOP], 1):
            print(_format_spring(rank, sig))

        print(f"\n  Display only -- no orders placed.\n")


if __name__ == "__main__":
    asyncio.run(main())
