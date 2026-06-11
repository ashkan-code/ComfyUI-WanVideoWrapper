#!/usr/bin/env python3
"""
ICT Multi-Timeframe Sniper — SOLUSDT SHORT
─────────────────────────────────────────────────────────────────
4H  : HTF bearish bias  (Lower High 86.14 < 87.50)
1H  : OTE zone computed from last bearish swing
15M : Entry confirmed — bearish candle rejects from OTE zone
─────────────────────────────────────────────────────────────────
Entry : MARKET SHORT after 15M bearish confirmation inside OTE
SL    : Above 1H session high + structural buffer  (not tight)
TP    : Single point — liquidity pool below Spring Low
"""

import asyncio, os, sys, time, math, ssl
import aiohttp

sys.path.insert(0, os.path.dirname(__file__))
from bitunix_scanner.client import AsyncBitunixClient

API_KEY    = os.getenv("BITUNIX_API_KEY",    "68f0a1765f124bacb847afa8db78e480")
SECRET_KEY = os.getenv("BITUNIX_SECRET_KEY", "159808597389a1cd1fc429f9f469209b")

SYMBOL   = "SOLUSDT"
LEVERAGE = 5

# ── Setup parameters (از تحلیل 4H/1H) ──────────────────────────
# 4H: Lower High تأیید شده (86.14 < 87.50)
# 1H: Swing High (session)   → برای OTE مرجع
SWING_HIGH   = 86.14    # سقف جلسه — آخرین Lower High
SWING_LOW    = 84.40    # کف جلسه  — پایین‌ترین نقطه بعد از سقف

OTE_LOW  = SWING_LOW + 0.618 * (SWING_HIGH - SWING_LOW)   # 85.47
OTE_HIGH = SWING_LOW + 0.786 * (SWING_HIGH - SWING_LOW)   # 85.77
OTE_MID  = (OTE_LOW + OTE_HIGH) / 2                       # 85.62

# ── SL و TP ──────────────────────────────────────────────────────
# SL: بالای سقف 1H جلسه + بافر ساختاری مناسب (نه تنگ)
SL = round(SWING_HIGH + 0.46, 2)     # 86.60 — فضای کافی بالای 86.14

# TP: یک نقطه — حوضچه نقدینگی زیر Spring Low
TP = 81.50   # sweep of 81.44 spring low — single target

# ── شرایط cancel/invalidation ─────────────────────────────────
CANCEL_IF_ABOVE = 87.10   # اگر SOL بالای این بسته شود → setup باطل
MAX_WAIT_HOURS  = 8       # حداکثر انتظار

POLL_SEC = 60   # هر ۶۰ ثانیه 15M را چک کن


# ── helpers ──────────────────────────────────────────────────────
def _fmt(p, d=2): return f"{p:.{d}f}"

def _qty_str(entry, margin, lev):
    qty = math.floor((margin * lev / entry) * 100) / 100
    return f"{qty:.2f}".rstrip("0").rstrip(".") if qty >= 0.01 else None


# ── دریافت قیمت لحظه‌ای ─────────────────────────────────────────
async def _ticker(client) -> float | None:
    try:
        resp = await client._get_public("/api/v1/futures/market/tickers")
        for t in (resp.get("data") or []):
            if t.get("symbol") == SYMBOL:
                return float(t.get("lastPrice", 0)) or None
    except Exception:
        pass
    return None


# ── لغو تمام اوردرهای pending ───────────────────────────────────
async def _cancel_all_pending(client):
    try:
        r = await client._get_private("/api/v1/futures/trade/get_pending_orders",
                                      {"symbol": SYMBOL})
        orders = (r.get("data") or {}).get("orderList") or []
        for o in orders:
            await client._post("/api/v1/futures/trade/cancel_order",
                               {"symbol": SYMBOL, "orderId": o["orderId"]})
            print(f"  🚫 pending order لغو شد: {o['orderId']}")
    except Exception as e:
        print(f"  ⚠️  cancel error: {e}")


# ── تأیید 15M ────────────────────────────────────────────────────
def _15m_confirmed(candles: list) -> bool:
    """
    تأیید بیریش روی 15M:
    آخرین کندل کامل ([-2]):
      - سقف آن وارد OTE zone شده (h >= OTE_LOW)
      - بدنه نزولی (close < open)
      - بسته شدن زیر OTE_MID (ریجکشن قوی از OTE)
    """
    if len(candles) < 3:
        return False
    c = candles[-2]   # آخرین کندل کامل ([-1] در حال شکل‌گیری)
    o = float(c["open"]); h = float(c["high"])
    cl = float(c["close"])

    touched_ote  = h >= OTE_LOW
    bearish_body = cl < o
    rejected_ote = cl < OTE_MID

    return touched_ote and bearish_body and rejected_ote


# ── ثبت اوردر ───────────────────────────────────────────────────
async def _place(client, body, label) -> str | None:
    r = await client._post("/api/v1/futures/trade/place_order", body)
    if r.get("code") == 0:
        oid = r["data"]["orderId"]
        print(f"  ✅ {label}  id={oid}")
        return oid
    print(f"  ❌ {label} failed: {r.get('msg')}")
    return None


# ════════════════════════════════════════════════════════════════
async def main():
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║   ICT MULTI-TF SNIPER — SOLUSDT SHORT                       ║
╠══════════════════════════════════════════════════════════════╣
║  4H Bias  : BEARISH  (Lower High 86.14 < 87.50)             ║
║  1H OTE   : {_fmt(OTE_LOW)} – {_fmt(OTE_HIGH)}  (61.8%–78.6% retrace)       ║
║  15M Entry: bearish close below {_fmt(OTE_MID)} inside OTE zone    ║
╠══════════════════════════════════════════════════════════════╣
║  Entry    : MARKET SHORT  (after 15M confirmation)          ║
║  SL       : {_fmt(SL)}  (بالای سقف 86.14 + بافر ساختاری)       ║
║  TP       : {_fmt(TP)}  (liquidity pool — Spring Low sweep)    ║
║  Leverage : {LEVERAGE}x                                              ║
╚══════════════════════════════════════════════════════════════╝
""")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    conn = aiohttp.TCPConnector(ssl=ssl_ctx)

    async with aiohttp.ClientSession(connector=conn) as session:
        client = AsyncBitunixClient(API_KEY, SECRET_KEY, session)

        # ── بررسی وضعیت اولیه ────────────────────────────────────
        cur = await _ticker(client)
        print(f"  📊 SOL: {_fmt(cur) if cur else '?'}")

        if cur and cur > CANCEL_IF_ABOVE:
            print(f"  ❌ SOL {_fmt(cur)} > {_fmt(CANCEL_IF_ABOVE)} — setup باطل\n")
            return

        positions = await client.get_positions()
        if any(p["symbol"] == SYMBOL for p in positions):
            print(f"  ⚠️  موقعیت SOLUSDT باز است — abort\n"); return

        # لغو اوردرهای pending قبلی
        await _cancel_all_pending(client)

        acc = await client.get_account()
        avail = float(acc.get("available", 0))
        print(f"  💰 موجودی: {avail:.4f} USDT")
        if avail < 1:
            print("  ❌ موجودی ناکافی\n"); return

        await client.set_leverage(SYMBOL, LEVERAGE)
        print(f"  ⚙️  Leverage: {LEVERAGE}x")
        print(f"\n  👁  منتظر تأیید 15M در OTE  ({_fmt(OTE_LOW)}–{_fmt(OTE_HIGH)}) …\n")

        # ── حلقه انتظار برای تأیید 15M ───────────────────────────
        deadline = time.time() + MAX_WAIT_HOURS * 3600
        tick = 0
        while time.time() < deadline:
            await asyncio.sleep(POLL_SEC)
            tick += 1

            cur = await _ticker(client)
            if not cur:
                continue

            # invalidation
            if cur > CANCEL_IF_ABOVE:
                print(f"\n  ❌ SOL={_fmt(cur)} > {_fmt(CANCEL_IF_ABOVE)} — setup باطل\n")
                return

            # وضعیت هر ۳ پول
            if tick % 3 == 0:
                zone_status = "در OTE ✓" if OTE_LOW <= cur <= OTE_HIGH else \
                              f"{'بالای' if cur > OTE_HIGH else 'پایین‌تر از'} OTE"
                print(f"  ⏳ [{time.strftime('%H:%M:%S')}]  SOL={_fmt(cur)}  {zone_status}")

            # چک تأیید 15M (فقط وقتی قیمت در نزدیکی OTE است)
            if cur < OTE_LOW - 1.0 or cur > OTE_HIGH + 1.0:
                continue

            try:
                candles_15m = await client.get_klines(SYMBOL, "15m", 10)
            except Exception:
                continue

            if not _15m_confirmed(candles_15m):
                c = candles_15m[-2] if len(candles_15m) >= 2 else {}
                print(f"  🔍 15M: O={c.get('open','?')}  H={c.get('high','?')}  "
                      f"C={c.get('close','?')}  — هنوز تأیید نشده")
                continue

            # ════════ تأیید 15M دریافت شد ════════════════════════
            c_conf = candles_15m[-2]
            print(f"""
  🎯 تأیید 15M!
     کندل: O={c_conf['open']}  H={c_conf['high']}  C={c_conf['close']}
     OTE zone touched ✅ | Bearish body ✅ | Rejected below {_fmt(OTE_MID)} ✅
""")

            # محاسبه حجم
            acc = await client.get_account()
            avail = float(acc.get("available", 0))
            margin = avail * 0.95
            entry_approx = cur   # قیمت فعلی به عنوان تخمین MARKET
            qty = _qty_str(entry_approx, margin, LEVERAGE)
            if not qty:
                print("  ❌ حجم خیلی کم\n"); return

            notional = float(qty) * entry_approx
            risk_pct  = abs(SL - entry_approx) / entry_approx * 100
            reward_pct = abs(TP - entry_approx) / entry_approx * 100
            rrr = reward_pct / risk_pct if risk_pct else 0

            print(f"  📐 Qty: {qty} SOL | Notional: {notional:.2f} USDT")
            print(f"  📊 Risk: {risk_pct:.2f}%  |  Reward: {reward_pct:.2f}%  |  RRR: {rrr:.1f}:1")

            # ── MARKET SHORT ──────────────────────────────────────
            body = {
                "symbol":      SYMBOL,
                "qty":         qty,
                "side":        "SELL",
                "tradeSide":   "OPEN",
                "orderType":   "MARKET",
                "slPrice":     _fmt(SL),
                "slStopType":  "MARK_PRICE",
                "slOrderType": "MARKET",
            }
            result = await client._post("/api/v1/futures/trade/place_order", body)

            if result.get("code") != 0 and "sl" in str(result.get("msg", "")).lower():
                print("  ⚠️  SL inline رد شد — بدون SL …")
                for k in ("slPrice", "slStopType", "slOrderType"): body.pop(k, None)
                result = await client._post("/api/v1/futures/trade/place_order", body)

            if result.get("code") != 0:
                print(f"  ❌ خطا: {result.get('msg')}\n"); return

            entry_oid = result["data"]["orderId"]
            print(f"\n  🔴 MARKET SHORT PLACED  id={entry_oid}")

            # صبر تا موقعیت باز شود
            fill_price = entry_approx
            for _ in range(10):
                await asyncio.sleep(3)
                positions = await client.get_positions()
                pos = next((p for p in positions if p["symbol"] == SYMBOL), None)
                if pos:
                    fill_price = float(pos.get("avgOpenPrice") or pos.get("entryPrice") or entry_approx)
                    break

            # ── TP LIMIT ──────────────────────────────────────────
            positions = await client.get_positions()
            pos = next((p for p in positions if p["symbol"] == SYMBOL), None)
            if pos:
                pos_id  = pos["positionId"]
                act_qty = pos["qty"]
                print(f"  🔴 موقعیت باز: positionId={pos_id}  qty={act_qty}")
                print(f"  📊 Fill ~{_fmt(fill_price)}  |  SL={_fmt(SL)}  |  TP={_fmt(TP)}")

                await _place(client, {
                    "symbol":     SYMBOL,
                    "qty":        act_qty,
                    "side":       "BUY",
                    "tradeSide":  "CLOSE",
                    "orderType":  "LIMIT",
                    "price":      _fmt(TP),
                    "positionId": pos_id,
                }, f"TP LIMIT @ {_fmt(TP)}")

            actual_rrr = abs(fill_price - TP) / abs(SL - fill_price) if SL != fill_price else 0
            print(f"""
  ╔══════════════════════════════════════════════════════════╗
  ║  🔴 SOL SHORT ACTIVE — ICT SNIPER                       ║
  ╠══════════════════════════════════════════════════════════╣
  ║  Entry (15M conf): ~{_fmt(fill_price)}                       ║
  ║  SL   : {_fmt(SL)}   (ساختاری — بالای 1H سقف)          ║
  ║  TP   : {_fmt(TP)}   (single target — Spring pool)     ║
  ║  RRR  : {actual_rrr:.1f}:1                                       ║
  ╚══════════════════════════════════════════════════════════╝
""")
            return

        print(f"\n  ⏰ {MAX_WAIT_HOURS}h timeout — تأیید 15M دریافت نشد\n")


if __name__ == "__main__":
    asyncio.run(main())
