"""
Bitunix ICT Scalping — 24/7 Autonomous Live System

Rules (hardcoded):
    • Max leverage  : 10x
    • BTC alignment : required
    • SL            : exact entry-OB wick + 0.05% buffer
    • TP            : nearest ICT target (FVG / swing low / equal levels)
    • Confidence    : ≥ 90% → full margin | 70–89% → 90% | < 70% → skip
    • Danger exit   : structural invalidation (15m+1h) / pattern / BTC flip
    • Loop          : after every close → immediate re-scan for next entry

Run:
    python -m bitunix_scanner.main            # scan only (one shot)
    python -m bitunix_scanner.main --live     # 24/7 autonomous mode
    python -m bitunix_scanner.main --live --top 200 --max-pos 3

Flags:
    --live           24/7 mode (scan → trade → monitor → re-scan, forever)
    --top N          symbols to scan by 24h volume (default 150)
    --min-score N    minimum OB score (default 9)
    --max-pos N      max simultaneous positions (default 3)
    --risk R         normal risk fraction (default 0.90)
    --poll N         AutoTrader poll seconds (default 30)
    --quiet          suppress scan progress bars
"""

import argparse
import asyncio
import os
import traceback
from datetime import datetime

import aiohttp

from .client import AsyncBitunixClient
from .live_manager import LiveManager, ManagedPosition
from .scanner import run_scan
from .signals import format_summary
from .trader import AutoTrader

API_KEY    = os.getenv("BITUNIX_API_KEY",    "7bee3f4756a0dbc89ae152f34c2175ac")
SECRET_KEY = os.getenv("BITUNIX_SECRET_KEY", "4e0a845778d49068297106a64cbcda61")

RESCAN_WAIT    = 300   # seconds between scans when no signal found
POST_TRADE_WAIT = 30   # seconds after all positions closed before re-scan
ERROR_WAIT     = 60    # seconds to wait after an unexpected error


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def parse_args():
    p = argparse.ArgumentParser(description="Bitunix ICT 24/7 scalping system")
    p.add_argument("--live",      action="store_true",
                   help="Run in 24/7 autonomous mode (scan → trade → re-scan)")
    p.add_argument("--top",       type=int,   default=150)
    p.add_argument("--min-score", type=int,   default=9)
    p.add_argument("--quiet",     action="store_true")
    p.add_argument("--max-pos",   type=int,   default=3)
    p.add_argument("--risk",      type=float, default=0.90)
    p.add_argument("--poll",      type=int,   default=30)
    return p.parse_args()


# ── helpers ────────────────────────────────────────────────────────────────

async def _load_existing_positions(client: AsyncBitunixClient,
                                   live_mgr: LiveManager) -> int:
    """Register any open exchange positions with LiveManager."""
    positions = await client.get_positions()
    if not positions:
        return 0

    tickers = await client._get_public("/api/v1/futures/market/tickers")
    price_map = {t["symbol"]: float(t["lastPrice"])
                 for t in (tickers.get("data") or [])}

    added = 0
    for p in positions:
        sym       = p["symbol"]
        # skip if already being watched
        if sym in live_mgr._positions:
            continue

        entry     = float(p["avgOpenPrice"])
        pos_id    = p["positionId"]
        qty_str   = str(p.get("qty", "0"))
        direction = "SHORT" if p["side"] in ("SELL", "SHORT") else "LONG"
        cur       = price_map.get(sym, entry)

        c5m = await client.get_klines(sym, "5m", 60)
        c1h = await client.get_klines(sym, "1h", 60)
        c4h = await client.get_klines(sym, "4h", 60)

        if c5m:
            swing_h = max(float(c["high"]) for c in c5m[-30:])
            swing_l = min(float(c["low"])  for c in c5m[-30:])
            sl = (max(swing_h, cur) * 1.001 if direction == "SHORT"
                  else min(swing_l, cur) * 0.999)
        else:
            liq = float(p.get("liqPrice", 0) or 0)
            sl = liq * 0.97 if direction == "SHORT" else liq * 1.03

        from .ict import find_ict_tp
        ict_dir = "bearish" if direction == "SHORT" else "bullish"
        tp, tp_reason = find_ict_tp(c1h, c4h, entry, ict_dir, sl, min_rr=1.5)

        mp = ManagedPosition(
            symbol      = sym,
            direction   = direction,
            entry_price = entry,
            sl_price    = sl,
            tp_price    = tp,
            ob_high     = sl,
            ob_low      = tp,
            position_id = pos_id,
            qty         = qty_str,
        )
        live_mgr.add_position(mp)
        print(f"  [{_ts()}] 📡 {sym}  {direction}  "
              f"entry={entry:.6f}  SL={sl:.6f}  TP={tp:.6f}  ({tp_reason})")
        added += 1

    return added


# ── single trading cycle ───────────────────────────────────────────────────

async def _run_cycle(client: AsyncBitunixClient,
                     args,
                     cycle: int) -> str:
    """
    One full cycle: load positions → scan → trade → monitor.
    Returns 'traded' | 'no_signal' | 'positions_only'.
    """
    print(f"\n  [{_ts()}]  ─── Cycle #{cycle} ───")

    live_mgr = LiveManager(client, poll_sec=15)

    # Always load existing positions first (covers SL/TP monitoring)
    n_existing = await _load_existing_positions(client, live_mgr)
    if n_existing:
        print(f"  [{_ts()}] 📋 {n_existing} existing position(s) handed to LiveManager")

    # ── Scan ──────────────────────────────────────────────────────────────
    print(f"  [{_ts()}] 🔍 Scanning top {args.top} symbols …")
    signals = await run_scan(
        API_KEY, SECRET_KEY,
        top_n=args.top,
        progress=not args.quiet,
    )

    # Re-sync positions opened during the scan (race-condition fix)
    n_new = await _load_existing_positions(client, live_mgr)
    if n_new:
        print(f"  [{_ts()}] 🔄 {n_new} new position(s) found after scan — added to LiveManager")

    if not signals:
        print(f"  [{_ts()}] ── سیگنالی یافت نشد")
        if live_mgr._positions:
            # Still have open positions to watch — run manager only
            print(f"  [{_ts()}] 📡 LiveManager ادامه می‌دهد برای {len(live_mgr._positions)} پوزیشن …")
            await live_mgr.run()
        return "no_signal"

    print(format_summary(signals))

    trader = AutoTrader(
        client,
        max_positions = args.max_pos,
        risk_pct      = args.risk,
        poll_sec      = args.poll,
        live_manager  = live_mgr,
    )
    trader.add_signals(signals)

    # Run trader + monitor concurrently until both are idle
    await asyncio.gather(trader.run(), live_mgr.run())

    return "traded"


# ── 24/7 main loop ─────────────────────────────────────────────────────────

async def _live_loop(args):
    print(f"""
╔══════════════════════════════════════════════════╗
║   BITUNIX  ·  ICT  ·  24/7 AUTONOMOUS SYSTEM   ║
║   TFs      : 1m 5m 15m 1h 4h 1d               ║
║   SL       : exact OB wick  (+0.05% buffer)    ║
║   TP       : ICT target (FVG / liq pool)       ║
║   Leverage : max 10x  (15 ÷ SL%)               ║
║   Margin   : اعتماد ≥90% → فول مارجین            ║
║   Danger   : structural / pattern / BTC flip   ║
║   Re-scan  : بعد از هر خروج → فوری              ║
╚══════════════════════════════════════════════════╝
""")

    cycle = 0
    total_cycles = 0

    async with aiohttp.ClientSession() as session:
        client = AsyncBitunixClient(API_KEY, SECRET_KEY, session)

        while True:
            cycle += 1
            total_cycles += 1
            try:
                result = await _run_cycle(client, args, cycle)

                if result == "no_signal":
                    print(f"\n  [{_ts()}] ⏳ بررسی مجدد در {RESCAN_WAIT // 60} دقیقه …\n")
                    await asyncio.sleep(RESCAN_WAIT)
                else:
                    # Traded or had positions — re-scan immediately after brief pause
                    print(f"\n  [{_ts()}] ✅ چرخه #{cycle} کامل شد — شروع مجدد در {POST_TRADE_WAIT}s …\n")
                    await asyncio.sleep(POST_TRADE_WAIT)

            except asyncio.CancelledError:
                raise
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"\n  [{_ts()}] ❌ خطا در چرخه #{cycle}: {e}")
                traceback.print_exc()
                print(f"  [{_ts()}] 🔄 ادامه در {ERROR_WAIT}s …\n")
                await asyncio.sleep(ERROR_WAIT)


# ── entry points ───────────────────────────────────────────────────────────

async def _main():
    args = parse_args()

    import bitunix_scanner.scanner as sc
    sc.TOP_N_BY_VOLUME   = args.top
    sc.MIN_OB_SCORE      = args.min_score
    sc.REQUIRE_ALIGNMENT = True

    if args.live:
        try:
            await _live_loop(args)
        except (KeyboardInterrupt, asyncio.CancelledError):
            print(f"\n\n  [{_ts()}] ⛔ سیستم توسط کاربر متوقف شد.\n")
        return

    # ── One-shot scan mode ────────────────────────────────────────────────
    print("""
╔══════════════════════════════════════════════╗
║   BITUNIX  ·  ICT Scalping System           ║
║   Mode     : SCAN ONLY                      ║
╚══════════════════════════════════════════════╝
""")
    async with aiohttp.ClientSession() as session:
        client = AsyncBitunixClient(API_KEY, SECRET_KEY, session)
        signals = await run_scan(API_KEY, SECRET_KEY,
                                 top_n=args.top,
                                 progress=not args.quiet)
        if signals:
            print(format_summary(signals))
        else:
            print("\n  ── No signals found ──\n")


def main():
    asyncio.run(_main())


if __name__ == "__main__":
    main()
