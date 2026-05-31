#!/usr/bin/env python3
"""
Pairs Arbitrage Scanner -- Bitunix Futures
corr + z-score divergence

Usage:
  python arbitrage.py           # single scan
  python arbitrage.py --live    # monitor 24/7
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
W = 46


def _line(c="-"): return c * W


def _fmt_opp(rank: int, o: ArbOpp) -> str:
    rl    = _rank(o.score)
    a_dir = "LONG " if o.direction_a == "LONG" else "SHORT"
    b_dir = "LONG " if o.direction_b == "LONG" else "SHORT"
    z_lbl = "OVER" if o.z_score > 0 else "UNDER"
    lines = [
        "",
        _line("="),
        f" #{rank}  {rl}",
        f"  score: {o.score:.1f}/100  {_bar(o.score)}",
        f"  corr={o.corr:.2f}  z={o.z_score:+.2f}s  {z_lbl}",
        _line("-"),
        f" {a_dir} {o.sym_a}",
        f"        @ {_fmt(o.price_a)}",
        f" {b_dir} {o.sym_b}",
        f"        @ {_fmt(o.price_b)}",
        f" ratio  : {o.ratio_now:.6f}",
        f" mean   : {o.ratio_mean:.6f}",
        f" dev    : {o.diverge_pct:.2f}%",
        _line("-"),
        f" gross  : {o.gross*100:>+.3f}%",
        f" fee x4 : {o.fee_cost*100:>+.3f}%  (0.06%x4)",
        f" spread : {o.spread_cost*100:>+.3f}%",
        f" ---",
        f" net    : {o.net*100:>+.3f}%",
        f" profit : {o.sim_usdt:>+.2f} USDT / 1000",
        _line("="),
    ]
    return "\n".join(lines)


def _summary(opps: List[ArbOpp], elapsed: float, n_sym: int):
    print(f"\n{_line('=')}")
    print(f" {len(opps)} opps from {n_sym} symbols  [{elapsed:.1f}s]")
    if not opps:
        print(f" No opportunity -- market aligned")
        print(_line("="))
        return
    print(_line("="))
    print(f" {'#':<3} {'A':<14} {'B':<14} {'net':<9} {'rank'}")
    print(f" {_line('-')}")
    for i, o in enumerate(opps[:SHOW_TOP], 1):
        print(f" #{i:<2} {o.sym_a:<14} {o.sym_b:<14} "
              f"{o.net*100:>+.3f}%  {_rank(o.score)}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live",     action="store_true")
    parser.add_argument("--interval", type=int, default=SCAN_INTERVAL)
    args = parser.parse_args()

    print(f"""
{_line('=')}
 Pairs Arbitrage -- Bitunix Futures
 top {TOP_SYMBOLS} symbols, corr+z-score
 fee: 0.06%x4=0.24% | threshold: 0.15%
{_line('=')}
""")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode    = ssl.CERT_NONE
    conn = aiohttp.TCPConnector(ssl=ssl_ctx)

    async with aiohttp.ClientSession(connector=conn) as session:
        client = AsyncBitunixClient(API_KEY, SECRET_KEY, session)

        async def _one_scan():
            t0      = time.time()
            print(f" [{time.strftime('%H:%M:%S')}] Scanning {TOP_SYMBOLS} symbols ...", flush=True)
            opps    = await scan(client)
            elapsed = time.time() - t0
            _summary(opps, elapsed, TOP_SYMBOLS)
            for i, o in enumerate(opps[:SHOW_TOP], 1):
                print(_fmt_opp(i, o))
            return opps

        if not args.live:
            await _one_scan()
            return

        print(f" Live -- every {args.interval}s  |  Ctrl+C to exit\n")
        while True:
            try:
                opps = await _one_scan()
                if opps:
                    best = opps[0]
                    print(f"\n BEST: {best.sym_a}+{best.sym_b}")
                    print(f"  net={best.net*100:+.3f}%  score={best.score:.0f}")
            except Exception as e:
                print(f" ERROR: {e}")
            await asyncio.sleep(args.interval)


if __name__ == "__main__":
    asyncio.run(main())
