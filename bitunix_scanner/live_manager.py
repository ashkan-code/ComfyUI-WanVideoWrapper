"""
Live position manager — HTF-only exit logic.

فلسفه:
  معامله فقط زمانی بسته میشه که تحلیل اصلی اشتباه ثابت بشه — نه نوسان ۵m.
  SL صرافی کار خودشو میکنه. ما فقط invalidation اصلی رو نگاه میکنیم.

شرط close اضطراری:
  1. Daily ساختار برعکس شد → close فوری
  2. هم 4H هم 1H با هم برعکس شدن → close
  3. BTC هم 4H هم 1H برعکس شد → close
  4. SL fallback (اگه SL صرافی fire نکرد) → close

هیچ close بر اساس ۵m یا ۱۵m نیست.
Poll هر ۱ ساعت یک بار کافیه.
"""

import asyncio
import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .client import AsyncBitunixClient
from .ict import market_structure
from .signals import _fmt

CANDLE_POLL_SEC  = 3600   # بررسی هر ۱ ساعت یک بار — HTF تغییر نمیکنه هر ۵ دقیقه


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
    Only closes on HIGH-CONFIDENCE signals — avoids premature exits on noise.
    Returns reason string if position should be closed, else None.
    """
    if len(candles) < 4:
        return None

    c1 = candles[-3]   # second-last closed
    c2 = candles[-2]   # last closed

    o1,h1,l1,cl1 = float(c1['open']),float(c1['high']),float(c1['low']),float(c1['close'])
    o2,h2,l2,cl2 = float(c2['open']),float(c2['high']),float(c2['low']),float(c2['close'])
    b1 = _body(o1, cl1)
    b2 = _body(o2, cl2)
    uw2 = _uw(o2, h2, cl2)
    lw2 = _lw(o2, l2, cl2)

    if direction == "SHORT":
        # 1. True bullish engulfing (body fully covers prev candle — no 75% shortcut)
        if (cl2 > o2 and b2 > 0
                and o2 <= min(o1, cl1)
                and cl2 >= max(o1, cl1)
                and b2 >= b1 * ENGULF_RATIO):
            return "Bullish Engulfing 5m 🕯️"

        # 2. Hammer / Pin Bar — strong lower wick, closes near high
        if b2 > 0 and lw2 >= b2 * WICK_RATIO and cl2 > (l2 + (h2 - l2) * 0.7):
            return "Hammer / Pin Bar 5m 🔨"

        # 3. OB zone clearly broken (0.5% buffer)
        if cl2 > ob_high * (1 + OB_BREAK_BUFFER):
            return f"OB Broken ↑ ({_fmt(cl2)} > {_fmt(ob_high)}) 🚫"

        # 4. REMOVED: 5m BOS — too noisy, fires on normal bounce
        # 5. REMOVED: 2× Strong Bull — fires on normal retracement

    else:  # LONG
        # 1. True bearish engulfing
        if (cl2 < o2 and b2 > 0
                and o2 >= max(o1, cl1)
                and cl2 <= min(o1, cl1)
                and b2 >= b1 * ENGULF_RATIO):
            return "Bearish Engulfing 5m 🕯️"

        # 2. Shooting Star — strong upper wick, closes near low
        if b2 > 0 and uw2 >= b2 * WICK_RATIO and cl2 < (l2 + (h2 - l2) * 0.3):
            return "Shooting Star 5m ⭐"

        # 3. OB zone clearly broken
        if cl2 < ob_low * (1 - OB_BREAK_BUFFER):
            return f"OB Broken ↓ ({_fmt(cl2)} < {_fmt(ob_low)}) 🚫"

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
        HTF structure invalidation — needs MULTIPLE TFs to agree before closing.
        Single TF flip (especially 1H) is noise in sideways markets — ignored alone.
        Rules:
          • Daily against → close immediately (Daily is king)
          • 4H against + 1H against → close (two HTFs confirm)
          • 4H against + 1H neutral → warning only, don't close
          • 1H alone against → ignore (normal retracement)
        """
        opp = "bullish" if mp.direction == "SHORT" else "bearish"

        # Daily structure against → immediate close (no argument with Daily)
        raw_1d = await self.client.get_klines(mp.symbol, "1d", 40)
        ms_1d  = market_structure(raw_1d, lookback=30)
        if ms_1d == opp:
            return f"Daily ساختار چرخید به {ms_1d.upper()} ⚡"

        # 4H + 1H both against → close (strong confirmation)
        raw_4h = await self.client.get_klines(mp.symbol, "4h", 60)
        ms_4h  = market_structure(raw_4h, lookback=40)
        raw_1h = await self.client.get_klines(mp.symbol, "1h", 60)
        ms_1h  = market_structure(raw_1h, lookback=40)

        if ms_4h == opp and ms_1h == opp:
            return f"4H+1H هر دو {opp.upper()} ← ساختار invalidated ⚡"

        # 4H against + 1H neutral → log warning but don't close
        if ms_4h == opp and ms_1h == "neutral":
            print(f"  ⚠️  {mp.symbol}: 4H={ms_4h} ولی 1H=neutral → نگه می‌داریم")

        return None

    async def _btc_htf_flipped(self, direction: str) -> Optional[str]:
        """BTC flip: needs BOTH 4H and 1H to flip — one alone is noise."""
        opp = "bullish" if direction == "SHORT" else "bearish"

        raw_4h = await self.client.get_klines("BTCUSDT", "4h", 60)
        ms_4h  = market_structure(raw_4h, lookback=40)
        raw_1h = await self.client.get_klines("BTCUSDT", "1h", 60)
        ms_1h  = market_structure(raw_1h, lookback=40)

        if ms_4h == opp and ms_1h == opp:
            return f"BTC 4H+1H هر دو {opp.upper()} ₿⚡"

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
              f"  [HTF-only monitoring  poll={self.poll_sec//60}h]\n")

        while self._positions:
            # Sync: remove positions closed by exchange SL/TP
            open_pos = await self.client.get_positions()
            open_ids = {p["positionId"] for p in open_pos}

            for sym in list(self._positions.keys()):
                mp = self._positions[sym]
                if mp.position_id not in open_ids:
                    elapsed = (time.time() - mp.open_time) / 60
                    print(f"  ✅ {sym} closed by exchange SL/TP  [{elapsed:.0f} min]")
                    self._positions.pop(sym, None)

            if not self._positions:
                break

            btc_flip_cache: Optional[str] = None

            for sym, mp in list(self._positions.items()):
                # Fetch current price for status
                raw1h = await self.client.get_klines(sym, "1h", 3)
                current_price = float(raw1h[-1]["close"]) if raw1h else mp.entry_price

                pnl_pct = ((mp.entry_price - current_price) / mp.entry_price * 100
                           if mp.direction == "SHORT"
                           else (current_price - mp.entry_price) / mp.entry_price * 100)
                elapsed_h = (time.time() - mp.open_time) / 3600
                sign = "+" if pnl_pct >= 0 else ""
                print(f"  📊 [{elapsed_h:.1f}h]  {sym}  {_fmt(current_price)}"
                      f"  PnL={sign}{pnl_pct:.2f}%"
                      f"  SL={_fmt(mp.sl_price)}  TP={_fmt(mp.tp1_price)}")

                # ── HTF structure invalidation ────────────────────────────
                struct_r = await self._structure_invalidated(mp)
                if struct_r:
                    await self._emergency_close(mp, struct_r)
                    continue

                # ── BTC HTF flip ──────────────────────────────────────────
                if btc_flip_cache is None:
                    btc_flip_cache = await self._btc_htf_flipped(mp.direction)
                if btc_flip_cache:
                    await self._emergency_close(mp, btc_flip_cache)
                    continue

                # ── SL fallback (exchange SL didn't fire) ─────────────────
                sl_hit = (current_price >= mp.sl_price if mp.direction == "SHORT"
                          else current_price <= mp.sl_price)
                if sl_hit:
                    await self._emergency_close(
                        mp, f"SL fallback {_fmt(current_price)} 🛑"
                    )
                    continue

                # ── TP hit check ──────────────────────────────────────────
                await self._check_tp1_hit(mp)

            await asyncio.sleep(self.poll_sec)

        print("  📡 LiveManager: all positions closed.")
