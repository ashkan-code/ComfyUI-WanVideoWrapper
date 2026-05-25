"""
Bitunix Multi-TF ICT Order Block Scanner
Usage:
    python -m bitunix_scanner.main
    python -m bitunix_scanner.main --top 100 --min-score 12
    python -m bitunix_scanner.main --no-alignment   # include BTC-divergent signals
"""

import argparse
import asyncio
import os
import sys

from .scanner import run_scan
from .signals import format_signal, format_summary

API_KEY = os.getenv("BITUNIX_API_KEY", "7bee3f4756a0dbc89ae152f34c2175ac")
SECRET_KEY = os.getenv("BITUNIX_SECRET_KEY", "4e0a845778d49068297106a64cbcda61")


def parse_args():
    p = argparse.ArgumentParser(description="Bitunix ICT OB multi-TF scanner")
    p.add_argument("--top", type=int, default=150,
                   help="Scan top N symbols by 24h volume (default 150)")
    p.add_argument("--min-score", type=int, default=9,
                   help="Minimum OB confluence score to include (default 9)")
    p.add_argument("--no-alignment", action="store_true",
                   help="Include signals that diverge from BTC bias")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress progress output")
    return p.parse_args()


async def _main():
    args = parse_args()

    # Apply CLI overrides to scanner module
    import bitunix_scanner.scanner as sc
    sc.TOP_N_BY_VOLUME = args.top
    sc.MIN_OB_SCORE = args.min_score
    sc.REQUIRE_ALIGNMENT = not args.no_alignment

    print(f"""
╔══════════════════════════════════════════════╗
║   BITUNIX  ·  ICT Multi-TF OB Scanner       ║
║   TFs : 1m | 5m | 15m | 1h | 4h | 1d       ║
║   Min confluence : 3 timeframes              ║
║   Leverage formula : 15 ÷ SL%  (max 10×)    ║
╚══════════════════════════════════════════════╝
""")

    signals = await run_scan(
        API_KEY, SECRET_KEY,
        top_n=args.top,
        progress=not args.quiet,
    )

    if signals:
        print(format_summary(signals))
    else:
        print("\n  ── No signals found in this scan ──\n")
        print("  Tips:")
        print("  • Lower --min-score (currently", args.min_score, ")")
        print("  • Add --no-alignment to include BTC-divergent signals")
        print("  • Increase --top to scan more symbols")


def main():
    asyncio.run(_main())


if __name__ == "__main__":
    main()
