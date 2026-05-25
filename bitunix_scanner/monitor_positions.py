"""
Standalone live monitor for manually-opened positions.
Adds HBAR and VET SHORT positions to LiveManager and runs ICT 3m candle monitoring.

Usage:
    python -m bitunix_scanner.monitor_positions
"""

import asyncio
import os

import aiohttp

from .client import AsyncBitunixClient
from .live_manager import LiveManager, ManagedPosition

API_KEY    = os.getenv("BITUNIX_API_KEY",    "7bee3f4756a0dbc89ae152f34c2175ac")
SECRET_KEY = os.getenv("BITUNIX_SECRET_KEY", "4e0a845778d49068297106a64cbcda61")


async def _main():
    async with aiohttp.ClientSession() as session:
        client = AsyncBitunixClient(API_KEY, SECRET_KEY, session)

        # Fetch live position data from exchange
        positions = await client.get_positions()
        pos_map = {p["symbol"]: p for p in positions}

        tickers_data = await client._get_public("/api/v1/futures/market/tickers")
        price_map = {t["symbol"]: float(t["lastPrice"])
                     for t in (tickers_data.get("data") or [])}

        live_mgr = LiveManager(client, poll_sec=20)

        targets = ["HBARUSDT", "VETUSDT", "XRPUSDT"]
        added = 0
        for sym in targets:
            p = pos_map.get(sym)
            if not p:
                print(f"  ⚠️  {sym}: no open position found, skipping")
                continue

            entry     = float(p["avgOpenPrice"])
            liq       = float(p.get("liqPrice", 0) or 0)
            pos_id    = p["positionId"]
            qty_str   = str(p.get("qty", "0"))
            direction = "SHORT" if p["side"] in ("SELL", "SHORT") else "LONG"
            cur       = price_map.get(sym, entry)

            # ICT scalp SL: above the recent swing high on 5m (last 30 candles)
            # Use a wider lookback to find a meaningful swing high, not micro noise
            c5m = await client.get_klines(sym, "5m", 60)
            if c5m:
                # Swing high = highest of the last 30 candles (covers recent structure)
                swing_h = max(float(c["high"]) for c in c5m[-30:])
                if direction == "SHORT":
                    # SL must be above BOTH current price and swing high
                    sl = max(swing_h, cur) * 1.001   # 0.1% above the highest point
                else:
                    swing_l = min(float(c["low"]) for c in c5m[-30:])
                    sl = min(swing_l, cur) * 0.999
            else:
                sl = liq * 0.97 if direction == "SHORT" else liq * 1.03

            risk = abs(sl - entry)
            tp   = entry - risk * 2.0 if direction == "SHORT" else entry + risk * 2.0
            loss_pct = risk / entry * 100

            mp = ManagedPosition(
                symbol       = sym,
                direction    = direction,
                entry_price  = entry,
                sl_price     = sl,
                tp_price     = tp,
                ob_high      = sl,
                ob_low       = tp,
                position_id  = pos_id,
                qty          = qty_str,
            )
            live_mgr.add_position(mp)
            added += 1

            print(f"  📡 {sym}  {direction}  entry={entry:.6f}  cur={cur:.6f}")
            print(f"       SL={sl:.6f}  (+{loss_pct:.2f}%)  TP={tp:.6f}  qty={qty_str}")

        if added == 0:
            print("\n  No positions to monitor. Exiting.")
            return

        print(f"""
┌─────────────────────────────────────────────────┐
│  LIVE MONITOR ACTIVE                            │
│  Positions watched : {added:<3}                        │
│  Pattern TF        : 3m candles                 │
│  Exit triggers     : Engulfing / Pin Bar /       │
│                      OB Break / BOS / BTC flip  │
│  Ctrl+C to stop                                 │
└─────────────────────────────────────────────────┘
""")

        try:
            await live_mgr.run()
        except KeyboardInterrupt:
            print("\n\n  ⛔ Monitor stopped by user.\n")


def main():
    asyncio.run(_main())


if __name__ == "__main__":
    main()
