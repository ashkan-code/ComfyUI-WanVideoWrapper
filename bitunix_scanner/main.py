"""
Bitunix Multi-TF ICT Order Block Scanner + Auto-Trader

Scan only:
    python -m bitunix_scanner.main
    python -m bitunix_scanner.main --top 100 --min-score 12

Scan + Auto-trade (opens orders when confirmed):
    python -m bitunix_scanner.main --auto
    python -m bitunix_scanner.main --auto --max-pos 2 --top 100

Other flags:
    --no-alignment   include signals that diverge from BTC bias
    --quiet          suppress progress output
"""

import argparse
import asyncio
import os

import aiohttp

from .client import AsyncBitunixClient
from .scanner import run_scan
from .signals import format_summary
from .trader import AutoTrader

API_KEY = os.getenv("BITUNIX_API_KEY", "7bee3f4756a0dbc89ae152f34c2175ac")
SECRET_KEY = os.getenv("BITUNIX_SECRET_KEY", "4e0a845778d49068297106a64cbcda61")


def parse_args():
    p = argparse.ArgumentParser(description="Bitunix ICT OB multi-TF scanner")
    p.add_argument("--top", type=int, default=150,
                   help="Scan top N symbols by 24h volume (default 150)")
    p.add_argument("--min-score", type=int, default=9,
                   help="Minimum OB confluence score (default 9)")
    p.add_argument("--no-alignment", action="store_true",
                   help="Include signals diverging from BTC bias")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress scan progress output")
    # ── Auto-trade flags ──────────────────────────────────────────────────
    p.add_argument("--auto", action="store_true",
                   help="Auto-trade: open orders when entry confirmed")
    p.add_argument("--max-pos", type=int, default=3,
                   help="Max simultaneous open positions (default 3)")
    p.add_argument("--risk", type=float, default=0.90,
                   help="Fraction of balance to risk per trade (default 0.90)")
    p.add_argument("--poll", type=int, default=30,
                   help="Seconds between price checks in auto mode (default 30)")
    return p.parse_args()


async def _main():
    args = parse_args()

    import bitunix_scanner.scanner as sc
    sc.TOP_N_BY_VOLUME = args.top
    sc.MIN_OB_SCORE = args.min_score
    sc.REQUIRE_ALIGNMENT = not args.no_alignment

    mode = "SCAN + AUTO-TRADE" if args.auto else "SCAN ONLY"
    print(f"""
╔══════════════════════════════════════════════╗
║   BITUNIX  ·  ICT Multi-TF OB Scanner       ║
║   TFs : 1m | 5m | 15m | 1h | 4h | 1d       ║
║   Min confluence : 3 timeframes              ║
║   Leverage : 15 ÷ SL%  (max 10×)            ║
║   Mode : {mode:<36}║
╚══════════════════════════════════════════════╝
""")

    # ── Run scan ──────────────────────────────────────────────────────────
    signals = await run_scan(
        API_KEY, SECRET_KEY,
        top_n=args.top,
        progress=not args.quiet,
    )

    if not signals:
        print("\n  ── No signals found ──\n")
        print("  Tips: lower --min-score, add --no-alignment, or increase --top")
        return

    print(format_summary(signals))

    if not args.auto:
        return

    # ── Auto-trade ────────────────────────────────────────────────────────
    print("\n" + "═" * 48)
    print("  Starting auto-trader …")
    print("  Ctrl+C to stop.\n")

    async with aiohttp.ClientSession() as session:
        client = AsyncBitunixClient(API_KEY, SECRET_KEY, session)
        trader = AutoTrader(
            client,
            max_positions=args.max_pos,
            risk_pct=args.risk,
            poll_sec=args.poll,
        )
        trader.add_signals(signals)
        try:
            await trader.run()
        except KeyboardInterrupt:
            print("\n\n  ⛔ Auto-trader stopped by user.\n")


def main():
    asyncio.run(_main())


if __name__ == "__main__":
    main()
