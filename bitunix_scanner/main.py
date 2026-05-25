"""
Bitunix ICT Advanced Scalping — 24/7 Autonomous System

Rules:
    • Top 20 symbols by volume
    • Single best setup only — ONE trade at a time
    • Full margin (100% available balance)
    • Max leverage 10x
    • SL ≤ 1.5% | RRR ≥ 1:2
    • Entry: OB + FVG + Liq Sweep (min 2/3) | OTE zone preferred
    • TP tiered: TP1 50% (liq pool) → TP2 50% (HTF FVG)
    • SL moves to breakeven after TP1
    • Danger exit: structure invalidation / pattern / BTC flip
    • After 2 losses → pause 1 candle cycle, reassess HTF
    • After each exit → immediate re-scan

Run:
    python -m bitunix_scanner.main           # scan only (one shot)
    python -m bitunix_scanner.main --live    # 24/7 autonomous mode
    python -m bitunix_scanner.main --live --top 20 --poll 30

Flags:
    --live     24/7 mode
    --top N    symbols to scan by volume (default 20)
    --poll N   AutoTrader poll seconds (default 30)
    --quiet    suppress scan output
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

RESCAN_WAIT     = 300   # seconds between scans when no signal found
POST_TRADE_WAIT = 30    # seconds after all positions closed before re-scan
ERROR_WAIT      = 60    # seconds after an unexpected error


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def parse_args():
    p = argparse.ArgumentParser(description="Bitunix ICT 24/7 advanced scalping")
    p.add_argument("--live",   action="store_true")
    p.add_argument("--top",    type=int, default=20)
    p.add_argument("--poll",   type=int, default=30)
    p.add_argument("--quiet",  action="store_true")
    return p.parse_args()


# ── load existing exchange positions ──────────────────────────────────────────

async def _load_existing_positions(client: AsyncBitunixClient,
                                   live_mgr: LiveManager) -> int:
    """Register any open exchange positions with LiveManager using tiered TP."""
    positions = await client.get_positions()
    if not positions:
        return 0

    tickers   = await client._get_public("/api/v1/futures/market/tickers")
    price_map = {t["symbol"]: float(t["lastPrice"])
                 for t in (tickers.get("data") or [])}

    added = 0
    for p in positions:
        sym = p["symbol"]
        if sym in live_mgr._positions:
            continue

        entry     = float(p["avgOpenPrice"])
        pos_id    = p["positionId"]
        qty_str   = str(p.get("qty", "0"))
        direction = "SHORT" if p["side"] in ("SELL", "SHORT") else "LONG"
        cur       = price_map.get(sym, entry)
        ict_dir   = "bearish" if direction == "SHORT" else "bullish"

        c5m = await client.get_klines(sym, "5m",  60)
        c1h = await client.get_klines(sym, "1h",  60)
        c4h = await client.get_klines(sym, "4h",  60)

        # SL: 30-candle swing with 0.1% buffer
        if c5m:
            swing_h = max(float(c["high"]) for c in c5m[-30:])
            swing_l = min(float(c["low"])  for c in c5m[-30:])
            sl = (max(swing_h, cur) * 1.001 if direction == "SHORT"
                  else min(swing_l, cur) * 0.999)
        else:
            liq = float(p.get("liqPrice", 0) or 0)
            sl  = liq * 0.97 if direction == "SHORT" else liq * 1.03

        # Tiered TP
        from .ict import find_tiered_tp
        tp1, tp2, tp1_r, tp2_r = find_tiered_tp(c1h, c4h, entry, ict_dir, sl)

        mp = ManagedPosition(
            symbol      = sym,
            direction   = direction,
            entry_price = entry,
            sl_price    = sl,
            tp1_price   = tp1,
            tp2_price   = tp2,
            ob_high     = sl,
            ob_low      = tp2,
            position_id = pos_id,
            qty         = qty_str,
        )
        live_mgr.add_position(mp)
        print(f"  [{_ts()}] 📡 {sym} {direction}  "
              f"entry={entry:.6g}  SL={sl:.6g}  "
              f"TP1={tp1:.6g} ({tp1_r})  TP2={tp2:.6g} ({tp2_r})")
        added += 1

    return added


# ── single trading cycle ──────────────────────────────────────────────────────

async def _run_cycle(client: AsyncBitunixClient,
                     args,
                     cycle: int,
                     trader_state: dict) -> str:
    """
    One cycle: load positions → scan → pick best → trade → monitor.
    Returns 'traded' | 'no_signal' | 'positions_only'.
    """
    print(f"\n  [{_ts()}]  ─── Cycle #{cycle} ───")

    live_mgr = LiveManager(client, poll_sec=15)

    n_existing = await _load_existing_positions(client, live_mgr)
    if n_existing:
        print(f"  [{_ts()}] 📋 {n_existing} existing position(s) loaded into LiveManager")

    # Scan
    print(f"  [{_ts()}] 🔍 Scanning top {args.top} symbols …")
    signals = await run_scan(
        API_KEY, SECRET_KEY,
        top_n    = args.top,
        progress = not args.quiet,
    )

    # Re-sync positions opened during scan
    n_new = await _load_existing_positions(client, live_mgr)
    if n_new:
        print(f"  [{_ts()}] 🔄 {n_new} new position(s) found after scan")

    if not signals:
        print(f"  [{_ts()}] ── No valid setup found this cycle")
        if live_mgr._positions:
            print(f"  [{_ts()}] 📡 Monitoring {len(live_mgr._positions)} existing position(s) …")
            await live_mgr.run()
        return "no_signal"

    # Show best setup
    best = signals[0]
    print(format_summary([best]))

    trader = AutoTrader(
        client,
        max_positions = 1,
        poll_sec      = args.poll,
        live_manager  = live_mgr,
    )
    # Restore consecutive loss state across cycles
    trader._consec_losses = trader_state.get("consec_losses", 0)
    trader._pause_until   = trader_state.get("pause_until",   0.0)

    trader.add_signals([best])   # only the single best signal

    await asyncio.gather(trader.run(), live_mgr.run())

    # Persist trader state
    trader_state["consec_losses"] = trader._consec_losses
    trader_state["pause_until"]   = trader._pause_until

    return "traded"


# ── 24/7 main loop ────────────────────────────────────────────────────────────

async def _live_loop(args):
    print(f"""
╔══════════════════════════════════════════════════════╗
║   BITUNIX  ·  ICT ADVANCED  ·  24/7 AUTONOMOUS     ║
║   Scope    : Top {args.top:<3} by volume                    ║
║   Mode     : 1 trade — FULL MARGIN                  ║
║   Entry    : OB + FVG + Liq Sweep (≥ 2/3)          ║
║   OTE      : 61.8%–79% Fibonacci preferred          ║
║   SL       : OB wick + 0.4% buffer  (max 1.5%)     ║
║   TP1(50%) : nearest liquidity pool (≥ 2:1)        ║
║   TP2(50%) : HTF FVG / OB  (≥ 3:1)                ║
║   Leverage : max 10x                                ║
║   Re-scan  : immediately after every exit           ║
╚══════════════════════════════════════════════════════╝
""")

    cycle        = 0
    trader_state = {}

    async with aiohttp.ClientSession() as session:
        client = AsyncBitunixClient(API_KEY, SECRET_KEY, session)

        while True:
            cycle += 1
            try:
                result = await _run_cycle(client, args, cycle, trader_state)

                if result == "no_signal":
                    print(f"\n  [{_ts()}] ⏳ No setup — rescanning in "
                          f"{RESCAN_WAIT // 60} min …\n")
                    await asyncio.sleep(RESCAN_WAIT)
                else:
                    print(f"\n  [{_ts()}] ✅ Cycle #{cycle} done — restarting in "
                          f"{POST_TRADE_WAIT}s …\n")
                    await asyncio.sleep(POST_TRADE_WAIT)

            except asyncio.CancelledError:
                raise
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"\n  [{_ts()}] ❌ Error in cycle #{cycle}: {e}")
                traceback.print_exc()
                print(f"  [{_ts()}] 🔄 Retrying in {ERROR_WAIT}s …\n")
                await asyncio.sleep(ERROR_WAIT)


# ── entry points ──────────────────────────────────────────────────────────────

async def _main():
    args = parse_args()

    import bitunix_scanner.scanner as sc
    sc.TOP_N_BY_VOLUME = args.top

    if args.live:
        try:
            await _live_loop(args)
        except (KeyboardInterrupt, asyncio.CancelledError):
            print(f"\n\n  [{_ts()}] ⛔ System stopped by user.\n")
        return

    # One-shot scan mode
    print("""
╔══════════════════════════════════════╗
║   BITUNIX  ·  ICT Advanced Scan     ║
║   Mode     : SCAN ONLY              ║
╚══════════════════════════════════════╝
""")
    async with aiohttp.ClientSession() as session:
        client  = AsyncBitunixClient(API_KEY, SECRET_KEY, session)
        signals = await run_scan(API_KEY, SECRET_KEY,
                                 top_n=args.top, progress=not args.quiet)
        if signals:
            print(format_summary(signals[:3]))  # show top 3
        else:
            print("\n  ── No valid setup found ──\n")


def main():
    asyncio.run(_main())


if __name__ == "__main__":
    main()
