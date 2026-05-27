#!/usr/bin/env python3
"""
تحلیل Wyckoff Spring/Upthrust — فقط نمایش، بدون معامله.
اجرا:  python wyckoff.py
"""
import asyncio, os, sys, ssl, time
import aiohttp
sys.path.insert(0, os.path.dirname(__file__))

from bitunix_scanner.client import AsyncBitunixClient
from bitunix_scanner.spring_scanner import (
    _scan_one, _format_spring, _bar, BATCH_SIZE, SHOW_TOP, kind_name
)
from bitunix_scanner.ict import btc_ict_bias

API_KEY    = os.getenv("BITUNIX_API_KEY",    "7bee3f4756a0dbc89ae152f34c2175ac")
SECRET_KEY = os.getenv("BITUNIX_SECRET_KEY", "4e0a845778d49068297106a64cbcda61")


async def main():
    print("""
╔══════════════════════════════════════════════════════╗
║   تحلیل Wyckoff Spring / Upthrust                   ║
║   همه ارزهای Bitunix — فقط نمایش، بدون معامله       ║
╚══════════════════════════════════════════════════════╝
""")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode    = ssl.CERT_NONE
    conn = aiohttp.TCPConnector(ssl=ssl_ctx)

    async with aiohttp.ClientSession(connector=conn) as session:
        client = AsyncBitunixClient(API_KEY, SECRET_KEY, session)

        # BTC bias
        print("  📊 تحلیل BTC …", flush=True)
        btc_tf = {tf: await client.get_klines("BTCUSDT", tf, 100)
                  for tf in ("4h", "1h", "1d")}
        btc_bias, btc_detail = btc_ict_bias(btc_tf)

        bias_icon = "🟢" if btc_bias=="bullish" else ("🔴" if btc_bias=="bearish" else "🟡")
        print(f"  {bias_icon} BTC → {btc_bias.upper()}")
        print(f"     {btc_detail}\n")

        if btc_bias == "neutral":
            print("  🟡 BTC بی‌تصمیمه — فنر در هر دو جهت اسکن میشه\n")
            dirs = [("LONG", "bullish"), ("SHORT", "bearish")]
        else:
            direction = "LONG" if btc_bias == "bullish" else "SHORT"
            ict_dir   = "bullish" if direction == "LONG" else "bearish"
            dirs      = [(direction, ict_dir)]

        # همه ارزها
        tickers = await client.get_all_tickers()
        for t in tickers:
            try: t["_vol"] = float(t.get("baseVol", 0))
            except: t["_vol"] = 0.0

        price_map = {t["symbol"]: float(t["lastPrice"])
                     for t in tickers
                     if t.get("lastPrice") and float(t.get("lastPrice", 0)) > 0}
        symbols = list(price_map.keys())
        print(f"  🔍 اسکن {len(symbols)} ارز …\n", flush=True)

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
                print(f"  {done}/{len(symbols)}  یافته: {len(found)}"
                      f"  [{time.time()-t0:.0f}s]", flush=True)

        elapsed = time.time() - t0
        print(f"\n{'═'*56}")
        print(f"  اسکن تموم شد  ─  {len(found)} فنر از {len(symbols)} ارز  [{elapsed:.0f}s]")
        print(f"{'═'*56}\n")

        if not found:
            print("  هیچ فنری پیدا نشد.\n")
            return

        found.sort(key=lambda s: s.score, reverse=True)

        print(f"\n{'═'*60}")
        print(f"  نتایج  ─  {len(found)} فنر معتبر از {len(symbols)} ارز")
        print(f"{'═'*60}")
        print(f"  {'#':<4} {'ارز':<16} {'جهت':<7} {'TF':<5} {'امتیاز':<10}"
              f" {'RRR':<7} {'SL%':<7} {'TP%':<8} {'Pierce'}")
        print("  " + "─"*65)
        for i, s in enumerate(found, 1):
            tp_pct  = (s.tp - s.entry) / s.entry * 100
            pierce  = s.detail.get("pierce", 0)
            marker  = "  ← 🔥" if s.score >= 70 else ("  ← ✅" if s.score >= 55 else "")
            print(f"  #{i:<3} {s.symbol:<16} {s.direction:<7} {s.tf:<5}"
                  f" {s.score:>5.0f}/100  1:{s.rr:.1f}   {s.loss_pct:.1f}%   "
                  f"{tp_pct:+.1f}%   {pierce:.2f}%{marker}")

        print(f"\n{'═'*60}")
        print(f"  تحلیل کامل top {min(SHOW_TOP, len(found))}:")
        print(f"{'═'*60}\n")

        for rank, sig in enumerate(found[:SHOW_TOP], 1):
            print(_format_spring(rank, sig))

        print(f"\n  برای معامله (با تأیید دستی):")
        print(f"  python -m bitunix_scanner.main --live --poll 30\n")


if __name__ == "__main__":
    asyncio.run(main())
