#!/usr/bin/env python3
"""
True Triangular Arbitrage — Bitunix Spot Convert
Cycle: USDT -> A -> B -> USDT

Usage:
  python triangle_arb.py           # single scan
  python triangle_arb.py --live    # monitor 24/7
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


def _fmt(v: float) -> str:
    if v == 0:
        return "0"
    if abs(v) >= 1_000:
        return f"{v:,.2f}"
    if abs(v) >= 1:
        return f"{v:.6f}"
    return f"{v:.8f}"


def _fmt_tri(rank: int, t: Triangle) -> str:
    rl         = _rank(t.score) if t.profitable else "BELOW THRESHOLD"
    color      = ">" if t.profitable else "-"
    net_lbl    = f"{t.net*100:>+7.3f}%"
    profit_lbl = (f"{t.profit_usdt:>+7.2f} USDT"
                  if t.profitable
                  else f"{t.profit_usdt:>+7.2f} USDT (loss)")
    bar        = _bar(t.score) if t.profitable else "." * 10
    return (
        f"\n+{'─'*62}+\n"
        f"|  {color} #{rank:<2}  {rl:<28}score: {t.score:>5.1f}  |\n"
        f"|  {bar:<14}                                    |\n"
        f"+{'─'*62}+\n"
        f"|  Leg 1  USDT -> {t.a:<10}  ask: {_fmt(t.ask_a):<20}|\n"
        f"|  Leg 2  {t.a:<6} -> {t.b:<10}  implied cross rate              |\n"
        f"|  Leg 3  {t.b:<6} -> USDT      bid: {_fmt(t.bid_b):<20}|\n"
        f"+{'─'*62}+\n"
        f"|  spread A : {t.spread_a*100:>6.3f}%   spread B : {t.spread_b*100:>6.3f}%          |\n"
        f"+{'─'*62}+\n"
        f"|  gross      : {t.gross*100:>+7.3f}%                                  |\n"
        f"|  fee x3     : {-t.fee_cost*100:>+7.3f}%  (0.15% x 3 legs)               |\n"
        f"|  spread     : {-t.spread_cost*100:>+7.3f}%                                  |\n"
        f"|  ────────────────────────────────────────────────────  |\n"
        f"|  net        : {net_lbl}  ~ {profit_lbl} / {BASE_AMOUNT:.0f}    |\n"
        f"+{'─'*62}+"
    )


def _summary(tris: List[Triangle], elapsed: float, source: str):
    tag        = "Spot API" if "Spot" in source else "Futures (fallback)"
    has_profit = any(t.profitable for t in tris)
    print(f"\n{'='*64}")
    if has_profit:
        n = sum(1 for t in tris if t.profitable)
        print(f"  > {n} profitable triangle(s) found  [{elapsed:.1f}s]  [{tag}]")
    else:
        print(f"  - No triangle above threshold  [{elapsed:.1f}s]  [{tag}]")
        if tris:
            best = tris[0]
            gap  = MIN_NET_PROFIT - best.net
            print(f"    Closest: USDT->{best.a}->{best.b}->USDT"
                  f"  (gap to profit: {gap*100:.3f}%)")
    print(f"{'='*64}")
    if not tris:
        return

    header = "Profitable" if has_profit else "Near-miss (below threshold)"
    print(f"\n  {header}:")
    print(f"  {'#':<4} {'A':<10} {'B':<10} {'gross':<12} {'net':<12} {'profit':<14} {'rank'}")
    print("  " + "-" * 64)
    for i, t in enumerate(tris[:SHOW_TOP], 1):
        rl   = _rank(t.score) if t.profitable else "below threshold"
        mark = "> " if t.profitable else "  "
        print(f"  {mark}#{i:<2} {t.a:<10} {t.b:<10} "
              f"{t.gross*100:>+.3f}%     {t.net*100:>+.3f}%     "
              f"{t.profit_usdt:>+.2f} USDT       {rl}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live",     action="store_true")
    parser.add_argument("--interval", type=int, default=SCAN_INTERVAL)
    args = parser.parse_args()

    print(f"""
+========================================================+
|   Triangular Arbitrage -- Bitunix Spot Convert         |
|   Cycle: USDT -> A -> B -> USDT                        |
|   Fee: 0.1%x3 + Slippage 0.05%x3 = 0.45% total       |
|   Threshold: net >= {MIN_NET_PROFIT*100:.2f}%                          |
+========================================================+
""")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode    = ssl.CERT_NONE
    conn = aiohttp.TCPConnector(ssl=ssl_ctx)

    async with aiohttp.ClientSession(connector=conn) as session:
        spot = SpotClient(session)

        async def _one_scan():
            t0 = time.time()
            print(f"  [{time.strftime('%H:%M:%S')}] Fetching prices ...", flush=True)
            tris    = await scan_triangles(spot)
            elapsed = time.time() - t0
            src     = "Futures (fallback)" if spot._use_futures_fallback else "Spot"
            print(f"  Source: {src}", flush=True)
            _summary(tris, elapsed, src)
            profitable = [t for t in tris if t.profitable]
            near_miss  = [t for t in tris if not t.profitable]

            if profitable:
                for i, t in enumerate(profitable[:SHOW_TOP], 1):
                    print(_fmt_tri(i, t))
            elif near_miss:
                print(f"\n  -- Near-miss paths (info only) --")
                for i, t in enumerate(near_miss[:3], 1):
                    print(_fmt_tri(i, t))
            return tris

        if not args.live:
            await _one_scan()
            return

        print(f"  Live mode -- every {args.interval}s  |  Ctrl+C to exit\n")
        while True:
            try:
                tris       = await _one_scan()
                profitable = [t for t in tris if t.profitable]
                if profitable:
                    best = profitable[0]
                    print(f"\n  BEST: USDT->{best.a}->{best.b}->USDT"
                          f"  net={best.net*100:+.3f}%"
                          f"  profit={best.profit_usdt:+.2f} USDT / {BASE_AMOUNT:.0f}")
            except Exception as e:
                print(f"  ERROR: {e}")
            await asyncio.sleep(args.interval)


if __name__ == "__main__":
    asyncio.run(main())
