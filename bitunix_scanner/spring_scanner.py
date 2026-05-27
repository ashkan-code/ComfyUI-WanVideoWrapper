"""
Wyckoff Spring / Upthrust Scanner — جداگانه از اسکن ICT اصلی.

جریان:
  ۱. BTC تحلیل میشه — فقط اگه جهت واضح داشت ادامه میده
  ۲. top N ارز اسکن میشن برای الگوی Spring/Upthrust روی 1H و 15M
  ۳. هر سیگنال پیدا شد → تحلیل کامل نمایش داده میشه
  ۴. از کاربر تأیید گرفته میشه (همیشه — حتی در حالت auto)
  ۵. بعد از تأیید → MARKET ورود

این اسکنر هرگز بدون تأیید دستی وارد نمیشه.
"""

import asyncio
import math
import os
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import aiohttp

from .client import AsyncBitunixClient
from .ict import (
    _parse_klines,
    _swing_highs, _swing_lows,
    btc_ict_bias,
    detect_wyckoff_spring,
    find_tiered_tp,
    market_structure,
)
from .signals import _fmt

API_KEY    = os.getenv("BITUNIX_API_KEY",    "7bee3f4756a0dbc89ae152f34c2175ac")
SECRET_KEY = os.getenv("BITUNIX_SECRET_KEY", "4e0a845778d49068297106a64cbcda61")

SPRING_TFS    = ["1h", "15m"]   # تایم‌فریم‌های چک فنر
TOP_N         = 100
MAX_LEVERAGE  = 10
SL_BUFFER_PCT = 0.005           # 0.5% فراتر از پایین‌ترین wick فنر


@dataclass
class SpringSignal:
    symbol:    str
    direction: str        # 'LONG' | 'SHORT'
    tf:        str        # تایم‌فریم که فنر روش پیدا شد
    level:     float      # سطح Equal Lows/Highs
    swept:     float      # تا کجا رفت (wick)
    entry:     float      # قیمت الان (MARKET)
    sl:        float      # حد ضرر ساختاری
    tp:        float      # تارگت
    rr:        float      # R:R
    leverage:  int
    loss_pct:  float
    detail:    dict
    btc_bias:  str
    btc_detail: str


def _floor_lev(lev: float) -> int:
    return max(1, min(MAX_LEVERAGE, math.floor(lev)))


def _fmt_price(price: float) -> str:
    if price >= 1000: return f"{price:,.2f}"
    if price >= 1:    return f"{price:.4f}"
    return f"{price:.6f}"


async def _scan_spring(client: AsyncBitunixClient,
                       symbol: str, price: float,
                       btc_bias: str, btc_detail: str,
                       direction: str) -> Optional[SpringSignal]:
    """یه ارز رو برای فنر اسکن کن."""

    for tf in SPRING_TFS:
        raw = await client.get_klines(symbol, tf, 80)
        if not raw:
            continue

        found, detail = detect_wyckoff_spring(raw, direction)
        if not found:
            continue

        klines = _parse_klines(raw)
        if not klines:
            continue

        # SL: پایین‌تر از wick فنر + بافر (LONG) یا بالاتر (SHORT)
        if direction == "LONG":
            sl       = detail["swept"] * (1 - SL_BUFFER_PCT)
            loss_pct = (price - sl) / price * 100
        else:
            sl       = detail["swept"] * (1 + SL_BUFFER_PCT)
            loss_pct = (sl - price) / price * 100

        if loss_pct <= 0 or loss_pct > 3.0:
            continue

        # TP: از کندل‌های 1H/4H
        raw1h = await client.get_klines(symbol, "1h", 80)
        raw4h = await client.get_klines(symbol, "4h", 80)
        ict_dir = "bullish" if direction == "LONG" else "bearish"

        try:
            _near, far, _nr, far_reason = find_tiered_tp(
                raw1h, raw4h, price, ict_dir, sl, min_rr=3.0
            )
            tp = far
        except Exception:
            risk = abs(price - sl)
            tp = (price + risk * 4.0) if direction == "LONG" else (price - risk * 4.0)
            far_reason = "4:1 fallback"

        rr = abs(tp - price) / abs(sl - price) if sl != price else 0
        if rr < 3.0:
            continue

        leverage = _floor_lev(15 / loss_pct)

        return SpringSignal(
            symbol    = symbol,
            direction = direction,
            tf        = tf,
            level     = detail["level"],
            swept     = detail["swept"],
            entry     = price,
            sl        = sl,
            tp        = tp,
            rr        = rr,
            leverage  = leverage,
            loss_pct  = loss_pct,
            detail    = detail,
            btc_bias  = btc_bias,
            btc_detail= btc_detail,
        )

    return None


def _format_spring(sig: SpringSignal) -> str:
    icon  = "🟢" if sig.direction == "LONG" else "🔴"
    kind  = sig.detail.get("type", "Spring")
    age   = sig.detail.get("age", 0)

    if sig.direction == "LONG":
        eq1  = _fmt_price(sig.detail.get("eq_lo1", 0))
        eq2  = _fmt_price(sig.detail.get("eq_lo2", 0))
        eq_label = f"Equal Lows: {eq1} ≈ {eq2}"
    else:
        eq1  = _fmt_price(sig.detail.get("eq_hi1", 0))
        eq2  = _fmt_price(sig.detail.get("eq_hi2", 0))
        eq_label = f"Equal Highs: {eq1} ≈ {eq2}"

    sl_pct = f"-{sig.loss_pct:.2f}%" if sig.direction == "LONG" else f"+{sig.loss_pct:.2f}%"
    tp_pct = (sig.tp - sig.entry) / sig.entry * 100

    return f"""
{'━'*54}
  {icon} Wyckoff {kind}  ─  {sig.symbol}  [{sig.tf}]
{'━'*54}
  BTC Bias  : {sig.btc_bias.upper()}  [{sig.btc_detail}]
  Direction : {sig.direction}
  ─────────────────────────────────────────────
  {eq_label}
  Swept به  : {_fmt_price(sig.swept)}  ({age} کندل پیش)
  Level     : {_fmt_price(sig.level)}
  ─────────────────────────────────────────────
  Entry     : MARKET  ~{_fmt_price(sig.entry)}
  Stop Loss : {_fmt_price(sig.sl)}  ({sl_pct})  ← زیر wick فنر
  TP (100%) : {_fmt_price(sig.tp)}  ({tp_pct:+.2f}%)
  RRR       : 1:{sig.rr:.1f}
  Leverage  : {sig.leverage}x
{'━'*54}"""


async def _ask(timeout: int = 120) -> bool:
    print(f"\n  ❓ این فنر رو تأیید میکنی؟  بله / خیر  [{timeout}s]\n", flush=True)
    loop = asyncio.get_event_loop()
    try:
        ans = await asyncio.wait_for(
            loop.run_in_executor(None, input, "  > "),
            timeout=timeout,
        )
        return ans.strip().lower() in ("بله", "yes", "y", "آره", "ok", "1", "تایید")
    except (asyncio.TimeoutError, EOFError):
        print("  ⏱️  timeout — رد شد\n")
        return False


async def _execute_spring(client: AsyncBitunixClient,
                          sig: SpringSignal) -> bool:
    """بعد از تأیید کاربر → MARKET ورود + TP LIMIT."""
    await client.set_leverage(sig.symbol, sig.leverage)

    acc   = await client.get_account()
    avail = float(acc.get("available", 0))
    if avail < 1:
        print("  ❌ موجودی ناکافی"); return False

    margin = avail * 0.95
    notional = margin * sig.leverage
    price    = sig.entry

    if price >= 1000:
        qty_f = math.floor(notional / price * 1000) / 1000
        qty   = f"{qty_f:.3f}" if qty_f >= 0.001 else None
    elif price >= 1:
        qty_f = math.floor(notional / price * 100) / 100
        qty   = f"{qty_f:.2f}".rstrip("0").rstrip(".") if qty_f >= 0.01 else None
    else:
        qty_f = math.floor(notional / price)
        qty   = str(int(qty_f)) if qty_f >= 1 else None

    if not qty:
        print("  ❌ حجم خیلی کم"); return False

    side = "SELL" if sig.direction == "SHORT" else "BUY"
    body = {
        "symbol":      sig.symbol,
        "qty":         qty,
        "side":        side,
        "tradeSide":   "OPEN",
        "orderType":   "MARKET",
        "slPrice":     _fmt_price(sig.sl),
        "slStopType":  "MARK_PRICE",
        "slOrderType": "MARKET",
    }

    r = await client._post("/api/v1/futures/trade/place_order", body)
    if r.get("code") != 0 and "sl" in str(r.get("msg", "")).lower():
        for k in ("slPrice", "slStopType", "slOrderType"): body.pop(k, None)
        r = await client._post("/api/v1/futures/trade/place_order", body)

    if r.get("code") != 0:
        print(f"  ❌ خطا: {r.get('msg')}"); return False

    oid = r["data"]["orderId"]
    print(f"\n  ✅ MARKET {sig.direction} PLACED  orderId={oid}")

    # صبر برای fill
    pos = None
    for _w in (2, 3, 5, 8):
        await asyncio.sleep(_w)
        positions = await client.get_positions()
        pos = next((p for p in positions if p["symbol"] == sig.symbol), None)
        if pos: break

    if pos:
        pos_id  = pos["positionId"]
        act_qty = pos["qty"]
        tp_side = "BUY" if sig.direction == "SHORT" else "SELL"
        tp_body = {
            "symbol":     sig.symbol,
            "qty":        str(act_qty),
            "side":       tp_side,
            "tradeSide":  "CLOSE",
            "orderType":  "LIMIT",
            "price":      _fmt_price(sig.tp),
            "positionId": pos_id,
        }
        tp_r = await client._post("/api/v1/futures/trade/place_order", tp_body)
        if tp_r.get("code") == 0:
            print(f"  🎯 TP LIMIT @ {_fmt_price(sig.tp)}  orderId={tp_r['data']['orderId']}")
        else:
            print(f"  ⚠️  TP failed: {tp_r.get('msg')}")

    return True


async def run_spring_scan(top_n: int = TOP_N,
                          progress: bool = True) -> None:
    """
    اسکن فنر — مستقل از اسکن ICT اصلی.
    همیشه قبل از ورود از کاربر تأیید میگیره.
    """
    async with aiohttp.ClientSession() as session:
        client = AsyncBitunixClient(API_KEY, SECRET_KEY, session)

        # BTC bias
        btc_tf = {tf: await client.get_klines("BTCUSDT", tf, 100)
                  for tf in ("4h", "1h", "1d")}
        btc_bias, btc_detail = btc_ict_bias(btc_tf)

        if btc_bias == "neutral":
            if progress:
                print("  🟡 [Spring] BTC بی‌تصمیمه — اسکن فنر skip")
            return

        direction = "LONG" if btc_bias == "bullish" else "SHORT"
        ict_dir   = "bullish" if direction == "LONG" else "bearish"

        if progress:
            icon = "🟢" if direction == "LONG" else "🔴"
            print(f"\n  {icon} [Spring Scan] BTC={btc_bias.upper()} → دنبال"
                  f" {'Spring 🔄' if direction=='LONG' else 'Upthrust 🔄'} می‌گردیم …\n")

        # top N ارز
        tickers = await client.get_all_tickers()
        for t in tickers:
            try: t["_vol"] = float(t.get("baseVol", 0))
            except: t["_vol"] = 0.0

        top = sorted(tickers, key=lambda x: x["_vol"], reverse=True)[:top_n]
        price_map = {t["symbol"]: float(t["lastPrice"])
                     for t in top if t.get("lastPrice")}

        found: List[SpringSignal] = []
        tasks = [
            _scan_spring(client, sym, price_map[sym], btc_bias, btc_detail, direction)
            for sym in price_map
        ]
        done = 0
        for coro in asyncio.as_completed(tasks):
            result = await coro
            done  += 1
            if result:
                found.append(result)
            if progress and done % 20 == 0:
                print(f"  [Spring] {done}/{len(tasks)}  یافته: {len(found)}", flush=True)

        if not found:
            if progress:
                print("  [Spring] هیچ فنری پیدا نشد این سایکل\n")
            return

        # مرتب‌سازی: RRR بالاتر اول
        found.sort(key=lambda s: s.rr, reverse=True)

        if progress:
            print(f"\n  [Spring] {len(found)} فنر پیدا شد:\n")

        for sig in found[:3]:
            print(_format_spring(sig))
            confirmed = await _ask()
            if confirmed:
                ok = await _execute_spring(client, sig)
                if ok:
                    print(f"\n  ✅ فنر {sig.symbol} وارد شد — منتظر تارگت\n")
                    return
            else:
                print(f"  ⏩ {sig.symbol} رد شد\n")
