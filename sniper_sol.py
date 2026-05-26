#!/usr/bin/env python3
"""
ICT Swing Sniper — SOLUSDT SHORT
BTC Bias: BEARISH 4H (Lower High 78,088 < 78,216)
Setup   : Lower High + OTE + Equal Lows target

Entry  : LIMIT SHORT 85.50  (OTE + Bearish OB zone)
SL     : 86.30              (+0.94% above session high 86.14)
TP1    : 83.50  50%         (below equal lows 83.64 — RRR 2.5:1)
TP2    : 81.50  50%         (liquidity pool 81.44-82.12 — RRR 5.0:1)
Leverage: 5x  (swing)
"""

import asyncio, os, sys, time, math, ssl
import aiohttp

sys.path.insert(0, os.path.dirname(__file__))
from bitunix_scanner.client import AsyncBitunixClient

API_KEY    = os.getenv("BITUNIX_API_KEY",    "7bee3f4756a0dbc89ae152f34c2175ac")
SECRET_KEY = os.getenv("BITUNIX_SECRET_KEY", "4e0a845778d49068297106a64cbcda61")

SYMBOL   = "SOLUSDT"
SIDE     = "SELL"
ENTRY    = 85.50
SL       = 86.30
TP1      = 83.50   # 50% close
TP2      = 81.50   # 50% close
LEVERAGE = 5

CANCEL_IF_BELOW = 83.00   # اگر SOL بدون fill از 83 رد شود → move رفته
CANCEL_IF_ABOVE = 87.00   # اگر SOL بالای 87 بسته شود → setup باطل
MAX_WAIT_HOURS  = 6


def _fmt(p, dec=2): return f"{p:.{dec}f}"

def _qty_str(entry, margin, lev):
    qty = math.floor((margin * lev / entry) * 100) / 100
    return f"{qty:.2f}".rstrip("0").rstrip(".") if qty >= 0.01 else None

def _half(qty_str):
    q = math.floor(float(qty_str) * 0.50 * 100) / 100
    return f"{q:.2f}".rstrip("0").rstrip(".") if q >= 0.01 else qty_str

async def _ticker(client, symbol):
    resp = await client._get_public("/api/v1/futures/market/tickers")
    for t in (resp.get("data") or []):
        if t.get("symbol") == symbol:
            return float(t.get("lastPrice", 0))
    return 0.0

async def _place(client, body, label):
    r = await client._post("/api/v1/futures/trade/place_order", body)
    if r.get("code") == 0:
        oid = r["data"]["orderId"]
        print(f"  ✅ {label} placed  id={oid}")
        return oid
    print(f"  ❌ {label} failed: {r.get('msg')}")
    return None

async def main():
    print(f"""
╔══════════════════════════════════════════════════════════╗
║  🔴 ICT SWING SNIPER — SOLUSDT SHORT                    ║
╠══════════════════════════════════════════════════════════╣
║  BTC Bias : BEARISH 4H (Lower High confirmed)            ║
║  Entry    : LIMIT SHORT  {_fmt(ENTRY)}                      ║
║  Stop Loss: {_fmt(SL)}   (+0.94% above session high)      ║
║  TP1 (50%): {_fmt(TP1)}   RRR 2.5:1                       ║
║  TP2 (50%): {_fmt(TP2)}   RRR 5.0:1                       ║
║  Leverage : {LEVERAGE}x   (swing)                               ║
╚══════════════════════════════════════════════════════════╝
""")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    conn = aiohttp.TCPConnector(ssl=ssl_ctx)
    async with aiohttp.ClientSession(connector=conn) as session:
        client = AsyncBitunixClient(API_KEY, SECRET_KEY, session)

        cur = await _ticker(client, SYMBOL)
        print(f"  📊 SOL الان: {_fmt(cur)}")

        if cur > CANCEL_IF_ABOVE:
            print(f"  ❌ SOL {_fmt(cur)} > {_fmt(CANCEL_IF_ABOVE)} — setup باطل.\n")
            return

        # بررسی موقعیت باز
        positions = await client.get_positions()
        if any(p["symbol"] == SYMBOL for p in positions):
            print(f"  ⚠️  موقعیت SOLUSDT باز است — abort.\n"); return

        # بررسی اوردر باز قبلی و موجودی
        acc = await client.get_account()
        avail = float(acc.get("available", 0))
        print(f"  💰 موجودی: {avail:.4f} USDT")

        open_orders = await client._get_private("/api/v1/futures/trade/get_pending_orders",
                                               {"symbol": SYMBOL})
        oid = None
        for o in (open_orders.get("data") or {}).get("orderList") or []:
            if o.get("side") == "SELL" and abs(float(o.get("price", 0)) - ENTRY) < 0.50:
                oid = o["orderId"]
                print(f"  🔄 اوردر قبلی یافت شد — monitor ادامه  id={oid}")
                break

        # اگر اوردری نیست و موجودی کافی هست → place کن
        if not oid:
            if avail < 1:
                print("  ❌ موجودی کم و اوردر بازی یافت نشد\n"); return

            await client.set_leverage(SYMBOL, LEVERAGE)
            print(f"  ⚙️  Leverage: {LEVERAGE}x")

            margin = avail * 0.95
            qty = _qty_str(ENTRY, margin, LEVERAGE)
            if not qty:
                print("  ❌ حجم خیلی کم\n"); return

            notional = float(qty) * ENTRY
            print(f"  📐 Margin: {margin:.2f} | Qty: {qty} SOL | Notional: {notional:.2f} USDT")

            print(f"\n  📤 LIMIT SELL @ {_fmt(ENTRY)} | SL @ {_fmt(SL)} …")
            body = {
                "symbol":      SYMBOL,
                "qty":         qty,
                "side":        SIDE,
                "tradeSide":   "OPEN",
                "orderType":   "LIMIT",
                "price":       _fmt(ENTRY),
                "slPrice":     _fmt(SL),
                "slStopType":  "MARK_PRICE",
                "slOrderType": "MARKET",
            }
            result = await client._post("/api/v1/futures/trade/place_order", body)

            if result.get("code") != 0 and "sl" in str(result.get("msg", "")).lower():
                print("  ⚠️  SL رد شد — بدون SL تلاش مجدد …")
                for k in ("slPrice", "slStopType", "slOrderType"): body.pop(k, None)
                result = await client._post("/api/v1/futures/trade/place_order", body)

            if result.get("code") != 0:
                print(f"  ❌ خطا: {result.get('msg')}\n"); return

            oid = result["data"]["orderId"]
            print(f"""
  ✅ LIMIT SHORT PLACED
     orderId : {oid}
     Entry   : {_fmt(ENTRY)} — منتظر fill …
     Cancel  : SOL > {_fmt(CANCEL_IF_ABOVE)}
""")

        # ─── حلقه مانیتورینگ ───────────────────────────────────────
        deadline = time.time() + MAX_WAIT_HOURS * 3600
        n = 0
        while time.time() < deadline:
            await asyncio.sleep(20)
            n += 1

            try: cur = await _ticker(client, SYMBOL)
            except: cur = None

            if cur and (cur > CANCEL_IF_ABOVE or cur < CANCEL_IF_BELOW):
                reason = "setup باطل" if cur > CANCEL_IF_ABOVE else "move missed"
                print(f"\n  ⚠️  SOL={_fmt(cur)} — {reason}. Cancel …")
                if oid:
                    await client._post("/api/v1/futures/trade/cancel_order",
                                       {"symbol": SYMBOL, "orderId": oid})
                else:
                    await client._post("/api/v1/futures/trade/cancel_all_orders",
                                       {"symbol": SYMBOL})
                print("  🚫 Cancel شد.\n"); return

            if n % 3 == 0:
                print(f"  ⏳ [{time.strftime('%H:%M:%S')}] SOL={_fmt(cur)}  "
                      f"انتظار fill @ {_fmt(ENTRY)} …")

            # بررسی باز شدن موقعیت
            positions = await client.get_positions()
            pos = next((p for p in positions if p["symbol"] == SYMBOL), None)
            if not pos:
                continue

            # ─── FILLED ────────────────────────────────────────────
            pos_id  = pos["positionId"]
            act_qty = pos["qty"]
            print(f"\n  🔴 SOL SHORT FILLED @ ~{_fmt(ENTRY)}")
            print(f"     positionId: {pos_id}  qty: {act_qty}")

            # نصف حجم برای هر TP
            q_half = _half(act_qty)

            print("\n  📤 ثبت TP orders …")
            # TP1 — BUY CLOSE 50%
            await _place(client, {
                "symbol":     SYMBOL,
                "qty":        q_half,
                "side":       "BUY",
                "tradeSide":  "CLOSE",
                "orderType":  "LIMIT",
                "price":      _fmt(TP1),
                "positionId": pos_id,
            }, f"TP1 50% @ {_fmt(TP1)}")

            # TP2 — BUY CLOSE 50% (کل باقیمانده)
            await _place(client, {
                "symbol":     SYMBOL,
                "qty":        act_qty,
                "side":       "BUY",
                "tradeSide":  "CLOSE",
                "orderType":  "LIMIT",
                "price":      _fmt(TP2),
                "positionId": pos_id,
            }, f"TP2 50% @ {_fmt(TP2)}")

            print(f"""
  ╔══════════════════════════════════════════════════════╗
  ║  🔴 SOL SWING SHORT ACTIVE                          ║
  ╠══════════════════════════════════════════════════════╣
  ║  Entry : {_fmt(ENTRY)}                                  ║
  ║  SL    : {_fmt(SL)}   (exchange stop)                  ║
  ║  TP1   : {_fmt(TP1)}   50% close  (RRR 2.5:1)         ║
  ║  TP2   : {_fmt(TP2)}   50% close  (RRR 5.0:1)         ║
  ║  Lev   : {LEVERAGE}x  swing                                 ║
  ╚══════════════════════════════════════════════════════╝
""")
            return

        # timeout
        print(f"\n  ⏰ {MAX_WAIT_HOURS}h timeout — cancel …")
        await client._post("/api/v1/futures/trade/cancel_order",
                           {"symbol": SYMBOL, "orderId": oid})
        print("  🚫 Order cancel — setup expired.\n")

if __name__ == "__main__":
    asyncio.run(main())
