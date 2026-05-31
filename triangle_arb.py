#!/usr/bin/env python3
"""
True Triangular Arbitrage -- Bitunix Spot Convert
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
W = 46   # line width for phone screen


def _fmt(v: float) -> str:
    if v == 0:       return "0"
    if abs(v) >= 1_000: return f"{v:,.2f}"
    if abs(v) >= 1:  return f"{v:.6f}"
    return f"{v:.8f}"


def _line(char="-"): return char * W


def _fmt_tri(rank: int, t: Triangle) -> str:
    rl  = _rank(t.score) if t.profitable else "BELOW THRESHOLD"
    bar = _bar(t.score) if t.profitable else "." * 10
    net_lbl    = f"{t.net*100:>+.3f}%"
    profit_lbl = f"{t.profit_usdt:>+.2f} USDT"
    sign       = ">" if t.profitable else "-"
    lines = [
        "",
        _line("="),
        f" {sign} #{rank}  {rl}",
        f"   score: {t.score:.1f}/100  {bar}",
        _line("-"),
        f" Leg1  USDT -> {t.a}",
        f"       ask : {_fmt(t.ask_a)}",
        f" Leg2  {t.a} -> {t.b}",
        f"       (implied cross rate)",
        f" Leg3  {t.b} -> USDT",
        f"       bid : {_fmt(t.bid_b)}",
        _line("-"),
        f" spread A : {t.spread_a*100:.3f}%",
        f" spread B : {t.spread_b*100:.3f}%",
        _line("-"),
        f" gross    : {t.gross*100:>+.4f}%",
        f" fee x3   : {-t.fee_cost*100:>+.4f}%  (0.15% x3)",
        f" spread   : {-t.spread_cost*100:>+.4f}%",
        f" ---",
        f" net      : {net_lbl}",
        f" profit   : {profit_lbl} / {BASE_AMOUNT:.0f} USDT",
        _line("="),
    ]
    return "\n".join(lines)


def _summary(tris: List[Triangle], elapsed: float, source: str):
    tag        = "Spot" if "Spot" in source else "Futures(fallback)"
    has_profit = any(t.profitable for t in tris)
    print(f"\n{_line('=')}")
    if has_profit:
        n = sum(1 for t in tris if t.profitable)
        print(f" {n} profitable triangle(s)  [{elapsed:.1f}s]")
        print(f" Source: {tag}")
    else:
        print(f" No triangle above threshold  [{elapsed:.1f}s]")
        print(f" Source: {tag}")
        if tris:
            best = tris[0]
            gap  = MIN_NET_PROFIT - best.net
            print(f" Closest: USDT->{best.a}->{best.b}->USDT")
            print(f" Gap to profit: {gap*100:.3f}%")
    print(_line("="))
    if not tris:
        return
    header = "Profitable" if has_profit else "Near-miss (below threshold)"
    print(f"\n {header}:")
    print(f" {'#':<3} {'A':<8} {'B':<8} {'net':<10} {'result'}")
    print(f" {_line('-')}")
    for i, t in enumerate(tris[:SHOW_TOP], 1):
        rl   = _rank(t.score) if t.profitable else "no"
        mark = ">" if t.profitable else " "
        print(f" {mark}#{i:<2} {t.a:<8} {t.b:<8} "
              f"{t.net*100:>+.3f}%   {rl}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live",     action="store_true")
    parser.add_argument("--interval", type=int, default=SCAN_INTERVAL)
    args = parser.parse_args()

    print(f"""
{_line('=')}
 Triangular Arbitrage -- Bitunix Spot
 Cycle: USDT -> A -> B -> USDT
 Fee: 0.1%x3 + slip 0.05%x3 = 0.45%
 Threshold: net >= {MIN_NET_PROFIT*100:.2f}%
{_line('=')}
""")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode    = ssl.CERT_NONE
    conn = aiohttp.TCPConnector(ssl=ssl_ctx)

    async with aiohttp.ClientSession(connector=conn) as session:
        spot = SpotClient(session)

        async def _one_scan():
            t0   = time.time()
            print(f" [{time.strftime('%H:%M:%S')}] Fetching ...", flush=True)
            tris    = await scan_triangles(spot)
            elapsed = time.time() - t0
            src     = "Futures (fallback)" if spot._use_futures_fallback else "Spot"
            print(f" Source: {src}", flush=True)
            _summary(tris, elapsed, src)
            profitable = [t for t in tris if t.profitable]
            near_miss  = [t for t in tris if not t.profitable]
            if profitable:
                for i, t in enumerate(profitable[:SHOW_TOP], 1):
                    print(_fmt_tri(i, t))
            elif near_miss:
                print("\n -- Near-miss (info only) --")
                for i, t in enumerate(near_miss[:3], 1):
                    print(_fmt_tri(i, t))
            return tris

        if not args.live:
            await _one_scan()
            return

        print(f" Live -- every {args.interval}s  |  Ctrl+C to exit\n")
        while True:
            try:
                tris       = await _one_scan()
                profitable = [t for t in tris if t.profitable]
                if profitable:
                    best = profitable[0]
                    print(f"\n BEST: USDT->{best.a}->{best.b}->USDT")
                    print(f"  net={best.net*100:+.3f}%  "
                          f"profit={best.profit_usdt:+.2f} USDT")
            except Exception as e:
                print(f" ERROR: {e}")
            await asyncio.sleep(args.interval)


if __name__ == "__main__":
    asyncio.run(main())
