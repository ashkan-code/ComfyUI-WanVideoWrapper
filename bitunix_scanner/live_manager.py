"""
Live position manager — ICT danger monitoring on 5m candle closes.

Exchange orders placed:
  • SL  : set at entry (MARK_PRICE MARKET stop) — exchange handles full SL
  • TP1 : LIMIT close 50% at TP1 price (placed by trader after fill)
  • TP2 : LIMIT close 50% at TP2 price (placed by trader after fill)

This manager's job (every 5 minutes = 1 candle):
  Priority 1 — Both 15m + 1h structure against position → emergency close
  Priority 2 — 5m candle: Engulfing / Pin Bar / BOS against position → close
  Priority 3 — BTC 15m structure flip → close
  Priority 4 — SL price breached (fallback if exchange SL not triggered) → close
  Priority 5 — Detect TP1 hit (position qty halved) → move SL to breakeven

On emergency close: cancel ALL open orders for that symbol, then market close.
"""

import asyncio
import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .client import AsyncBitunixClient
from .ict import market_structure
from .signals import _fmt

CANDLE_POLL_SEC  = 300    # check every 5m candle close
ENGULF_RATIO     = 0.75
WICK_RATIO       = 2.0
OB_BREAK_BUFFER  = 0.003


@dataclass
class ManagedPosition:
    symbol:      str
    direction:   str
    entry_price: float
    sl_price:    float
    tp1_price:   float
    tp2_price:   float
    ob_high:     float
    ob_low:      float
    position_id: str
    qty:         str  = "0"
    open_time:   float = 0.0
    tp1_hit:     bool  = False

    def __post_init__(self):
        if self.open_time == 0.0:
            self.open_time = time.time()


# ── candle helpers ────────────────────────────────────────────────────────────

def _body(o, c):  return abs(c - o)
def _uw(o, h, c): return h - max(o, c)
def _lw(o, l, c): return min(o, c) - l


def detect_danger_candle(candles: list, direction: str,
                          ob_high: float, ob_low: float,
                          entry_price: float) -> Optional[str]:
    """
    Analyse the last two CLOSED 5m candles for ICT danger signals.
    Returns reason string if position should be closed, else None.
    """
    if len(candles) < 4:
        return None

    # Use last 2 closed candles (candles[-1] is still forming)
    c1 = candles[-3]   # second-last closed
    c2 = candles[-2]   # last closed

    o1,h1,l1,cl1 = float(c1['open']),float(c1['high']),float(c1['low']),float(c1['close'])
    o2,h2,l2,cl2 = float(c2['open']),float(c2['high']),float(c2['low']),float(c2['close'])
    b1 = _body(o1, cl1)
    b2 = _body(o2, cl2)
    uw2 = _uw(o2, h2, cl2)
    lw2 = _lw(o2, l2, cl2)

    if direction == "SHORT":
        # 1. Strong bullish engulfing
        if (cl2 > o2
                and b2 > 0
                and o2 <= min(o1, cl1)
                and cl2 >= max(o1, cl1)
                and b2 >= b1 * ENGULF_RATIO):
            return "Bullish Engulfing 5m 🕯️"

        # 2. Hammer / Pin Bar (strong lower wick — buyers defending lows)
        if b2 > 0 and lw2 >= b2 * WICK_RATIO and cl2 > (l2 + (h2 - l2) * 0.6):
            return "Hammer / Pin Bar 5m 🔨"

        # 3. OB zone broken (close above OB high)
        if cl2 > ob_high * (1 + OB_BREAK_BUFFER):
            return f"OB Broken ↑ ({_fmt(cl2)} > {_fmt(ob_high)}) 🚫"

        # 4. Break of structure bullish on 5m
        recent_high = max(float(c['high']) for c in candles[-10:-2])
        if h2 > recent_high * 1.002:
            return f"BOS Bullish 5m (HH {_fmt(h2)}) 📈"

        # 5. Two consecutive strong bullish candles above entry
        if (cl2 > o2 and cl1 > o1
                and cl2 > entry_price and cl1 > entry_price
                and b2 > b1 * 0.5):
            return "2× Strong Bull 5m above entry 🔁"

    else:  # LONG
        # 1. Strong bearish engulfing
        if (cl2 < o2
                and b2 > 0
                and o2 >= max(o1, cl1)
                and cl2 <= min(o1, cl1)
                and b2 >= b1 * ENGULF_RATIO):
            return "Bearish Engulfing 5m 🕯️"

        # 2. Shooting Star (strong upper wick — sellers defending highs)
        if b2 > 0 and uw2 >= b2 * WICK_RATIO and cl2 < (l2 + (h2 - l2) * 0.4):
            return "Shooting Star 5m ⭐"

        # 3. OB zone broken
        if cl2 < ob_low * (1 - OB_BREAK_BUFFER):
            return f"OB Broken ↓ ({_fmt(cl2)} < {_fmt(ob_low)}) 🚫"

        # 4. BOS bearish on 5m
        recent_low = min(float(c['low']) for c in candles[-10:-2])
        if l2 < recent_low * 0.998:
            return f"BOS Bearish 5m (LL {_fmt(l2)}) 📉"

        # 5. Two consecutive strong bearish candles below entry
        if (cl2 < o2 and cl1 < o1
                and cl2 < entry_price and cl1 < entry_price
                and b2 > b1 * 0.5):
            return "2× Strong Bear 5m below entry 🔁"

    return None


# ── LiveManager ───────────────────────────────────────────────────────────────

class LiveManager:
    def __init__(self, client: AsyncBitunixClient,
                 poll_sec: int = CANDLE_POLL_SEC):
        self.client   = client
        self.poll_sec = poll_sec
        self._positions: Dict[str, ManagedPosition] = {}

    def add_position(self, pos: ManagedPosition):
        self._positions[pos.symbol] = pos
        print(f"  📡 LiveManager watching: {pos.direction} {pos.symbol}")
        print(f"       SL={_fmt(pos.sl_price)}  TP1={_fmt(pos.tp1_price)}"
              f"  TP2={_fmt(pos.tp2_price)}  [5m candle monitoring]")

    # ── Emergency close ───────────────────────────────────────────────────

    async def _cancel_all_orders(self, symbol: str):
        """Cancel all open orders for this symbol before emergency close."""
        try:
            open_orders = await self.client._get_private(
                "/api/v1/futures/trade/get_pending_orders",
                {"symbol": symbol}
            )
            orders = (open_orders.get("data") or {}).get("orderList") or []
            if orders:
                ids = [o["orderId"] for o in orders]
                await self.client.cancel_orders(symbol, ids)
                print(f"  🗑️  Cancelled {len(ids)} open order(s) for {symbol}")
        except Exception as e:
            print(f"  ⚠️  Could not cancel orders for {symbol}: {e}")

    async def _emergency_close(self, pos: ManagedPosition, reason: str):
        """Cancel all orders then market-close the full position."""
        await self._cancel_all_orders(pos.symbol)
        await asyncio.sleep(0.5)

        side = "BUY" if pos.direction == "SHORT" else "SELL"
        body = {
            "symbol":     pos.symbol,
            "side":       side,
            "tradeSide":  "CLOSE",
            "orderType":  "MARKET",
            "qty":        pos.qty,
            "positionId": pos.position_id,
            "reduceOnly": True,
        }
        result = await self.client._post("/api/v1/futures/trade/place_order", body)
        elapsed = (time.time() - pos.open_time) / 60

        if result.get("code") == 0:
            print(f"\n  🔴 EMERGENCY CLOSE  {pos.direction} {pos.symbol}")
            print(f"     Reason  : {reason}")
            print(f"     Duration: {elapsed:.1f} min")
            print(f"     orderId : {result['data']['orderId']}\n")
            self._positions.pop(pos.symbol, None)
        else:
            print(f"  ⚠️  Emergency close failed {pos.symbol}: {result.get('msg')}")

    # ── Checks ────────────────────────────────────────────────────────────

    async def _structure_invalidated(self, mp: ManagedPosition) -> Optional[str]:
        """
        HTF-first danger check — priority: Daily > 4H > 1H > 15m
        A single HTF signal is enough to close. No need for LTF confirmation.
        """
        opp = "bullish" if mp.direction == "SHORT" else "bearish"

        # Priority 1: Daily structure against → immediate close
        raw_1d = await self.client.get_klines(mp.symbol, "1d", 40)
        ms_1d  = market_structure(raw_1d, lookback=30)
        if ms_1d == opp:
            return f"Daily ساختار چرخید به {ms_1d.upper()} ⚡"

        # Priority 2: 4H structure against → immediate close
        raw_4h = await self.client.get_klines(mp.symbol, "4h", 60)
        ms_4h  = market_structure(raw_4h, lookback=40)
        if ms_4h == opp:
            return f"4H ساختار چرخید به {ms_4h.upper()} ⚡"

        # Priority 3: 1H structure against → immediate close
        raw_1h = await self.client.get_klines(mp.symbol, "1h", 60)
        ms_1h  = market_structure(raw_1h, lookback=40)
        if ms_1h == opp:
            return f"1H ساختار چرخید به {ms_1h.upper()} ⚡"

        # Priority 4: 15m (advisory — close only if 1h also neutral)
        raw_15m = await self.client.get_klines(mp.symbol, "15m", 60)
        ms_15m  = market_structure(raw_15m, lookback=30)
        if ms_15m == opp and ms_1h == "neutral":
            return f"15m {ms_15m.upper()} + 1H neutral — خروج احتیاطی ⚡"

        return None

    async def _btc_htf_flipped(self, direction: str) -> Optional[str]:
        """BTC HTF-first check: 4H flip is enough — don't wait for 15m."""
        opp = "bullish" if direction == "SHORT" else "bearish"

        # BTC 4H first
        raw_4h = await self.client.get_klines("BTCUSDT", "4h", 60)
        ms_4h  = market_structure(raw_4h, lookback=40)
        if ms_4h == opp:
            return f"BTC 4H چرخید به {ms_4h.upper()} ₿⚡"

        # BTC 1H
        raw_1h = await self.client.get_klines("BTCUSDT", "1h", 60)
        ms_1h  = market_structure(raw_1h, lookback=40)
        if ms_1h == opp:
            return f"BTC 1H چرخید به {ms_1h.upper()} ₿⚡"

        return None

    async def _check_tp1_hit(self, mp: ManagedPosition):
        """
        If TP1 order was filled (position qty roughly halved), record TP1 hit
        and move exchange SL to breakeven by placing a new stop via set_position_tpsl.
        """
        if mp.tp1_hit:
            return
        positions = await self.client.get_positions()
        pos_now = next((p for p in positions if p["positionId"] == mp.position_id), None)
        if not pos_now:
            return
        current_qty = float(pos_now.get("qty", mp.qty))
        original_qty = float(mp.qty)
        if original_qty > 0 and current_qty <= original_qty * 0.6:
            mp.tp1_hit = True
            mp.qty = str(current_qty)
            print(f"\n  🟡 TP1 HIT — {mp.symbol}  qty reduced to {current_qty}")
            print(f"     Moving SL to breakeven: {_fmt(mp.entry_price)}\n")
            mp.sl_price = mp.entry_price

    # ── Main monitoring loop ──────────────────────────────────────────────

    async def run(self):
        print(f"\n  📡 LiveManager — {len(self._positions)} position(s)"
              f"  [HTF-first monitoring  poll={self.poll_sec}s]\n")

        while self._positions:
            # Sync: remove positions closed by exchange SL/TP
            open_pos = await self.client.get_positions()
            open_ids = {p["positionId"] for p in open_pos}

            for sym in list(self._positions.keys()):
                mp = self._positions[sym]
                if mp.position_id not in open_ids:
                    elapsed = (time.time() - mp.open_time) / 60
                    print(f"  ✅ {sym} closed by exchange SL/TP  [{elapsed:.1f} min]")
                    self._positions.pop(sym, None)

            if not self._positions:
                break

            btc_flip_cache: Optional[str] = None

            for sym, mp in list(self._positions.items()):
                # ── P1: HTF structure (Daily > 4H > 1H > 15m) ────────────
                struct_r = await self._structure_invalidated(mp)
                if struct_r:
                    await self._emergency_close(mp, struct_r)
                    continue

                # ── P2: BTC HTF flip (4H > 1H) ───────────────────────────
                if btc_flip_cache is None:
                    btc_flip_cache = await self._btc_htf_flipped(mp.direction)
                if btc_flip_cache:
                    await self._emergency_close(mp, btc_flip_cache)
                    continue

                # ── P3: 5m candle danger ──────────────────────────────────
                candles_5m = await self.client.get_klines(sym, "5m", 15)
                if len(candles_5m) >= 4:
                    current_price = float(candles_5m[-1]["close"])
                    danger = detect_danger_candle(
                        candles_5m, mp.direction,
                        mp.ob_high, mp.ob_low, mp.entry_price
                    )
                    if danger:
                        await self._emergency_close(mp, danger)
                        continue

                    # ── P4: SL fallback ───────────────────────────────────
                    if False:
                        await self._emergency_close(mp, "BTC 15m structure flipped ₿")
                        continue

                    # ── P4: SL fallback (in case exchange SL didn't fire) ──
                    sl_breached = (current_price >= mp.sl_price
                                   if mp.direction == "SHORT"
                                   else current_price <= mp.sl_price)
                    if sl_breached:
                        await self._emergency_close(
                            mp, f"SL fallback hit at {_fmt(current_price)} 🛑"
                        )
                        continue

                    # ── P5: detect TP1 hit ────────────────────────────────
                    await self._check_tp1_hit(mp)

                    # Status
                    pnl_pct = ((mp.entry_price - current_price) / mp.entry_price * 100
                               if mp.direction == "SHORT"
                               else (current_price - mp.entry_price) / mp.entry_price * 100)
                    tp_now  = mp.tp2_price if mp.tp1_hit else mp.tp1_price
                    tp_tag  = "→TP2" if mp.tp1_hit else "→TP1"
                    sign    = "+" if pnl_pct >= 0 else ""
                    print(f"  📊 {sym:<18}  {_fmt(current_price):>12}"
                          f"  PnL={sign}{pnl_pct:.2f}%"
                          f"  SL={_fmt(mp.sl_price)}"
                          f"  {tp_tag}={_fmt(tp_now)}"
                          f"  {'🟡 TP1 done' if mp.tp1_hit else ''}")

            await asyncio.sleep(self.poll_sec)

        print("  📡 LiveManager: all positions closed.")
