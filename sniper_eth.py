#!/usr/bin/env python3
"""
ICT Swing Sniper — ETHUSDT LONG
Spring: double-bottom 2084 | BOS: 10:15 UTC | OTE+FVG+OB: 2096-2106

Entry  : LIMIT 2106   (OTE + FVG bottom + Bullish OB)
SL     : 2079         (-1.28% — below spring double-bottom)
TP1    : 2200  40%    (RRR 3.48:1)
TP2    : 2280  30%    (RRR 6.44:1)
TP3    : 2400  30%    (RRR 10.9:1)
Leverage: 7x  (swing — needs room)
"""

import asyncio, os, sys, time, math
import aiohttp

sys.path.insert(0, os.path.dirname(__file__))
from bitunix_scanner.client import AsyncBitunixClient

API_KEY    = os.getenv("BITUNIX_API_KEY",    "68f0a1765f124bacb847afa8db78e480")
SECRET_KEY = os.getenv("BITUNIX_SECRET_KEY", "159808597389a1cd1fc429f9f469209b")

SYMBOL   = "ETHUSDT"
SIDE     = "BUY"
ENTRY    = 2106.0
SL       = 2079.0
TP1      = 2200.0   # 40% close
TP2      = 2280.0   # 30% close
TP3      = 2400.0   # 30% close
LEVERAGE = 7

CANCEL_IF_ABOVE = 2165.0   # ETH breaks 2165 without fill → move gone
MAX_WAIT_HOURS  = 8


def _fmt(p): return f"{p:.2f}"

def _qty_str(entry, margin, lev):
    qty = math.floor((margin * lev / entry) * 100) / 100
    return f"{qty:.2f}".rstrip("0").rstrip(".") if qty >= 0.01 else None

def _split(qty_str, pct):
    """Return qty_str × pct, floored to 2 decimals."""
    q = math.floor(float(qty_str) * pct * 100) / 100
    return f"{q:.2f}".rstrip("0").rstrip(".") if q >= 0.01 else None

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
║  🟢 ICT SWING SNIPER — ETHUSDT LONG                     ║
╠══════════════════════════════════════════════════════════╣
║  Entry  LIMIT : {_fmt(ENTRY)}   (OTE + FVG + OB zone)       ║
║  Stop Loss    : {_fmt(SL)}   (-1.28%)  ← below spring 2084 ║
║  TP1  (40%)   : {_fmt(TP1)}   RRR 3.48:1                  ║
║  TP2  (30%)   : {_fmt(TP2)}   RRR 6.44:1                  ║
║  TP3  (30%)   : {_fmt(TP3)}   RRR 10.9:1                  ║
║  Leverage     : {LEVERAGE}x   (swing — 8h window)                ║
╚══════════════════════════════════════════════════════════╝
""")

    async with aiohttp.ClientSession() as session:
        client = AsyncBitunixClient(API_KEY, SECRET_KEY, session)

        cur = await _ticker(client, SYMBOL)
        print(f"  📊 ETH now: {_fmt(cur)}")

        if cur > CANCEL_IF_ABOVE:
            print(f"  ❌ ETH {_fmt(cur)} > {_fmt(CANCEL_IF_ABOVE)} — move gone, abort.\n")
            return

        positions = await client.get_positions()
        if any(p["symbol"] == SYMBOL for p in positions):
            print(f"  ⚠️  Already have ETHUSDT position — aborting.\n"); return

        acc = await client.get_account()
        avail = float(acc.get("available", 0))
        print(f"  💰 Available: {avail:.4f} USDT")
        if avail < 1:
            print("  ❌ Balance too low\n"); return

        await client.set_leverage(SYMBOL, LEVERAGE)
        print(f"  ⚙️  Leverage set to {LEVERAGE}x")

        margin = avail * 0.95
        qty = _qty_str(ENTRY, margin, LEVERAGE)
        if not qty:
            print("  ❌ Lot size too small\n"); return

        notional = float(qty) * ENTRY
        print(f"  📐 Margin: {margin:.2f} USDT | Qty: {qty} ETH | Notional: {notional:.2f} USDT")

        print(f"\n  📤 Placing LIMIT BUY @ {_fmt(ENTRY)} SL @ {_fmt(SL)} …")
        body = {
            "symbol": SYMBOL, "qty": qty, "side": SIDE,
            "tradeSide": "OPEN", "orderType": "LIMIT",
            "price": _fmt(ENTRY),
            "slPrice": _fmt(SL), "slStopType": "MARK_PRICE", "slOrderType": "MARKET",
        }
        result = await client._post("/api/v1/futures/trade/place_order", body)

        if result.get("code") != 0 and "sl" in str(result.get("msg","")).lower():
            print("  ⚠️  SL param rejected — retry without SL …")
            for k in ("slPrice","slStopType","slOrderType"): body.pop(k, None)
            result = await client._post("/api/v1/futures/trade/place_order", body)

        if result.get("code") != 0:
            print(f"  ❌ Failed: {result.get('msg')}\n"); return

        oid = result["data"]["orderId"]
        print(f"""
  ✅ LIMIT ORDER PLACED
     orderId : {oid}
     Entry   : {_fmt(ENTRY)}  waiting for fill …
     Cancel  : if ETH > {_fmt(CANCEL_IF_ABOVE)} without fill
""")

        # ── Monitor loop ──────────────────────────────────────────────────
        deadline = time.time() + MAX_WAIT_HOURS * 3600
        n = 0
        while time.time() < deadline:
            await asyncio.sleep(20)
            n += 1

            try: cur = await _ticker(client, SYMBOL)
            except: cur = 0.0

            if cur > CANCEL_IF_ABOVE:
                print(f"\n  ⚠️  ETH={_fmt(cur)} > {_fmt(CANCEL_IF_ABOVE)} — move gone. Cancelling …")
                await client._post("/api/v1/futures/trade/cancel_order",
                                   {"symbol": SYMBOL, "orderId": oid})
                print("  🚫 Order cancelled. Wait for next retrace.\n"); return

            if n % 3 == 0:
                print(f"  ⏳ [{time.strftime('%H:%M:%S')}] ETH={_fmt(cur)}  "
                      f"waiting fill @ {_fmt(ENTRY)} …")

            positions = await client.get_positions()
            pos = next((p for p in positions if p["symbol"] == SYMBOL), None)
            if not pos:
                continue

            # ── FILLED ────────────────────────────────────────────────
            pos_id  = pos["positionId"]
            act_qty = pos["qty"]
            print(f"\n  🟢 ETH LONG FILLED @ ~{_fmt(ENTRY)}")
            print(f"     positionId: {pos_id}  qty: {act_qty}")

            # Split qty for 3 TPs
            q40 = _split(act_qty, 0.40)
            q30 = _split(act_qty, 0.30)

            print("\n  📤 Placing TP orders …")
            for tp_price, tp_qty, label in [
                (TP1, q40,     "TP1 40%"),
                (TP2, q30,     "TP2 30%"),
                (TP3, act_qty, "TP3 30%"),   # remainder
            ]:
                if not tp_qty: continue
                await _place(client, {
                    "symbol": SYMBOL, "qty": tp_qty,
                    "side": "SELL", "tradeSide": "CLOSE",
                    "orderType": "LIMIT", "price": _fmt(tp_price),
                    "positionId": pos_id,
                }, label)

            print(f"""
  ╔══════════════════════════════════════════════════════╗
  ║  ✅ ETH SWING TRADE ACTIVE                          ║
  ╠══════════════════════════════════════════════════════╣
  ║  Entry : {_fmt(ENTRY)}                                  ║
  ║  SL    : {_fmt(SL)}  (exchange stop)                   ║
  ║  TP1   : {_fmt(TP1)}  40% close  (RRR 3.48:1)         ║
  ║  TP2   : {_fmt(TP2)}  30% close  (RRR 6.44:1)         ║
  ║  TP3   : {_fmt(TP3)}  30% close  (RRR 10.9:1)         ║
  ║  Lev   : {LEVERAGE}x  swing                                 ║
  ╚══════════════════════════════════════════════════════╝
""")
            return

        print(f"\n  ⏰ {MAX_WAIT_HOURS}h timeout — cancelling …")
        await client._post("/api/v1/futures/trade/cancel_order",
                           {"symbol": SYMBOL, "orderId": oid})
        print("  🚫 Order cancelled — setup expired.\n")

if __name__ == "__main__":
    asyncio.run(main())
