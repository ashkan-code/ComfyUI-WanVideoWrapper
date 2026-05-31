#!/usr/bin/env python3
"""
Arbitrage Scanner — Bitunix Futures
  ① مثلثی واقعی (اگه cross-pair وجود داشت)
  ② Synthetic Pairs Arb — انحراف نسبت ارزهای همبسته از میانگین

اجرا:
  python arbitrage.py          # یک اسکن
  python arbitrage.py --live   # نظارت 24/7 هر 30 ثانیه

هزینه‌ها:
  Taker fee  : 0.06% × 4 legs = 0.24% round-trip
  Spread     : از order book — fallback 0.04%
  Min profit : 0.35% بعد از همه هزینه‌ها
"""
import argparse, asyncio, os, ssl, sys, time
sys.path.insert(0, os.path.dirname(__file__))

import aiohttp
from typing import List

from bitunix_scanner.client     import AsyncBitunixClient
from bitunix_scanner.arbitrage  import (
    find_true_triangles, find_synthetic_opps,
    ArbOpp, _bar, _rank, _score,
    TAKER_FEE, MIN_NET_PROFIT,
)
from bitunix_scanner.signals import _fmt

API_KEY    = os.getenv("BITUNIX_API_KEY",    "7bee3f4756a0dbc89ae152f34c2175ac")
SECRET_KEY = os.getenv("BITUNIX_SECRET_KEY", "4e0a845778d49068297106a64cbcda61")

SCAN_INTERVAL = 30    # ثانیه بین اسکن‌ها در حالت live
TOP_N         = 8     # نمایش top N


# ── نمایش ─────────────────────────────────────────────────────────────────────

def _fmt_opp(rank: int, o: ArbOpp) -> str:
    rl   = _rank(o.score)
    icon = "🔺" if o.direction_a == "LONG" else "🔻"
    kind_label = "△ مثلثی" if o.kind == "triangle" else "⇄ Synthetic"
    a_icon = "🟢" if o.direction_a == "LONG" else "🔴"
    b_icon = "🟢" if o.direction_b == "LONG" else "🔴"

    if o.kind == "triangle":
        pair_line = (f"  مسیر  :  USDT → {o.sym_a} → {o.sym_b} → USDT\n"
                     f"  لگ‌ها  :  {o.direction_a} {o.sym_a}  ·  {o.direction_b} {o.sym_b}")
    else:
        z_arrow = "▲ بیش‌ارزش" if o.z_score > 0 else "▼ کم‌ارزش"
        pair_line = (
            f"  {a_icon} {o.direction_a:<5} {o.sym_a:<16}  @ {_fmt(o.price_a)}\n"
            f"  {b_icon} {o.direction_b:<5} {o.sym_b:<16}  @ {_fmt(o.price_b)}\n"
            f"  نسبت   :  {o.ratio_now:.6f}  (میانگین {o.ratio_mean:.6f})  z={o.z_score:+.2f}σ  {z_arrow}"
        )

    return f"""
┌{'─'*60}┐
│  🎯 #{rank:<2}  {kind_label}  {rl:<18}{'':>5}│
│  امتیاز: {o.score:>5.1f}/100  {_bar(o.score)}{'':>10}│
├{'─'*60}┤
{pair_line}
├{'─'*60}┤
│  سود ناخالص : {o.gross_profit*100:>+7.3f}%{'':>38}│
│  کارمزد     : {o.fee_cost*100:>+7.3f}%  (taker ×4 = 0.24%){'':>20}│
│  اسپرد      : {o.spread_cost*100:>+7.3f}%  (از order book){'':>22}│
│  ─────────────────────────────────────────────────────  │
│  سود خالص   : {o.net_profit*100:>+7.3f}%  ≈ {o.sim_profit:>+7.2f} USDT per 1000{'':>7}│
├{'─'*60}┤
│  {o.detail[:58]:<58}│
└{'─'*60}┘"""


def _print_summary(opps: List[ArbOpp], elapsed: float, n_sym: int):
    total = len(opps)
    print(f"\n{'═'*62}")
    print(f"  📊 Arbitrage Scan — {total} فرصت از {n_sym} ارز  [{elapsed:.1f}s]")
    print(f"{'═'*62}")
    print(f"  {'#':<4} {'نوع':<12} {'A':<16} {'B':<16} {'z':<8} {'خالص':<10} {'رتبه'}")
    print("  " + "─" * 60)
    for i, o in enumerate(opps[:TOP_N], 1):
        z_str = f"{o.z_score:+.2f}σ"
        kind = "△ مثلثی" if o.kind == "triangle" else "⇄ Synth"
        print(f"  #{i:<3} {kind:<12} {o.sym_a:<16} {o.sym_b:<16}"
              f" {z_str:<8} {o.net_profit*100:>+.3f}%   {_rank(o.score)}")
    if not opps:
        print("  هیچ فرصتی بالای آستانه پیدا نشد.")


# ── main scan ─────────────────────────────────────────────────────────────────

async def scan_once(client: AsyncBitunixClient, verbose: bool = True) -> List[ArbOpp]:
    t0      = time.time()
    tickers = await client.get_all_tickers()

    price_map = {t["symbol"]: float(t["lastPrice"])
                 for t in tickers
                 if t.get("lastPrice") and float(t.get("lastPrice", 0)) > 0}
    n_sym = len(price_map)

    # ① مثلثی واقعی
    tri = find_true_triangles(tickers)

    # ② synthetic pairs
    syn = await find_synthetic_opps(client, price_map)

    all_opps = sorted(tri + syn, key=lambda x: x.score, reverse=True)
    elapsed  = time.time() - t0

    if verbose:
        _print_summary(all_opps, elapsed, n_sym)
        for i, o in enumerate(all_opps[:TOP_N], 1):
            print(_fmt_opp(i, o))

    return all_opps


# ── entry point ───────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="نظارت 24/7")
    parser.add_argument("--interval", type=int, default=SCAN_INTERVAL)
    parser.add_argument("--min-profit", type=float, default=MIN_NET_PROFIT * 100,
                        help="حداقل سود خالص %%")
    args = parser.parse_args()

    print("""
╔══════════════════════════════════════════════════════╗
║   🔍 Arbitrage Scanner — Bitunix Futures            ║
║   ① Triangle Arb  (cross-pairs اگه وجود داشتن)    ║
║   ② Synthetic Arb (pairs همبسته — z-score)         ║
║   کارمزد: 0.06% ×4 = 0.24% | spread: live          ║
╚══════════════════════════════════════════════════════╝
""")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode    = ssl.CERT_NONE
    conn = aiohttp.TCPConnector(ssl=ssl_ctx)

    async with aiohttp.ClientSession(connector=conn) as session:
        client = AsyncBitunixClient(API_KEY, SECRET_KEY, session)

        if not args.live:
            await scan_once(client, verbose=True)
            return

        print(f"  🔄 Live mode — هر {args.interval}s اسکن  |  Ctrl+C برای خروج\n")
        cycle = 0
        while True:
            cycle += 1
            print(f"\n  ── Cycle #{cycle}  [{time.strftime('%H:%M:%S')}] ──")
            try:
                opps = await scan_once(client, verbose=True)
                if opps:
                    print(f"\n  🔔 {len(opps)} فرصت فعال — بالاترین: "
                          f"{opps[0].sym_a}+{opps[0].sym_b}  "
                          f"net={opps[0].net_profit*100:+.3f}%")
            except Exception as e:
                print(f"  ⚠️  خطا: {e}")
            await asyncio.sleep(args.interval)


if __name__ == "__main__":
    asyncio.run(main())
