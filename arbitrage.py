#!/usr/bin/env python3
"""
Arbitrage Scanner — Bitunix Futures
اجرا:
  python arbitrage.py           # یک اسکن
  python arbitrage.py --live    # نظارت 24/7
"""
import argparse, asyncio, os, ssl, sys, time
sys.path.insert(0, os.path.dirname(__file__))

import aiohttp
from typing import List

from bitunix_scanner.client    import AsyncBitunixClient
from bitunix_scanner.arbitrage import (
    scan, ArbOpp, _bar, _rank, ROUND_TRIP_FEES, TOP_SYMBOLS
)
from bitunix_scanner.signals import _fmt

API_KEY    = os.getenv("BITUNIX_API_KEY",    "7bee3f4756a0dbc89ae152f34c2175ac")
SECRET_KEY = os.getenv("BITUNIX_SECRET_KEY", "4e0a845778d49068297106a64cbcda61")

SCAN_INTERVAL = 30
SHOW_TOP      = 10


# ── نمایش ─────────────────────────────────────────────────────────────────────

def _fmt_opp(rank: int, o: ArbOpp) -> str:
    rl     = _rank(o.score)
    a_ico  = "🟢" if o.direction_a == "LONG" else "🔴"
    b_ico  = "🟢" if o.direction_b == "LONG" else "🔴"
    z_lbl  = "▲ بیش‌ارزش" if o.z_score > 0 else "▼ کم‌ارزش"

    return f"""
┌{'─'*60}┐
│  🎯 #{rank:<2}  {rl:<22}  امتیاز: {o.score:>5.1f}/100  {'':>4}│
│  {_bar(o.score):<14}  corr={o.corr:.2f}  z={o.z_score:+.2f}σ  {z_lbl:<14}  │
├{'─'*60}┤
│  {a_ico} {o.direction_a:<5} {o.sym_a:<16}  @ {_fmt(o.price_a):<16}  │
│  {b_ico} {o.direction_b:<5} {o.sym_b:<16}  @ {_fmt(o.price_b):<16}  │
│  نسبت  : {o.ratio_now:.6f}  میانگین: {o.ratio_mean:.6f}  انحراف: {o.diverge_pct:.2f}%  │
├{'─'*60}┤
│  ناخالص     : {o.gross*100:>+7.3f}%  {'':>37}│
│  کارمزد ×4  : {o.fee_cost*100:>+7.3f}%  (taker 0.06% × 4 لگ)  {'':>20}│
│  اسپرد      : {o.spread_cost*100:>+7.3f}%  {'':>37}│
│  ────────────────────────────────────────────────────  │
│  خالص       : {o.net*100:>+7.3f}%  ≈ {o.sim_usdt:>+7.2f} USDT / 1000 {'':>10}│
└{'─'*60}┘"""


def _summary(opps: List[ArbOpp], elapsed: float, n_sym: int):
    print(f"\n{'═'*62}")
    print(f"  📊 {len(opps)} فرصت از {n_sym} ارز  [{elapsed:.1f}s]")
    if not opps:
        print(f"  هیچ فرصتی بالای آستانه نبود — بازار هم‌جهته")
        print(f"{'═'*62}")
        return
    print(f"{'═'*62}")
    print(f"  {'#':<4} {'A':<16} {'جهت':<7} {'B':<16} {'جهت':<7} {'z':<8} {'خالص':<10} {'رتبه'}")
    print("  " + "─" * 60)
    for i, o in enumerate(opps[:SHOW_TOP], 1):
        print(f"  #{i:<3} {o.sym_a:<16} {o.direction_a:<7} {o.sym_b:<16} "
              f"{o.direction_b:<7} {o.z_score:>+.2f}σ  {o.net*100:>+.3f}%  {_rank(o.score)}")


# ── main ──────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live",     action="store_true")
    parser.add_argument("--interval", type=int, default=SCAN_INTERVAL)
    args = parser.parse_args()

    print(f"""
╔══════════════════════════════════════════════════════╗
║   💹 Arbitrage Scanner — Bitunix Futures            ║
║   top {TOP_SYMBOLS} ارز → همه جفت‌ها → corr + z-score      ║
║   کارمزد: 0.06%×4=0.24%  |  اسپرد: live depth      ║
║   آستانه: corr≥0.60  |z|≥1.5σ  |  net≥0.15%        ║
╚══════════════════════════════════════════════════════╝
""")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode    = ssl.CERT_NONE
    conn = aiohttp.TCPConnector(ssl=ssl_ctx)

    async with aiohttp.ClientSession(connector=conn) as session:
        client = AsyncBitunixClient(API_KEY, SECRET_KEY, session)

        async def _one_scan():
            t0   = time.time()
            print(f"  [{time.strftime('%H:%M:%S')}] 🔍 اسکن {TOP_SYMBOLS} ارز …", flush=True)
            opps = await scan(client)
            elapsed = time.time() - t0
            _summary(opps, elapsed, TOP_SYMBOLS)
            for i, o in enumerate(opps[:SHOW_TOP], 1):
                print(_fmt_opp(i, o))
            return opps

        if not args.live:
            await _one_scan()
            return

        print(f"  🔄 Live — هر {args.interval}s  |  Ctrl+C خروج\n")
        cycle = 0
        while True:
            cycle += 1
            try:
                opps = await _one_scan()
                if opps:
                    best = opps[0]
                    print(f"\n  🔔 بهترین: {best.sym_a}+{best.sym_b}"
                          f"  net={best.net*100:+.3f}%  score={best.score:.0f}")
            except Exception as e:
                print(f"  ⚠️  خطا: {e}")
            await asyncio.sleep(args.interval)


if __name__ == "__main__":
    asyncio.run(main())
