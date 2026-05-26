#!/usr/bin/env python3
"""
ICT Sniper — XRPUSDT LONG
Setup: OTE zone sweep (1.3483) + 5m reversal confirmed + BTC OTE recovery.

Entry  : LIMIT 1.3504  (OTE boundary retest)
SL     : 1.3462        (-0.31%)
TP1    : 1.3597        (session high, RR 2.2:1)  — close 50%
TP2    : 1.3658        (daily high,   RR 3.7:1)  — close 50%
Leverage: 10x
"""

import asyncio
import os
import sys
import time
import math
import aiohttp

sys.path.insert(0, os.path.dirname(__file__))
from bitunix_scanner.client import AsyncBitunixClient

API_KEY    = os.getenv("BITUNIX_API_KEY",    "7bee3f4756a0dbc89ae152f34c2175ac")
SECRET_KEY = os.getenv("BITUNIX_SECRET_KEY", "4e0a845778d49068297106a64cbcda61")

SYMBOL   = "XRPUSDT"
SIDE     = "BUY"
ENTRY    = 1.3504
SL       = 1.3462
TP1      = 1.3597
TP2      = 1.3658
LEVERAGE = 10

CANCEL_IF_ABOVE = 1.3600   # If XRP pushes above this before filling → cancel (missed)
MAX_WAIT_HOURS  = 4        # Auto-cancel after 4 hours if not filled


def _fmt(price: float) -> str:
    return f"{price:.4f}"


def _qty_str(entry: float, margin: float, leverage: int):
    notional = margin * leverage
    qty = notional / entry
    qty = math.floor(qty * 100) / 100
    if qty < 0.01:
        return None
    s = f"{qty:.2f}"
    return s.rstrip("0").rstrip(".")


async def _get_ticker_price(client: AsyncBitunixClient, symbol: str) -> float:
    resp = await client._get_public("/api/v1/futures/market/tickers")
    tickers = resp.get("data") or []
    for t in tickers:
        if t.get("symbol") == symbol:
            return float(t.get("lastPrice", 0))
    return 0.0


async def _check_filled(client: AsyncBitunixClient, symbol: str, order_id: str) -> bool:
    """Check if the limit order has been filled (position exists)."""
    positions = await client.get_positions()
    for p in positions:
        if p["symbol"] == symbol:
            return True
    return False


async def _place_tp(client: AsyncBitunixClient, symbol: str,
                    pos_id: str, tp_price: float, qty_str: str,
                    label: str):
    body = {
        "symbol":     symbol,
        "qty":        qty_str,
        "side":       "SELL",
        "tradeSide":  "CLOSE",
        "orderType":  "LIMIT",
        "price":      _fmt(tp_price),
        "positionId": pos_id,
    }
    r = await client._post("/api/v1/futures/trade/place_order", body)
    if r.get("code") == 0:
        print(f"  🎯 {label} LIMIT placed @ {_fmt(tp_price)}  id={r['data']['orderId']}")
    else:
        print(f"  ⚠️  {label} failed: {r.get('msg')}")


async def main():
    print(f"""
╔══════════════════════════════════════════════════════╗
║  🎯 ICT SNIPER — XRPUSDT LONG                       ║
╠══════════════════════════════════════════════════════╣
║  Entry  (LIMIT) : {_fmt(ENTRY)}                          ║
║  Stop Loss      : {_fmt(SL)}   (-0.31%)                  ║
║  TP1 (50%)      : {_fmt(TP1)}   (RR 2.2:1)               ║
║  TP2 (50%)      : {_fmt(TP2)}   (RR 3.7:1)               ║
║  Leverage       : {LEVERAGE}x                              ║
║  Cancel above   : {_fmt(CANCEL_IF_ABOVE)}                  ║
╚══════════════════════════════════════════════════════╝
""")

    async with aiohttp.ClientSession() as session:
        client = AsyncBitunixClient(API_KEY, SECRET_KEY, session)

        # 1. Check current price
        current = await _get_ticker_price(client, SYMBOL)
        print(f"  📊 Current XRP price: {_fmt(current)}")

        if current > CANCEL_IF_ABOVE:
            print(f"  ❌ Price {_fmt(current)} > cancel threshold {_fmt(CANCEL_IF_ABOVE)}")
            print(f"     Move already gone. Wait for next setup.\n")
            return

        # 2. Check no existing position
        positions = await client.get_positions()
        for p in positions:
            if p["symbol"] == SYMBOL:
                print(f"  ⚠️  Already have a {SYMBOL} position open — aborting.\n")
                return

        # 3. Get balance
        account   = await client.get_account()
        available = float(account.get("available", 0))
        print(f"  💰 Available balance: {available:.4f} USDT")

        if available < 1.0:
            print(f"  ❌ Balance too low ({available:.4f} USDT) — need at least 1 USDT\n")
            return

        # 4. Set leverage
        await client.set_leverage(SYMBOL, LEVERAGE)
        print(f"  ⚙️  Leverage set to {LEVERAGE}x")

        # 5. Calculate qty
        margin = available * 0.95
        qty    = _qty_str(ENTRY, margin, LEVERAGE)
        if not qty:
            print(f"  ❌ Lot size too small (balance={available:.2f} USDT)\n")
            return

        print(f"  📐 Margin: {margin:.4f} USDT  |  Qty: {qty} XRP  "
              f"(notional ≈ {float(qty)*ENTRY:.2f} USDT)")

        # 6. Place LIMIT entry + SL
        print(f"\n  📤 Placing LIMIT BUY @ {_fmt(ENTRY)} with SL @ {_fmt(SL)} …")
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

        # Retry without SL params if exchange rejects (some Bitunix versions)
        if result.get("code") != 0 and "sl" in str(result.get("msg", "")).lower():
            print(f"  ⚠️  SL param rejected — retrying without SL …")
            body.pop("slPrice", None)
            body.pop("slStopType", None)
            body.pop("slOrderType", None)
            result = await client._post("/api/v1/futures/trade/place_order", body)

        if result.get("code") != 0:
            print(f"  ❌ Order placement failed: {result.get('msg')}\n")
            return

        order_id = result["data"]["orderId"]
        print(f"""
  ✅ LIMIT ORDER PLACED
     orderId  : {order_id}
     Waiting for fill at {_fmt(ENTRY)} …
     (cancel if XRP breaks above {_fmt(CANCEL_IF_ABOVE)} without retracing)
""")

        # 7. Monitor for fill — poll every 15s
        deadline = time.time() + MAX_WAIT_HOURS * 3600
        poll_n   = 0
        while time.time() < deadline:
            await asyncio.sleep(15)
            poll_n += 1

            # Check current price — cancel if price ripped above threshold
            try:
                cur = await _get_ticker_price(client, SYMBOL)
            except Exception:
                cur = 0.0

            if cur > CANCEL_IF_ABOVE:
                print(f"\n  ⚠️  XRP hit {_fmt(cur)} > {_fmt(CANCEL_IF_ABOVE)} "
                      f"— move gone without fill. Cancelling limit order …")
                await client._post(
                    "/api/v1/futures/trade/cancel_order",
                    {"symbol": SYMBOL, "orderId": order_id}
                )
                print(f"  🚫 Order {order_id} cancel requested. Wait for next setup.\n")
                return

            if poll_n % 4 == 0:   # log every ~60s
                print(f"  ⏳ [{time.strftime('%H:%M:%S')}] XRP={_fmt(cur)}  "
                      f"waiting for fill @ {_fmt(ENTRY)} …")

            # Check if position opened (order filled)
            filled = await _check_filled(client, SYMBOL, order_id)
            if not filled:
                continue

            # ── FILLED ────────────────────────────────────────────────────
            print(f"\n  🟢 POSITION OPENED!  XRP LONG filled @ ~{_fmt(ENTRY)}")

            # Get position details
            positions = await client.get_positions()
            pos = next((p for p in positions if p["symbol"] == SYMBOL), None)
            if not pos:
                print("  ⚠️  Could not fetch position details — TP orders skipped")
                return

            pos_id     = pos["positionId"]
            actual_qty = pos["qty"]
            print(f"     positionId: {pos_id}  |  qty: {actual_qty}")

            # 8. Place TP1 (50%) and TP2 (50%) LIMIT close orders
            try:
                q = float(actual_qty)
                q_dec = len(str(actual_qty).split(".")[-1]) if "." in str(actual_qty) else 0
                half_q = str(int(q // 2)) if q_dec == 0 else f"{q/2:.{q_dec}f}"
            except Exception:
                half_q = actual_qty

            print(f"\n  📤 Placing TP orders …")
            await _place_tp(client, SYMBOL, pos_id, TP1, half_q,      "TP1 50%")
            await _place_tp(client, SYMBOL, pos_id, TP2, actual_qty,   "TP2 50%")

            print(f"""
  ╔══════════════════════════════════════════════════════╗
  ║  ✅ SNIPER TRADE ACTIVE — XRPUSDT LONG              ║
  ╠══════════════════════════════════════════════════════╣
  ║  Entry  : {_fmt(ENTRY)}                                  ║
  ║  SL     : {_fmt(SL)}   (exchange stop order)           ║
  ║  TP1    : {_fmt(TP1)}   (limit close, 50%)              ║
  ║  TP2    : {_fmt(TP2)}   (limit close, 50%)              ║
  ║  Leverage: {LEVERAGE}x                                   ║
  ╚══════════════════════════════════════════════════════╝
""")
            return

        # Timeout
        print(f"\n  ⏰ {MAX_WAIT_HOURS}h timeout — order not filled. Cancelling …")
        await client._post(
            "/api/v1/futures/trade/cancel_order",
            {"symbol": SYMBOL, "orderId": order_id}
        )
        print(f"  🚫 Limit order cancelled. Setup expired.\n")


if __name__ == "__main__":
    asyncio.run(main())
