#!/usr/bin/env python3
"""
Pairs Arbitrage Scanner -- Bitunix Futures
corr + z-score divergence across top symbols

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


def _fmt_opp(rank: int, o: ArbOpp) -> str:
    rl    = _rank(o.score)
    a_ico = "L" if o.direction_a == "LONG" else "S"
    b_ico = "L" if o.direction_b == "LONG" else "S"
    z_lbl = "OVERVALUED" if o.z_score > 0 else "UNDERVALUED"

    return (
        f"\n+{'─'*60}+\n"
        f"|  #{rank:<2}  {rl:<22}  score: {o.score:>5.1f}/100      |\n"
        f"|  {_bar(o.score):<14}  corr={o.corr:.2f}  z={o.z_score:+.2f}s  {z_lbl:<14}  |\n"
        f"+{'─'*60}+\n"
        f"|  {a_ico} {o.direction_a:<5} {o.sym_a:<16}  @ {_fmt(o.price_a):<16}  |\n"
        f"|  {b_ico} {o.direction_b:<5} {o.sym_b:<16}  @ {_fmt(o.price_b):<16}  |\n"
        f"|  ratio: {o.ratio_now:.6f}  mean: {o.ratio_mean:.6f}  dev: {o.diverge_pct:.2f}%  |\n"
        f"+{'─'*60}+\n"
        f"|  gross      : {o.gross*100:>+7.3f}%                                   |\n"
        f"|  fee x4     : {o.fee_cost*100:>+7.3f}%  (taker 0.06% x 4 legs)        |\n"
        f"|  spread     : {o.spread_cost*100:>+7.3f}%                                   |\n"
        f"|  ─────────────────────────────────────────────────   |\n"
        f"|  net        : {o.net*100:>+7.3f}%  ~ {o.sim_usdt:>+7.2f} USDT / 1000     |\n"
        f"+{'─'*60}+"
    )


def _summary(opps: List[ArbOpp], elapsed: float, n_sym: int):
    print(f"\n{'='*62}")
    print(f"  {len(opps)} opportunities from {n_sym} symbols  [{elapsed:.1f}s]")
    if not opps:
        print(f"  No opportunity above threshold -- market aligned")
        print(f"{'='*62}")
        return
    print(f"{'='*62}")
    print(f"  {'#':<4} {'A':<16} {'dir':<7} {'B':<16} {'dir':<7} {'z':<8} {'net':<10} {'rank'}")
    print("  " + "-" * 60)
    for i, o in enumerate(opps[:SHOW_TOP], 1):
        print(f"  #{i:<3} {o.sym_a:<16} {o.direction_a:<7} {o.sym_b:<16} "
              f"{o.direction_b:<7} {o.z_score:>+.2f}s  {o.net*100:>+.3f}%  {_rank(o.score)}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live",     action="store_true")
    parser.add_argument("--interval", type=int, default=SCAN_INTERVAL)
    args = parser.parse_args()

    print(f"""
+====================================================+
|   Pairs Arbitrage Scanner -- Bitunix Futures       |
|   top {TOP_SYMBOLS} symbols -> all pairs -> corr + z-score  |
|   fee: 0.06%x4=0.24%  |  spread: live depth        |
|   threshold: corr>=0.60  |z|>=1.5s  net>=0.15%     |
+====================================================+
""")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode    = ssl.CERT_NONE
    conn = aiohttp.TCPConnector(ssl=ssl_ctx)

    async with aiohttp.ClientSession(connector=conn) as session:
        client = AsyncBitunixClient(API_KEY, SECRET_KEY, session)

        async def _one_scan():
            t0   = time.time()
            print(f"  [{time.strftime('%H:%M:%S')}] Scanning {TOP_SYMBOLS} symbols ...", flush=True)
            opps    = await scan(client)
            elapsed = time.time() - t0
            _summary(opps, elapsed, TOP_SYMBOLS)
            for i, o in enumerate(opps[:SHOW_TOP], 1):
                print(_fmt_opp(i, o))
            return opps

        if not args.live:
            await _one_scan()
            return

        print(f"  Live -- every {args.interval}s  |  Ctrl+C to exit\n")
        while True:
            try:
                opps = await _one_scan()
                if opps:
                    best = opps[0]
                    print(f"\n  BEST: {best.sym_a}+{best.sym_b}"
                          f"  net={best.net*100:+.3f}%  score={best.score:.0f}")
            except Exception as e:
                print(f"  ERROR: {e}")
            await asyncio.sleep(args.interval)


if __name__ == "__main__":
    asyncio.run(main())
