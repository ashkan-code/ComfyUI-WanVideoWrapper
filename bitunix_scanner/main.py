"""
Bitunix Scalping System — ICT Multi-TF OB Confluence

Rules (hardcoded):
    • Max leverage  : 10x  (floor(15 / SL%) capped at 10)
    • BTC alignment : required  (signals must match BTC bias)
    • SL            : tightest OB wick (lowest TF)
    • TP            : 2× risk  (R:R 1:2)
    • Live manager  : closes on adverse 3m candle pattern

Scan only:
    python -m bitunix_scanner.main

Scan + Auto-trade + Live management:
    python -m bitunix_scanner.main --auto
    python -m bitunix_scanner.main --auto --max-pos 2 --top 150

Flags:
    --quiet          suppress scan progress
    --max-pos N      max simultaneous positions (default 3)
    --risk R         fraction of balance per trade (default 0.90)
    --poll N         seconds between checks (default 30)
    --top N          top N symbols by 24h volume to scan (default 150)
    --min-score N    minimum OB confluence score (default 9)
"""

import argparse
import asyncio
import os

import aiohttp

from .client import AsyncBitunixClient
from .live_manager import LiveManager
from .scanner import run_scan
from .signals import format_summary
from .trader import AutoTrader

API_KEY    = os.getenv("BITUNIX_API_KEY",    "7bee3f4756a0dbc89ae152f34c2175ac")
SECRET_KEY = os.getenv("BITUNIX_SECRET_KEY", "4e0a845778d49068297106a64cbcda61")


def parse_args():
    p = argparse.ArgumentParser(description="Bitunix ICT scalping system")
    p.add_argument("--top",       type=int,   default=150)
    p.add_argument("--min-score", type=int,   default=9)
    p.add_argument("--quiet",     action="store_true")
    p.add_argument("--auto",      action="store_true",
                   help="Enable auto-trading + live position management")
    p.add_argument("--max-pos",   type=int,   default=3)
    p.add_argument("--risk",      type=float, default=0.90)
    p.add_argument("--poll",      type=int,   default=30)
    return p.parse_args()


async def _main():
    args = parse_args()

    import bitunix_scanner.scanner as sc
    sc.TOP_N_BY_VOLUME   = args.top
    sc.MIN_OB_SCORE      = args.min_score
    sc.REQUIRE_ALIGNMENT = True          # always required — BTC alignment is mandatory

    mode = "SCALP AUTO-TRADE + LIVE MGR" if args.auto else "SCAN ONLY"
    print(f"""
╔══════════════════════════════════════════════╗
║   BITUNIX  ·  ICT Scalping System           ║
║   TFs        : 1m 5m 15m 1h 4h 1d          ║
║   SL         : tightest OB wick (lowest TF) ║
║   TP         : 2 × risk  (R:R 1:2)          ║
║   Leverage   : 15 ÷ SL%  (max 10×)          ║
║   BTC Align  : REQUIRED  ✓                  ║
║   Exit       : pattern / BOS / BTC flip     ║
║   Mode       : {mode:<33}║
╚══════════════════════════════════════════════╝
""")

    # ── Scan ─────────────────────────────────────────────────────────────
    signals = await run_scan(
        API_KEY, SECRET_KEY,
        top_n=args.top,
        progress=not args.quiet,
    )

    if not signals:
        print("\n  ── No signals found ──\n")
        print("  Try: lower --min-score, add --no-alignment, or increase --top")
        return

    print(format_summary(signals))

    if not args.auto:
        return

    # ── Auto-trade + Live management (concurrent tasks) ───────────────────
    print("\n" + "═" * 48)
    print("  Starting auto-trader + live manager …")
    print("  Ctrl+C to stop.\n")

    async with aiohttp.ClientSession() as session:
        client = AsyncBitunixClient(API_KEY, SECRET_KEY, session)

        live_mgr = LiveManager(client, poll_sec=20)
        trader   = AutoTrader(
            client,
            max_positions=args.max_pos,
            risk_pct=args.risk,
            poll_sec=args.poll,
            live_manager=live_mgr,
        )
        trader.add_signals(signals)

        try:
            await asyncio.gather(
                trader.run(),
                live_mgr.run(),
            )
        except KeyboardInterrupt:
            print("\n\n  ⛔ Stopped by user.\n")


def main():
    asyncio.run(_main())


if __name__ == "__main__":
    main()
