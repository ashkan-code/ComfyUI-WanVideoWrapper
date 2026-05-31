"""
Bitunix ICT Scanner — تحلیل و نمایش، بدون اوردر.

فقط اسکن می‌کنه و سیگنال‌ها رو نشون میده — هیچ اوردری نمی‌ذاره.

Run:
    python -m bitunix_scanner.main           # یک اسکن
    python -m bitunix_scanner.main --live    # لوپ 24/7
    python -m bitunix_scanner.main --live --top 100 --poll 300

Flags:
    --live     حالت لوپ 24/7
    --top N    تعداد ارز برای اسکن بر اساس حجم (پیش‌فرض 100)
    --poll N   ثانیه‌های بین اسکن‌ها (پیش‌فرض 300)
    --quiet    بدون خروجی اضافه
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
from .scanner import run_scan
from .signals import Signal, _fmt, format_summary
from .spring_scanner import run_spring_scan

API_KEY    = os.getenv("BITUNIX_API_KEY",    "68f0a1765f124bacb847afa8db78e480")
SECRET_KEY = os.getenv("BITUNIX_SECRET_KEY", "159808597389a1cd1fc429f9f469209b")

RESCAN_WAIT       = 300    # seconds between scans
ERROR_WAIT        = 60     # seconds after an unexpected error
SPRING_SCAN_EVERY = 14400  # spring scan هر 4 ساعت یک بار (HTF event)


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def parse_args():
    p = argparse.ArgumentParser(description="Bitunix ICT Scanner — فقط تحلیل")
    p.add_argument("--live",   action="store_true", help="حالت لوپ 24/7")
    p.add_argument("--top",    type=int, default=100)
    p.add_argument("--poll",   type=int, default=300)
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


# ── single scan cycle (view only) ────────────────────────────────────────────

async def _run_cycle(client: AsyncBitunixClient,
                     args,
                     cycle: int) -> str:
    """
    یک چرخه اسکن — فقط تحلیل و نمایش، بدون اوردر.
    Returns 'found' | 'no_signal'
    """
    print(f"\n  [{_ts()}]  ─── Cycle #{cycle} ───")
    print(f"  [{_ts()}] 🔍 Scanning top {args.top} symbols …")

    signals = await run_scan(
        API_KEY, SECRET_KEY,
        top_n    = args.top,
        progress = not args.quiet,
    )

    if not signals:
        print(f"  [{_ts()}] ── هیچ سیگنالی پیدا نشد")
        return "no_signal"

    account   = await client.get_account()
    available = float(account.get("available", 0))

    for sig in signals:
        report = await _build_ict_report(client, sig, available)
        print(report)

    return "found"


# ── 24/7 main loop ────────────────────────────────────────────────────────────

async def _live_loop(args):
    print(f"""
╔══════════════════════════════════════════════════════╗
║   BITUNIX  ·  ICT Scanner  ·  24/7                ║
║   Scope    : Top {args.top:<3} by volume                    ║
║   Mode     : فقط تحلیل — بدون اوردر               ║
║   Bias     : 4H + 1H structure                      ║
║   ICT      : OB · FVG · Liq Sweep · OTE            ║
╚══════════════════════════════════════════════════════╝
""")

    import time as _time
    cycle            = 0
    last_spring_scan = 0.0

    async with aiohttp.ClientSession() as session:
        client = AsyncBitunixClient(API_KEY, SECRET_KEY, session)

        while True:
            cycle += 1
            try:
                # Spring scan: هر 4 ساعت یک بار
                now = _time.time()
                if now - last_spring_scan >= SPRING_SCAN_EVERY:
                    print(f"\n  [{_ts()}] 🔄 Wyckoff Spring scan (هر 4h) …")
                    await run_spring_scan(top_n=0, progress=True)
                    last_spring_scan = _time.time()

                result = await _run_cycle(client, args, cycle)

                wait = RESCAN_WAIT
                label = "اسکن بعدی" if result == "no_signal" else "تکرار"
                print(f"\n  [{_ts()}] ⏳ {label} در {wait // 60} دقیقه …\n")
                await asyncio.sleep(wait)

            except asyncio.CancelledError:
                raise
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"\n  [{_ts()}] ❌ خطا در cycle #{cycle}: {e}")
                traceback.print_exc()
                print(f"  [{_ts()}] 🔄 تلاش مجدد در {ERROR_WAIT}s …\n")
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
║   BITUNIX  ·  ICT Scanner           ║
║   فقط تحلیل — بدون اوردر            ║
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
