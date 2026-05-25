"""
Live position manager — tiered exit (TP1 50% / TP2 50%) + ICT danger exits.

Exit logic:
  Priority 1 — Structural invalidation (15m + 1h both against) → close 100%
  Priority 2 — TP1 hit                                          → close 50%, SL → breakeven
  Priority 3 — TP2 hit (after TP1)                             → close remaining 50%
  Priority 4 — SL hit (price beyond sl_price)                  → close 100%
  Priority 5 — Candle pattern on 3m                            → close 100%
  Priority 6 — BTC 15m structure flip                          → close 100%
"""

import asyncio
import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .client import AsyncBitunixClient
from .ict import market_structure, _klines_to_df
from .signals import _fmt

POLL_SEC        = 20
ENGULF_RATIO    = 0.8
WICK_RATIO      = 2.5
OB_BREAK_BUFFER = 0.003
MONITOR_TF      = "3m"


@dataclass
class ManagedPosition:
    symbol:      str
    direction:   str       # 'LONG' | 'SHORT'
    entry_price: float
    sl_price:    float
    tp1_price:   float
    tp2_price:   float
    ob_high:     float
    ob_low:      float
    position_id: str
    qty:         str  = "0"
    open_time:   float = 0.0
    tp1_hit:     bool  = False   # True once 50% closed at TP1

    def __post_init__(self):
        if self.open_time == 0.0:
            self.open_time = time.time()


def _body(o, c):  return abs(c - o)
def _uw(o, h, c): return h - max(o, c)
def _lw(o, l, c): return min(o, c) - l


def _half_qty(qty_str: str) -> str:
    """Return half the qty, rounded down to integer or 2 dec."""
    try:
        q = float(qty_str)
    except Exception:
        return qty_str
    half = q / 2
    if "." not in qty_str or qty_str.endswith(".0"):
        return str(max(1, math.floor(half)))
    decimals = len(qty_str.split(".")[-1])
    factor   = 10 ** decimals
    return f"{math.floor(half * factor) / factor:.{decimals}f}".rstrip("0").rstrip(".")


def detect_exit_pattern(candles: list, direction: str,
                         ob_high: float, ob_low: float,
                         entry_price: float) -> Optional[str]:
    if len(candles) < 4:
        return None
    c0 = candles[-4]
    c1 = candles[-3]
    c2 = candles[-2]
    o0,h0,l0,cl0 = float(c0['open']),float(c0['high']),float(c0['low']),float(c0['close'])
    o1,h1,l1,cl1 = float(c1['open']),float(c1['high']),float(c1['low']),float(c1['close'])
    o2,h2,l2,cl2 = float(c2['open']),float(c2['high']),float(c2['low']),float(c2['close'])
    b2 = _body(o2,cl2); b1 = _body(o1,cl1)
    uw2 = _uw(o2,h2,cl2); lw2 = _lw(o2,l2,cl2)

    if direction == "SHORT":
        if (cl2>o2 and o2<=min(o1,cl1)
                and cl2>=max(o1,cl1)*(1+0.0005)
                and b2>=b1*ENGULF_RATIO):
            return "Bullish Engulfing 🕯️"
        if b2>0 and lw2>=b2*WICK_RATIO and cl2>(l2+(h2-l2)*0.55):
            return "Hammer / Pin Bar 🔨"
        if cl2 > ob_high*(1+OB_BREAK_BUFFER):
            return f"OB Zone Broken ↑ 🚫"
        rh = max(float(c['high']) for c in candles[-8:-2])
        if h2 > rh*1.001:
            return "BOS Bullish 3m 📈"
        if cl2>o2 and cl1>o1 and cl2>entry_price and cl1>entry_price:
            return "2× Bull above entry 🔁"
    else:
        if (cl2<o2 and o2>=max(o1,cl1)
                and cl2<=min(o1,cl1)*(1-0.0005)
                and b2>=b1*ENGULF_RATIO):
            return "Bearish Engulfing 🕯️"
        if b2>0 and uw2>=b2*WICK_RATIO and cl2<(l2+(h2-l2)*0.45):
            return "Shooting Star ⭐"
        if cl2 < ob_low*(1-OB_BREAK_BUFFER):
            return f"OB Zone Broken ↓ 🚫"
        rl = min(float(c['low']) for c in candles[-8:-2])
        if l2 < rl*0.999:
            return "BOS Bearish 3m 📉"
        if cl2<o2 and cl1<o1 and cl2<entry_price and cl1<entry_price:
            return "2× Bear below entry 🔁"
    return None


class LiveManager:
    def __init__(self, client: AsyncBitunixClient, poll_sec: int = POLL_SEC):
        self.client   = client
        self.poll_sec = poll_sec
        self._positions: Dict[str, ManagedPosition] = {}

    def add_position(self, pos: ManagedPosition):
        self._positions[pos.symbol] = pos
        print(f"  📡 LiveManager watching: {pos.direction} {pos.symbol}"
              f"  TP1={_fmt(pos.tp1_price)}  TP2={_fmt(pos.tp2_price)}"
              f"  SL={_fmt(pos.sl_price)}")

    # ── Close helpers ──────────────────────────────────────────────────────

    async def _close_qty(self, pos: ManagedPosition, qty: str, reason: str,
                          partial: bool = False) -> bool:
        side = "BUY" if pos.direction == "SHORT" else "SELL"
        body = {
            "symbol":     pos.symbol,
            "side":       side,
            "tradeSide":  "CLOSE",
            "orderType":  "MARKET",
            "qty":        qty,
            "positionId": pos.position_id,
            "reduceOnly": True,
        }
        result = await self.client._post("/api/v1/futures/trade/place_order", body)
        if result.get("code") == 0:
            elapsed = (time.time() - pos.open_time) / 60
            tag = "PARTIAL TP1" if partial else "CLOSED"
            print(f"\n  {'🟡' if partial else '🔴'} {tag}  {pos.direction} {pos.symbol}")
            print(f"     Reason  : {reason}")
            print(f"     Qty     : {qty}  Duration: {elapsed:.1f} min")
            print(f"     orderId : {result['data']['orderId']}\n")
            if not partial:
                self._positions.pop(pos.symbol, None)
            return True
        else:
            print(f"  ⚠️  Close failed {pos.symbol}: {result.get('msg')}")
            return False

    async def _close_full(self, pos: ManagedPosition, reason: str):
        await self._close_qty(pos, pos.qty, reason, partial=False)

    async def _close_half(self, pos: ManagedPosition, reason: str):
        half = _half_qty(pos.qty)
        ok   = await self._close_qty(pos, half, reason, partial=True)
        if ok:
            pos.tp1_hit  = True
            pos.sl_price = pos.entry_price   # move SL to breakeven
            print(f"  🛡️  SL moved to breakeven ({_fmt(pos.entry_price)}) for {pos.symbol}")

    # ── Checks ────────────────────────────────────────────────────────────

    async def _structure_invalidated(self, mp: ManagedPosition) -> Optional[str]:
        against = 0
        details = []
        for tf in ("15m", "1h"):
            raw = await self.client.get_klines(mp.symbol, tf, 60)
            ms  = market_structure(raw, lookback=40)
            if mp.direction == "SHORT" and ms == "bullish":
                against += 1; details.append(f"{tf}=bull")
            elif mp.direction == "LONG" and ms == "bearish":
                against += 1; details.append(f"{tf}=bear")
        if against >= 2:
            return f"Structure invalidated [{', '.join(details)}] ⚡"
        return None

    async def _btc_flipped(self, direction: str) -> bool:
        raw = await self.client.get_klines("BTCUSDT", "15m", 60)
        ms  = market_structure(raw, lookback=40)
        return (direction == "SHORT" and ms == "bullish") or \
               (direction == "LONG"  and ms == "bearish")

    # ── Main loop ─────────────────────────────────────────────────────────

    async def run(self):
        print(f"\n  📡 LiveManager started — {len(self._positions)} position(s)"
              f"  [TP tiered 50%/50%]  poll={self.poll_sec}s\n")

        while self._positions:
            # Sync: remove positions closed externally (SL/TP hit on exchange)
            open_pos = await self.client.get_positions()
            open_ids = {p["positionId"] for p in open_pos}
            for sym in list(self._positions.keys()):
                mp = self._positions[sym]
                if mp.position_id not in open_ids:
                    print(f"  ✅ {sym} closed externally (SL/TP/manual)")
                    self._positions.pop(sym, None)

            if not self._positions:
                break

            btc_flip_cache: Optional[bool] = None

            for sym, mp in list(self._positions.items()):
                # ── P1: structural invalidation ───────────────────────────
                struct_r = await self._structure_invalidated(mp)
                if struct_r:
                    await self._close_full(mp, struct_r)
                    continue

                candles = await self.client.get_klines(sym, MONITOR_TF, 20)
                if len(candles) < 5:
                    continue

                price   = float(candles[-1]["close"])
                pnl_pct = ((mp.entry_price - price) / mp.entry_price * 100
                           if mp.direction == "SHORT"
                           else (price - mp.entry_price) / mp.entry_price * 100)

                # ── P2: SL hit ────────────────────────────────────────────
                sl_hit = (price >= mp.sl_price if mp.direction == "SHORT"
                          else price <= mp.sl_price)
                if sl_hit:
                    await self._close_full(mp, f"SL hit at {_fmt(price)} 🛑")
                    continue

                # ── P3: TP1 hit (if not already) ─────────────────────────
                if not mp.tp1_hit:
                    tp1_hit = (price <= mp.tp1_price if mp.direction == "SHORT"
                               else price >= mp.tp1_price)
                    if tp1_hit:
                        await self._close_half(mp, f"TP1 hit {_fmt(price)} 🟡 (50% closed)")
                        continue

                # ── P4: TP2 hit (only after TP1) ─────────────────────────
                if mp.tp1_hit:
                    tp2_hit = (price <= mp.tp2_price if mp.direction == "SHORT"
                               else price >= mp.tp2_price)
                    if tp2_hit:
                        await self._close_full(mp, f"TP2 hit {_fmt(price)} 🎯")
                        continue

                # ── P5: candle pattern ────────────────────────────────────
                reason = detect_exit_pattern(
                    candles, mp.direction, mp.ob_high, mp.ob_low, mp.entry_price
                )
                if reason:
                    await self._close_full(mp, reason)
                    continue

                # ── P6: BTC 15m flip ─────────────────────────────────────
                if btc_flip_cache is None:
                    btc_flip_cache = await self._btc_flipped(mp.direction)
                if btc_flip_cache:
                    await self._close_full(mp, "BTC 15m flipped ₿")
                    continue

                # Status
                tp_target = mp.tp2_price if mp.tp1_hit else mp.tp1_price
                tp_dist   = abs(price - tp_target) / mp.entry_price * 100
                tp_tag    = "TP2" if mp.tp1_hit else "TP1"
                sign      = "+" if pnl_pct >= 0 else ""
                print(f"  📊 {sym:<18}  {_fmt(price):>12}"
                      f"  PnL={sign}{pnl_pct:.2f}%"
                      f"  {tp_tag} dist={tp_dist:.2f}%"
                      f"  {'🟡TP1 done' if mp.tp1_hit else '⬜'}")

            await asyncio.sleep(self.poll_sec)

        print("  📡 LiveManager: all positions closed.")
