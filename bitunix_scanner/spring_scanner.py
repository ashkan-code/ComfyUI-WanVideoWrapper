"""
Wyckoff Spring / Upthrust Scanner — همه ارزهای Bitunix.

جریان:
  ۱. BTC تحلیل — اگه neutral بود skip
  ۲. همه ۶۳۵ ارز اسکن میشن (concurrent, batched)
  ۳. هر سیگنال امتیازدهی میشه (0–100)
  ۴. top 5 بالاترین امتیاز نمایش داده میشن
  ۵. کاربر هر کدوم رو تأیید یا رد میکنه
  ۶. بعد از تأیید → MARKET ورود

هرگز بدون تأیید دستی ورود نمیزنه.
"""

import asyncio
import math
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import aiohttp

from .client import AsyncBitunixClient
from .ict import (
    _parse_klines,
    _swing_highs, _swing_lows,
    _atr_vals,
    btc_ict_bias,
    detect_wyckoff_spring,
    detect_fvg,
    market_structure,
    find_tiered_tp,
)
from .signals import _fmt

API_KEY    = os.getenv("BITUNIX_API_KEY",    "7bee3f4756a0dbc89ae152f34c2175ac")
SECRET_KEY = os.getenv("BITUNIX_SECRET_KEY", "4e0a845778d49068297106a64cbcda61")

SPRING_TFS   = ["1h", "15m"]
SL_BUFFER    = 0.005     # 0.5% فراتر از wick
MIN_RR       = 3.0
BATCH_SIZE   = 30        # همزمان چند ارز
SHOW_TOP     = 5         # نمایش top N
CONFIRM_SEC  = 180       # ثانیه timeout تأیید


@dataclass
class SpringSignal:
    symbol:     str
    direction:  str       # LONG | SHORT
    tf:         str
    level:      float     # Equal Lows/Highs level
    swept:      float     # تا کجا wick رفت
    age:        int       # چند کندل پیش
    entry:      float
    sl:         float
    tp:         float
    rr:         float
    leverage:   int
    loss_pct:   float
    score:      float     # 0–100
    score_detail: str
    detail:     dict = field(default_factory=dict)
    btc_bias:   str  = ""
    btc_detail: str  = ""


# ── امتیازدهی ────────────────────────────────────────────────────────────────

def _score_spring(sig: SpringSignal,
                  raw1h: list, raw4h: list,
                  ict_dir: str) -> Tuple[float, str]:
    """
    امتیاز 0–100 برای رتبه‌بندی:
      TF weight       : 1H=20  15M=10
      wick/body ratio : max 20
      recency         : max 15  (تازه‌تر = بهتر)
      Equal tightness : max 10  (کف‌های مساوی‌تر = نقدینگی بیشتر)
      4H alignment    : 15
      FVG در جهت      : 10
      RRR             : max 10
    """
    parts = []
    score = 0.0

    # TF weight
    tf_pts = 20 if sig.tf == "1h" else 10
    score += tf_pts
    parts.append(f"TF={tf_pts}")

    # wick/body ratio
    c = sig.detail.get("candle", {})
    if c:
        body = abs(float(c.get("close", 0)) - float(c.get("open", 0)))
        if sig.direction == "LONG":
            wick = min(float(c.get("open", 0)), float(c.get("close", 0))) - float(c.get("low", 0))
        else:
            wick = float(c.get("high", 0)) - max(float(c.get("open", 0)), float(c.get("close", 0)))
        ratio = wick / body if body > 0 else 0
        wk_pts = min(ratio / 4.0, 1.0) * 20
        score += wk_pts
        parts.append(f"wick={wk_pts:.0f}")

    # recency (age 0–10 candles: 15pts → 0pts)
    age = sig.age
    rec_pts = max(0, 15 - age * 1.5)
    score += rec_pts
    parts.append(f"age={rec_pts:.0f}")

    # Equal tightness
    if sig.direction == "LONG":
        l1 = sig.detail.get("eq_lo1", sig.level)
        l2 = sig.detail.get("eq_lo2", sig.level)
    else:
        l1 = sig.detail.get("eq_hi1", sig.level)
        l2 = sig.detail.get("eq_hi2", sig.level)
    tightness = abs(l1 - l2) / sig.level if sig.level > 0 else 0.003
    eq_pts = max(0, (0.003 - tightness) / 0.003) * 10
    score += eq_pts
    parts.append(f"eq={eq_pts:.0f}")

    # 4H alignment
    if raw4h:
        ms4 = market_structure(raw4h, lookback=40)
        if ms4 == ict_dir:
            score += 15
            parts.append("4H=✅15")
        elif ms4 == "neutral":
            score += 7
            parts.append("4H=🟡7")

    # FVG در جهت روی 1H
    if raw1h:
        fvgs = detect_fvg(raw1h, ict_dir)
        if fvgs:
            score += 10
            parts.append("FVG=✅10")

    # RRR
    rr_pts = min(sig.rr / 6.0, 1.0) * 10
    score += rr_pts
    parts.append(f"RR={rr_pts:.0f}")

    return min(score, 100.0), " | ".join(parts)


# ── اسکن یک ارز ──────────────────────────────────────────────────────────────

async def _scan_one(client: AsyncBitunixClient,
                    symbol: str, price: float,
                    btc_bias: str, btc_detail: str,
                    direction: str,
                    ict_dir: str) -> Optional[SpringSignal]:

    raw4h = await client.get_klines(symbol, "4h", 80)
    raw1h = await client.get_klines(symbol, "1h", 80)

    best: Optional[SpringSignal] = None

    for tf, raw in [("1h", raw1h), ("15m", None)]:
        if tf == "15m":
            raw = await client.get_klines(symbol, "15m", 80)
        if not raw:
            continue

        found, detail = detect_wyckoff_spring(raw, ict_dir)
        if not found:
            continue

        # SL
        if direction == "LONG":
            sl       = detail["swept"] * (1 - SL_BUFFER)
            loss_pct = (price - sl) / price * 100
        else:
            sl       = detail["swept"] * (1 + SL_BUFFER)
            loss_pct = (sl - price) / price * 100

        if loss_pct <= 0 or loss_pct > 3.5:
            continue

        # TP
        try:
            _n, far, _nr, _fr = find_tiered_tp(raw1h, raw4h, price, ict_dir, sl, min_rr=MIN_RR)
            tp = far
        except Exception:
            risk = abs(price - sl)
            tp = (price + risk * 4) if direction == "LONG" else (price - risk * 4)

        rr = abs(tp - price) / abs(sl - price) if sl != price else 0
        if rr < MIN_RR:
            continue

        leverage = max(1, min(10, math.floor(15 / loss_pct)))

        sig = SpringSignal(
            symbol    = symbol,
            direction = direction,
            tf        = tf,
            level     = detail["level"],
            swept     = detail["swept"],
            age       = detail.get("age", 0),
            entry     = price,
            sl        = sl,
            tp        = tp,
            rr        = rr,
            leverage  = leverage,
            loss_pct  = loss_pct,
            score     = 0.0,
            score_detail = "",
            detail    = detail,
            btc_bias  = btc_bias,
            btc_detail= btc_detail,
        )

        score, score_detail = _score_spring(sig, raw1h, raw4h, ict_dir)
        sig.score        = score
        sig.score_detail = score_detail

        # 1H بهتر از 15M — فقط بهترین رو نگه دار
        if best is None or sig.score > best.score:
            best = sig

    return best


# ── فرمت نمایش ───────────────────────────────────────────────────────────────

def _bar(score: float) -> str:
    filled = round(score / 10)
    return "█" * filled + "░" * (10 - filled)


def _fmt_price(p: float) -> str:
    if p >= 1000: return f"{p:,.2f}"
    if p >= 1:    return f"{p:.4f}"
    return f"{p:.6f}"


def _format_spring(rank: int, sig: SpringSignal) -> str:
    icon  = "🟢" if sig.direction == "LONG" else "🔴"
    kind  = sig.detail.get("type", "Spring")

    if sig.direction == "LONG":
        eq1 = _fmt_price(sig.detail.get("eq_lo1", sig.level))
        eq2 = _fmt_price(sig.detail.get("eq_lo2", sig.level))
        eq_label = f"Equal Lows : {eq1} ≈ {eq2}"
    else:
        eq1 = _fmt_price(sig.detail.get("eq_hi1", sig.level))
        eq2 = _fmt_price(sig.detail.get("eq_hi2", sig.level))
        eq_label = f"Equal Highs: {eq1} ≈ {eq2}"

    sl_pct = f"-{sig.loss_pct:.2f}%" if sig.direction == "LONG" else f"+{sig.loss_pct:.2f}%"
    tp_pct = (sig.tp - sig.entry) / sig.entry * 100

    return f"""
{'━'*56}
  #{rank}  {icon} {kind}  ─  {sig.symbol}  [{sig.tf.upper()}]
  امتیاز: {sig.score:.0f}/100  {_bar(sig.score)}
{'━'*56}
  BTC       : {sig.btc_bias.upper()}  {sig.btc_detail}
  {eq_label}
  Swept به  : {_fmt_price(sig.swept)}  ({sig.age} کندل پیش)
  ─────────────────────────────────────────────────
  Entry     : MARKET  ~{_fmt_price(sig.entry)}
  Stop Loss : {_fmt_price(sig.sl)}  ({sl_pct})
  TP (100%) : {_fmt_price(sig.tp)}  ({tp_pct:+.2f}%)
  RRR       : 1:{sig.rr:.1f}
  Leverage  : {sig.leverage}x  |  SL={sig.loss_pct:.2f}%
  ─────────────────────────────────────────────────
  امتیاز    : {sig.score_detail}
{'━'*56}"""


# ── confirm ───────────────────────────────────────────────────────────────────

async def _ask(sym: str, timeout: int = CONFIRM_SEC) -> bool:
    print(f"\n  ❓ {sym} — وارد بشم؟  بله / خیر  [{timeout}s timeout]\n", flush=True)
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


# ── execute ───────────────────────────────────────────────────────────────────

async def _execute(client: AsyncBitunixClient, sig: SpringSignal) -> bool:
    await client.set_leverage(sig.symbol, sig.leverage)
    acc   = await client.get_account()
    avail = float(acc.get("available", 0))
    if avail < 1:
        print("  ❌ موجودی ناکافی"); return False

    margin   = avail * 0.95
    notional = margin * sig.leverage
    p        = sig.entry

    if p >= 1000:
        qf = math.floor(notional / p * 1000) / 1000
        qty = f"{qf:.3f}" if qf >= 0.001 else None
    elif p >= 1:
        qf = math.floor(notional / p * 100) / 100
        qty = f"{qf:.2f}".rstrip("0").rstrip(".") if qf >= 0.01 else None
    else:
        qf = math.floor(notional / p)
        qty = str(int(qf)) if qf >= 1 else None

    if not qty:
        print("  ❌ حجم خیلی کم"); return False

    side = "SELL" if sig.direction == "SHORT" else "BUY"
    body = {
        "symbol": sig.symbol, "qty": qty, "side": side,
        "tradeSide": "OPEN", "orderType": "MARKET",
        "slPrice": _fmt_price(sig.sl),
        "slStopType": "MARK_PRICE", "slOrderType": "MARKET",
    }
    r = await client._post("/api/v1/futures/trade/place_order", body)
    if r.get("code") != 0 and "sl" in str(r.get("msg", "")).lower():
        for k in ("slPrice", "slStopType", "slOrderType"): body.pop(k, None)
        r = await client._post("/api/v1/futures/trade/place_order", body)

    if r.get("code") != 0:
        print(f"  ❌ خطا: {r.get('msg')}"); return False

    oid = r["data"]["orderId"]
    print(f"\n  ✅ MARKET {sig.direction}  {sig.symbol}  orderId={oid}")

    # صبر برای fill و گذاشتن TP
    pos = None
    for w in (2, 3, 5, 8):
        await asyncio.sleep(w)
        positions = await client.get_positions()
        pos = next((p for p in positions if p["symbol"] == sig.symbol), None)
        if pos: break

    if pos:
        tp_side = "BUY" if sig.direction == "SHORT" else "SELL"
        tp_r = await client._post("/api/v1/futures/trade/place_order", {
            "symbol": sig.symbol, "qty": str(pos["qty"]),
            "side": tp_side, "tradeSide": "CLOSE",
            "orderType": "LIMIT", "price": _fmt_price(sig.tp),
            "positionId": pos["positionId"],
        })
        if tp_r.get("code") == 0:
            print(f"  🎯 TP @ {_fmt_price(sig.tp)}  orderId={tp_r['data']['orderId']}")
        else:
            print(f"  ⚠️  TP failed: {tp_r.get('msg')}")
    return True


# ── main scan ─────────────────────────────────────────────────────────────────

async def run_spring_scan(top_n: int = 0,   # 0 = همه ارزها
                          progress: bool = True) -> None:
    """
    اسکن فنر — همه ارزهای Bitunix (یا top_n اگه > 0).
    همیشه تأیید دستی قبل از ورود.
    """
    t0 = time.time()

    async with aiohttp.ClientSession() as session:
        client = AsyncBitunixClient(API_KEY, SECRET_KEY, session)

        # BTC bias
        btc_tf = {tf: await client.get_klines("BTCUSDT", tf, 100)
                  for tf in ("4h", "1h", "1d")}
        btc_bias, btc_detail = btc_ict_bias(btc_tf)

        if btc_bias == "neutral":
            if progress:
                print("  🟡 [Spring] BTC بی‌تصمیمه — اسکن فنر skip\n")
            return

        direction = "LONG" if btc_bias == "bullish" else "SHORT"
        ict_dir   = "bullish" if direction == "LONG" else "bearish"
        icon      = "🟢" if direction == "LONG" else "🔴"

        # همه ارزها
        tickers = await client.get_all_tickers()
        for t in tickers:
            try: t["_vol"] = float(t.get("baseVol", 0))
            except: t["_vol"] = 0.0

        if top_n and top_n > 0:
            tickers = sorted(tickers, key=lambda x: x["_vol"], reverse=True)[:top_n]

        price_map = {t["symbol"]: float(t["lastPrice"])
                     for t in tickers if t.get("lastPrice") and float(t.get("lastPrice", 0)) > 0}
        symbols   = list(price_map.keys())

        if progress:
            print(f"\n  {icon} [Spring Scan]  BTC={btc_bias.upper()}"
                  f"  |  {len(symbols)} ارز  |  دنبال {kind_name(direction)} …\n",
                  flush=True)

        # Batched concurrent scan
        found: List[SpringSignal] = []
        done = 0

        for i in range(0, len(symbols), BATCH_SIZE):
            batch = symbols[i: i + BATCH_SIZE]
            tasks = [
                _scan_one(client, sym, price_map[sym],
                          btc_bias, btc_detail, direction, ict_dir)
                for sym in batch
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, SpringSignal):
                    found.append(r)
            done += len(batch)
            if progress:
                elapsed = time.time() - t0
                print(f"  [Spring] {done}/{len(symbols)}"
                      f"  یافته: {len(found)}"
                      f"  [{elapsed:.0f}s]", flush=True)

        elapsed = time.time() - t0
        if not found:
            if progress:
                print(f"\n  [Spring] هیچ فنری پیدا نشد  [{elapsed:.0f}s]\n")
            return

        # رتبه‌بندی بر اساس امتیاز
        found.sort(key=lambda s: s.score, reverse=True)
        top = found[:SHOW_TOP]

        if progress:
            print(f"\n{'═'*56}")
            print(f"  🔍 Spring Scan تموم شد — {len(found)} فنر از {len(symbols)} ارز")
            print(f"  ⏱️  زمان: {elapsed:.0f}s  |  top {len(top)} نمایش داده میشه")
            print(f"{'═'*56}\n")

        # نمایش و تأیید
        for rank, sig in enumerate(top, start=1):
            print(_format_spring(rank, sig))
            confirmed = await _ask(sig.symbol)
            if confirmed:
                ok = await _execute(client, sig)
                if ok:
                    print(f"\n  ✅ {sig.symbol} وارد شد — بقیه رد میشن\n")
                    return
            else:
                print(f"  ⏩ #{rank} {sig.symbol} رد شد\n")

        print("  [Spring] همه رد شدن یا زمان تموم شد.\n")


def kind_name(direction: str) -> str:
    return "Spring 🔄 (LONG)" if direction == "LONG" else "Upthrust 🔄 (SHORT)"
