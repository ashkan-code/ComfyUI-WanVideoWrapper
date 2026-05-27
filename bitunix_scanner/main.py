"""
Bitunix ICT Advanced Scalping — 24/7 Autonomous System

Rules:
    • Top 20 symbols by volume
    • Single best setup only — ONE trade at a time
    • Full margin (100% available balance)
    • Max leverage 10x
    • SL ≤ 2.5% (structural: OB wick + 0.5%) | RRR ≥ 1:3
    • Entry: OB + FVG + Liq Sweep (min 2/3) | OTE zone preferred
    • Confirm: 15M candle must touch OB + close in direction → MARKET entry
    • TP single: 100% at HTF OB/FVG target (≥ 3:1 RRR)
    • Danger exit: structure invalidation / BTC flip
    • After 2 losses → pause 1 hour, reassess HTF
    • After each exit → immediate re-scan
    • Spread ≤ 0.12% required
    • Semi-manual: present analysis → ask confirmation → execute

Run:
    python -m bitunix_scanner.main           # scan only (one shot)
    python -m bitunix_scanner.main --live    # 24/7 with confirmation prompt
    python -m bitunix_scanner.main --live --auto  # fully autonomous (no prompt)
    python -m bitunix_scanner.main --live --top 20 --poll 30

Flags:
    --live     24/7 mode
    --auto     skip manual confirmation (fully autonomous)
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
from .ict import (
    market_structure,
    detect_candle_confirmation,
    detect_breaker_block,
    detect_mitigation_block,
    btc_ict_bias,
    detect_fvg,
    detect_liquidity_sweep,
    find_impulse_for_ote,
    find_ote_zone,
)
from .live_manager import LiveManager, ManagedPosition
from .scanner import run_scan
from .signals import Signal, _fmt, format_summary
from .spring_scanner import run_spring_scan
from .trader import AutoTrader

API_KEY    = os.getenv("BITUNIX_API_KEY",    "7bee3f4756a0dbc89ae152f34c2175ac")
SECRET_KEY = os.getenv("BITUNIX_SECRET_KEY", "4e0a845778d49068297106a64cbcda61")

RESCAN_WAIT       = 300    # seconds between scans when no signal found
POST_TRADE_WAIT   = 30     # seconds after all positions closed before re-scan
ERROR_WAIT        = 60     # seconds after an unexpected error
CONFIRM_TIMEOUT   = 120    # seconds to wait for user confirmation
SPRING_SCAN_EVERY = 14400  # spring scan هر 4 ساعت یک بار (HTF event)


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def parse_args():
    p = argparse.ArgumentParser(description="Bitunix ICT 24/7 advanced scalping")
    p.add_argument("--live",   action="store_true")
    p.add_argument("--auto",   action="store_true", help="skip confirmation prompt")
    p.add_argument("--top",    type=int, default=100)
    p.add_argument("--poll",   type=int, default=30)
    p.add_argument("--quiet",  action="store_true")
    return p.parse_args()


# ── ICT analysis output formatter ─────────────────────────────────────────────

async def _build_ict_report(client: AsyncBitunixClient,
                             signal: Signal,
                             available_usdt: float) -> str:
    """
    Build the structured ICT multi-timeframe analysis report.
    """
    sym     = signal.symbol
    ict_dir = "bearish" if signal.direction == "SHORT" else "bullish"

    # Fetch extra klines for the report
    c1d  = await client.get_klines(sym, "1d",  60)
    c4h  = await client.get_klines(sym, "4h",  60)
    c15m = await client.get_klines(sym, "15m", 60)
    c5m  = await client.get_klines(sym, "5m",  30)

    # Structure on each TF
    daily_ms = market_structure(c1d,  lookback=40)
    h4_ms    = market_structure(c4h,  lookback=40)
    m15_ms   = market_structure(c15m, lookback=30)

    # Key levels
    fvgs_1h = detect_fvg(await client.get_klines(sym, "1h", 60), ict_dir)
    fvg_str = f"{_fmt(fvgs_1h[0][0])}–{_fmt(fvgs_1h[0][1])}" if fvgs_1h else "—"

    liq_ok, liq_detail = detect_liquidity_sweep(c15m, ict_dir)

    bb = detect_breaker_block(c4h, "4h")
    bb_str = _fmt(bb[0].ob_high) + "–" + _fmt(bb[0].ob_low) if bb else "—"

    mb = detect_mitigation_block(c4h, "4h", ict_dir)
    mb_str = (f"{_fmt(mb.ob_low)}–{_fmt(mb.ob_high)}"
              if mb else "—")

    # 15M candle state (last completed)
    candle_ok, candle_name = False, "—"
    if c15m and len(c15m) >= 2:
        c15 = c15m[-2]
        o15, h15, l15, cl15 = (float(c15["open"]), float(c15["high"]),
                                float(c15["low"]), float(c15["close"]))
        if signal.direction == "SHORT":
            candle_ok = h15 >= signal.zone.price_low * 0.997 and cl15 < o15
        else:
            candle_ok = l15 <= signal.zone.price_high * 1.003 and cl15 > o15
        candle_name = f"15M {'bearish' if signal.direction=='SHORT' else 'bullish'} OB touch"

    # OTE check
    sw_lo, sw_hi = find_impulse_for_ote(c15m, ict_dir)
    ote_lo, ote_hi = find_ote_zone(sw_lo, sw_hi, ict_dir)
    cur_price = float(c5m[-1]["close"]) if c5m else signal.entry
    ote_in = ote_lo <= cur_price <= ote_hi

    # Spread
    if c5m:
        avg_spread = (float(c5m[-1]["high"]) - float(c5m[-1]["low"])) / float(c5m[-1]["close"]) * 100
    else:
        avg_spread = 0.0

    arrow = "▲ LONG" if signal.direction == "LONG" else "▼ SHORT"
    icon  = "🟢" if signal.direction == "LONG" else "🔴"

    # Confluence checks string
    checks = []
    checks.append("✅ OB" if signal.zone else "❌ OB")
    checks.append("✅ FVG" if signal.fvg_ok else "❌ FVG")
    checks.append("✅ Liq Sweep" if signal.liq_swept else "❌ Liq Sweep")
    checks.append("✅ OTE" if (signal.ote_ok or ote_in) else "⬜ OTE")
    checks.append(f"✅ {signal.mss_detail}" if signal.mss_ok else "❌ BOS/MSS")
    checks.append(f"✅ {candle_name}" if candle_ok else "⬜ 15M confirm pending")
    checks_str = "  ".join(checks)

    sl_pct_str = (f"-{signal.loss_pct:.3f}%"
                  if signal.direction == "LONG"
                  else f"+{signal.loss_pct:.3f}%")

    # Danger warning
    if avg_spread > 0.12:
        spread_warn = f"  ⚠️  Spread {avg_spread:.3f}% — above 0.12% threshold!\n"
    else:
        spread_warn = f"  Spread {avg_spread:.3f}% ✓\n"

    # Entry reason summary
    reasons = []
    if signal.zone:
        tfs = " + ".join(signal.zone.timeframes)
        reasons.append(f"Confluent OB [{tfs}] score {signal.zone.score}/21")
    if signal.fvg_ok:
        reasons.append("FVG مشاهده شد روی ۱H")
    if signal.liq_swept:
        reasons.append(f"Liquidity sweep: {signal.liq_detail}")
    if signal.mss_ok:
        reasons.append(f"Structure shift: {signal.mss_detail}")
    if ote_in or signal.ote_ok:
        reasons.append(f"قیمت در OTE zone ({_fmt(ote_lo)}–{_fmt(ote_hi)})")
    if candle_ok:
        reasons.append(f"تأیید ۱۵m: {candle_name}")
    if bb_str != "—":
        reasons.append(f"Breaker Block 4H: {bb_str}")
    reason_text = "\n".join(f"    • {r}" for r in reasons) if reasons else "    • ICT confluence detected"

    # Risk management
    risk_lines = []
    if not signal.fvg_ok:
        risk_lines.append("FVG تأیید نشده — احتمال ورود زودهنگام بالاتر")
    if not candle_ok:
        risk_lines.append("تأیید ۱۵m هنوز نیامده — منتظر بسته شدن کندل ۱۵m در منطقه OB")
    if avg_spread > 0.08:
        risk_lines.append(f"اسپرد {avg_spread:.3f}% — لبه تریدینگ را کاهش می‌دهد")
    if signal.quality_score < 60:
        risk_lines.append(f"کیفیت سیگنال پایین ({signal.quality_score:.0f}/100) — با احتیاط")
    risk_lines.append("اگر قیمت از OB خارج شد یا BTC ساختار تغییر داد → فوری ببند")
    risk_text = "\n".join(f"    • {r}" for r in risk_lines)

    report = f"""
{'═'*56}
  {icon}  تحلیل ICT  ─  {signal.symbol}
{'═'*56}

  **تحلیل مولتی تایم فریم:**
  - Daily Bias : {daily_ms.upper()}
  - 4H Bias    : {h4_ms.upper()}
  - 15m Bias   : {m15_ms.upper()}
  - Key Levels : OB {_fmt(signal.zone.price_low)}–{_fmt(signal.zone.price_high)}  |  FVG {fvg_str}  |  Liq: {liq_detail or '—'}
  - Breaker BB : {bb_str}
  - Mitigation : {mb_str}

  Coin         : {signal.symbol}
  Direction    : {arrow}
  Leverage     : {signal.leverage}x  (max 10x)
  Margin       : 100% — {available_usdt:.2f} USDT available
  Entry        : MARKET after 15M confirmation
  Stop Loss    : {_fmt(signal.sl)}  ({sl_pct_str})  ← OB wick + 0.5% structural
  TP (100%)    : {_fmt(signal.tp1)}  ← {signal.tp1_reason}
  RRR          : 1:{signal.rr1:.1f}
  Quality      : {signal.quality_score:.0f}/100
{spread_warn}
  **چک‌لیست ICT:**
  {checks_str}

  **دلیل ورود (ICT):**
{reason_text}

  **ریسک و مدیریت:**
{risk_text}

{'═'*56}"""
    return report


async def _ask_confirm(timeout: int = CONFIRM_TIMEOUT) -> bool:
    """
    Async confirmation prompt with timeout.
    Returns True if user confirms, False otherwise.
    """
    print(f"\n  ❓ تایید می‌کنی؟ (بله/خیر)  [{timeout}s timeout → auto-skip]\n", flush=True)

    loop = asyncio.get_event_loop()
    try:
        answer = await asyncio.wait_for(
            loop.run_in_executor(None, input, "  > "),
            timeout=timeout,
        )
        ans = answer.strip().lower()
        if ans in ("بله", "yes", "y", "آره", "ok", "1", "✓", "تایید"):
            return True
        print(f"  ⏩ رد شد: '{answer}'\n")
        return False
    except asyncio.TimeoutError:
        print(f"\n  ⏱️  {timeout}s گذشت — سیگنال رد شد (timeout)\n")
        return False
    except EOFError:
        # Non-interactive environment — auto-skip
        print("  ⚠️  محیط غیر تعاملی — سیگنال رد شد\n")
        return False


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
    One cycle: load positions → scan → pick best → [confirm] → trade → monitor.
    Returns 'traded' | 'no_signal' | 'skipped' | 'positions_only'.
    """
    print(f"\n  [{_ts()}]  ─── Cycle #{cycle} ───")

    live_mgr = LiveManager(client, poll_sec=3600)

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

    # Best signal
    best = signals[0]

    # Account balance for report
    account   = await client.get_account()
    available = float(account.get("available", 0))

    # Build and print the structured ICT report
    report = await _build_ict_report(client, best, available)
    print(report)

    # Semi-manual confirmation (unless --auto)
    if not args.auto:
        confirmed = await _ask_confirm()
        if not confirmed:
            if live_mgr._positions:
                print(f"  [{_ts()}] 📡 Monitoring {len(live_mgr._positions)} existing position(s) …")
                await live_mgr.run()
            return "skipped"

    trader = AutoTrader(
        client,
        max_positions = 1,
        poll_sec      = args.poll,
        live_manager  = live_mgr,
    )
    trader._consec_losses = trader_state.get("consec_losses", 0)
    trader._pause_until   = trader_state.get("pause_until",   0.0)

    trader.add_signals(signals)   # all signals ranked by quality — trader tries each on fail

    await asyncio.gather(trader.run(), live_mgr.run())

    trader_state["consec_losses"] = trader._consec_losses
    trader_state["pause_until"]   = trader._pause_until

    return "traded"


# ── 24/7 main loop ────────────────────────────────────────────────────────────

async def _live_loop(args):
    mode_tag = "AUTONOMOUS" if args.auto else "SEMI-MANUAL (تایید قبل از ورود)"
    print(f"""
╔══════════════════════════════════════════════════════╗
║   BITUNIX  ·  ICT SNIPER  ·  24/7                 ║
║   Scope    : Top {args.top:<3} by volume                    ║
║   Mode     : {mode_tag:<40}║
║   Bias     : 4H + 1H structure                      ║
║   Entry    : MARKET after 15M candle confirm        ║
║   OTE      : 61.8%–78.6% Fibonacci zone             ║
║   SL       : OB wick + 0.5%  (max 2.5%)            ║
║   Spread   : max 0.25%                              ║
║   TP (100%): HTF FVG / OB  (≥ 3:1 RRR)            ║
║   Leverage : max 10x                                ║
║   Pause    : 1 hour after 2 consecutive losses      ║
╚══════════════════════════════════════════════════════╝
""")

    cycle             = 0
    trader_state      = {}
    last_spring_scan  = 0.0   # timestamp آخرین spring scan

    async with aiohttp.ClientSession() as session:
        client = AsyncBitunixClient(API_KEY, SECRET_KEY, session)

        while True:
            cycle += 1
            try:
                # Spring scan: فقط هر 4 ساعت یک بار (نه هر 5 دقیقه)
                import time as _time
                now = _time.time()
                if now - last_spring_scan >= SPRING_SCAN_EVERY:
                    print(f"\n  [{_ts()}] 🔄 Wyckoff Spring scan (هر 4h) …")
                    await run_spring_scan(top_n=0, progress=True)
                    last_spring_scan = _time.time()

                result = await _run_cycle(client, args, cycle, trader_state)

                if result == "no_signal":
                    print(f"\n  [{_ts()}] ⏳ No setup — rescanning in "
                          f"{RESCAN_WAIT // 60} min …\n")
                    await asyncio.sleep(RESCAN_WAIT)
                elif result == "skipped":
                    print(f"\n  [{_ts()}] ⏩ Skipped — rescanning in "
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
            account   = await client.get_account()
            available = float(account.get("available", 0))
            for sig in signals[:3]:
                report = await _build_ict_report(client, sig, available)
                print(report)
        else:
            print("\n  ── No valid setup found ──\n")


def main():
    asyncio.run(_main())


if __name__ == "__main__":
    main()
