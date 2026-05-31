#!/usr/bin/env python3
"""
True Triangular Arbitrage — Bitunix Spot Convert
چرخه: USDT → A → B → USDT

اجرا:
  python triangle_arb.py           # یک اسکن
  python triangle_arb.py --live    # نظارت 24/7
"""
import argparse, asyncio, os, ssl, sys, time
from typing import List
sys.path.insert(0, os.path.dirname(__file__))

import aiohttp

from bitunix_scanner.spot_client import SpotClient
from bitunix_scanner.triangle_arb import (
    scan_triangles, Triangle,
    TOTAL_COST, MIN_NET_PROFIT, BASE_AMOUNT,
    _rank, _bar,
)

SCAN_INTERVAL = 20
SHOW_TOP      = 10


# ── نمایش ─────────────────────────────────────────────────────────────────────

def _fmt(v: float) -> str:
    if v == 0:
        return "0"
    if abs(v) >= 1_000:
        return f"{v:,.2f}"
    if abs(v) >= 1:
        return f"{v:.6f}"
    return f"{v:.8f}"


def _fmt_tri(rank: int, t: Triangle) -> str:
    rl    = _rank(t.score) if t.profitable else "❌ زیر آستانه"
    color = "🔺" if t.profitable else "⚪"
    net_lbl = f"{t.net*100:>+7.3f}%"
    profit_lbl = f"{t.profit_usdt:>+7.2f} USDT" if t.profitable else f"{t.profit_usdt:>+7.2f} USDT (ضرر)"
    return f"""
┌{'─'*62}┐
│  {color} #{rank:<2}  {rl:<28}امتیاز: {t.score:>5.1f}  │
│  {_bar(t.score) if t.profitable else '░'*10:<14}                                    │
├{'─'*62}┤
│  لگ ۱  USDT → {t.a:<10}  ask: {_fmt(t.ask_a):<20}│
│  لگ ۲  {t.a:<6} → {t.b:<10}  نرخ ضمنی                        │
│  لگ ۳  {t.b:<6} → USDT      bid: {_fmt(t.bid_b):<20}│
├{'─'*62}┤
│  spread A : {t.spread_a*100:>6.3f}%   spread B : {t.spread_b*100:>6.3f}%          │
├{'─'*62}┤
│  ناخالص     : {t.gross*100:>+7.3f}%                                  │
│  کارمزد ×۳  : {-t.fee_cost*100:>+7.3f}%  (0.15% × 3 لگ)              │
│  اسپرد      : {-t.spread_cost*100:>+7.3f}%                                  │
│  ──────────────────────────────────────────────────────  │
│  خالص       : {net_lbl}  ≈ {profit_lbl} / {BASE_AMOUNT:.0f}    │
└{'─'*62}┘"""


def _summary(tris: List[Triangle], elapsed: float, source: str):
    tag = "📡 Spot" if "Spot" in source else "📊 Futures (fallback)"
    has_profit = any(t.profitable for t in tris)
    print(f"\n{'═'*64}")
    if has_profit:
        n = sum(1 for t in tris if t.profitable)
        print(f"  🔺 {n} مثلث سودآور یافت شد  [{elapsed:.1f}s]  {tag}")
    else:
        print(f"  ⚠️  بازار هم‌ارزش — هیچ مثلثی بالای آستانه نیست  [{elapsed:.1f}s]  {tag}")
        if tris:
            best = tris[0]
            gap  = MIN_NET_PROFIT - best.net
            print(f"  نزدیک‌ترین مسیر: USDT→{best.a}→{best.b}→USDT"
                  f"  (فاصله تا سود: {gap*100:.3f}%)")
    print(f"{'═'*64}")
    if not tris:
        return

    header = "سودآور" if has_profit else "نزدیک‌ترین (زیر آستانه)"
    print(f"\n  {header}:")
    print(f"  {'#':<4} {'A':<10} {'B':<10} {'ناخالص':<12} {'خالص':<12} {'سود USDT':<14} {'رتبه'}")
    print("  " + "─" * 64)
    for i, t in enumerate(tris[:SHOW_TOP], 1):
        rl = _rank(t.score) if t.profitable else "زیر آستانه"
        mark = "🔺" if t.profitable else "  "
        print(f"  {mark}#{i:<2} {t.a:<10} {t.b:<10} "
              f"{t.gross*100:>+.3f}%     {t.net*100:>+.3f}%     "
              f"{t.profit_usdt:>+.2f} USDT       {rl}")


# ── main ──────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live",     action="store_true")
    parser.add_argument("--interval", type=int, default=SCAN_INTERVAL)
    args = parser.parse_args()

    print(f"""
╔══════════════════════════════════════════════════════════╗
║   🔺 Triangular Arbitrage — Bitunix Spot Convert        ║
║   چرخه: USDT → A → B → USDT                            ║
║   کارمزد: 0.1%×3 + Slippage 0.05%×3 = 0.45% کل        ║
║   آستانه: net ≥ {MIN_NET_PROFIT*100:.2f}% خالص                        ║
╚══════════════════════════════════════════════════════════╝
""")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode    = ssl.CERT_NONE
    conn = aiohttp.TCPConnector(ssl=ssl_ctx)

    async with aiohttp.ClientSession(connector=conn) as session:
        spot = SpotClient(session)

        async def _one_scan():
            t0 = time.time()
            print(f"  [{time.strftime('%H:%M:%S')}] 🔍 fetch قیمت‌ها …", flush=True)
            tris = await scan_triangles(spot)
            elapsed = time.time() - t0
            src = "Futures (fallback)" if spot._use_futures_fallback else "Spot"
            print(f"  منبع: {src}", flush=True)
            _summary(tris, elapsed, src)
            profitable = [t for t in tris if t.profitable]
            near_miss  = [t for t in tris if not t.profitable]

            if profitable:
                for i, t in enumerate(profitable[:SHOW_TOP], 1):
                    print(_fmt_tri(i, t))
            elif near_miss:
                print(f"\n  ── نزدیک‌ترین مسیرها (اطلاعاتی) ──")
                for i, t in enumerate(near_miss[:3], 1):
                    print(_fmt_tri(i, t))
            return tris

        if not args.live:
            await _one_scan()
            return

        print(f"  🔄 Live — هر {args.interval}s  |  Ctrl+C خروج\n")
        while True:
            try:
                tris = await _one_scan()
                profitable = [t for t in tris if t.profitable]
                if profitable:
                    best = profitable[0]
                    print(f"\n  🔔 بهترین: USDT→{best.a}→{best.b}→USDT"
                          f"  net={best.net*100:+.3f}%"
                          f"  سود={best.profit_usdt:+.2f} USDT / {BASE_AMOUNT:.0f}")
            except Exception as e:
                print(f"  ⚠️  خطا: {e}")
            await asyncio.sleep(args.interval)


if __name__ == "__main__":
    asyncio.run(main())
