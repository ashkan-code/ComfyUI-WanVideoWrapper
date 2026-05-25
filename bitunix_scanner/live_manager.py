"""
Live position manager for scalping.

Monitors open positions on 3m candles and closes them immediately
if an unfavorable candle pattern or structure break is detected.

Exit conditions for SHORT:
  1. Bullish Engulfing    — strong reversal candle body engulfs previous
  2. Hammer / Pin Bar     — long lower wick (rejection of lows) → bulls present
  3. OB Zone Broken       — candle closes above bearish OB high + buffer
  4. BOS Bullish (3m)     — higher high made above recent swing high
  5. BTC 15m Flip         — BTC structure turns bullish on 15m
  6. Two Consecutive Bull — two 3m candles close above entry price

Exit conditions for LONG:
  1. Bearish Engulfing
  2. Shooting Star        — long upper wick (rejection of highs) → bears present
  3. OB Zone Broken       — candle closes below bullish OB low - buffer
  4. BOS Bearish (3m)     — lower low made below recent swing low
  5. BTC 15m Flip         — BTC structure turns bearish on 15m
  6. Two Consecutive Bear — two 3m candles close below entry price
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from .client import AsyncBitunixClient
from .ict import market_structure, _klines_to_df
from .signals import _fmt

# ── Tunable constants ─────────────────────────────────────────────────────
POLL_SEC         = 20      # check every 20 seconds
ENGULF_RATIO     = 0.8     # body must cover ≥ 80% of prev body to count as engulf
WICK_RATIO       = 2.5     # wick must be ≥ 2.5× body for pin bar / shooting star
OB_BREAK_BUFFER  = 0.003   # 0.3% beyond OB zone counts as broken
CONSEC_CANDLES   = 2       # consecutive adverse candles before forced exit
MONITOR_TF       = "3m"    # timeframe for pattern detection


@dataclass
class ManagedPosition:
    symbol: str
    direction: str      # 'LONG' | 'SHORT'
    entry_price: float
    sl_price: float
    tp_price: float
    ob_high: float      # original OB zone high
    ob_low: float       # original OB zone low
    position_id: str
    qty: str = "0"      # "0" = full close; set to actual qty string if needed
    open_time: float = 0.0

    def __post_init__(self):
        if self.open_time == 0.0:
            self.open_time = time.time()


def _body_size(o: float, c: float) -> float:
    return abs(c - o)


def _upper_wick(o: float, h: float, c: float) -> float:
    return h - max(o, c)


def _lower_wick(o: float, l: float, c: float) -> float:
    return min(o, c) - l


def detect_exit_pattern(candles: list, direction: str,
                         ob_high: float, ob_low: float,
                         entry_price: float) -> Optional[str]:
    """
    Analyse the last 3 closed 3m candles.
    Returns exit reason string, or None if all clear.
    """
    if len(candles) < 3:
        return None

    # Use last 3 fully-closed candles (index -3, -2, -1 but skip the live candle)
    # candles list is oldest→newest; last element = current (not closed yet)
    c0 = candles[-4] if len(candles) >= 4 else candles[-3]  # two candles ago
    c1 = candles[-3]   # previous closed candle
    c2 = candles[-2]   # last closed candle  (most recent closed)
    # candles[-1] is still forming → ignore

    o0, h0, l0, cl0 = float(c0['open']), float(c0['high']), float(c0['low']), float(c0['close'])
    o1, h1, l1, cl1 = float(c1['open']), float(c1['high']), float(c1['low']), float(c1['close'])
    o2, h2, l2, cl2 = float(c2['open']), float(c2['high']), float(c2['low']), float(c2['close'])

    body2 = _body_size(o2, cl2)
    body1 = _body_size(o1, cl1)
    body0 = _body_size(o0, cl0)
    uw2   = _upper_wick(o2, h2, cl2)
    lw2   = _lower_wick(o2, l2, cl2)

    if direction == "SHORT":
        # ── 1. Bullish Engulfing ─────────────────────────────────────────
        # c2 is bullish AND its body engulfs c1's body
        if (cl2 > o2                             # c2 is green
                and o2 <= min(o1, cl1)           # opens at or below c1 body
                and cl2 >= max(o1, cl1) * (1 + 0.0005)  # closes above c1 body
                and body2 >= body1 * ENGULF_RATIO):
            return "Bullish Engulfing 🕯️"

        # ── 2. Hammer / Pin Bar ──────────────────────────────────────────
        # Long lower wick, close near top of candle → bulls defending
        if (body2 > 0
                and lw2 >= body2 * WICK_RATIO
                and cl2 > (l2 + (h2 - l2) * 0.55)):
            return "Hammer / Pin Bar 🔨"

        # ── 3. OB Zone Broken ────────────────────────────────────────────
        if cl2 > ob_high * (1 + OB_BREAK_BUFFER):
            return f"OB Zone Broken ↑ (close {_fmt(cl2)} > OB {_fmt(ob_high)}) 🚫"

        # ── 4. Break of Structure Bullish (higher high on 3m) ────────────
        recent_high = max(float(c['high']) for c in candles[-8:-2])
        if h2 > recent_high * 1.001:
            return f"BOS Bullish 3m (new HH {_fmt(h2)}) 📈"

        # ── 5. Two consecutive bullish candles above entry ────────────────
        both_bull = (cl2 > o2 and cl1 > o1)
        both_above_entry = (cl2 > entry_price and cl1 > entry_price)
        if both_bull and both_above_entry:
            return "2× Bull candles above entry 🔁"

    else:  # LONG
        # ── 1. Bearish Engulfing ─────────────────────────────────────────
        if (cl2 < o2
                and o2 >= max(o1, cl1)
                and cl2 <= min(o1, cl1) * (1 - 0.0005)
                and body2 >= body1 * ENGULF_RATIO):
            return "Bearish Engulfing 🕯️"

        # ── 2. Shooting Star ─────────────────────────────────────────────
        if (body2 > 0
                and uw2 >= body2 * WICK_RATIO
                and cl2 < (l2 + (h2 - l2) * 0.45)):
            return "Shooting Star ⭐"

        # ── 3. OB Zone Broken ────────────────────────────────────────────
        if cl2 < ob_low * (1 - OB_BREAK_BUFFER):
            return f"OB Zone Broken ↓ (close {_fmt(cl2)} < OB {_fmt(ob_low)}) 🚫"

        # ── 4. Break of Structure Bearish (lower low on 3m) ──────────────
        recent_low = min(float(c['low']) for c in candles[-8:-2])
        if l2 < recent_low * 0.999:
            return f"BOS Bearish 3m (new LL {_fmt(l2)}) 📉"

        # ── 5. Two consecutive bearish candles below entry ────────────────
        both_bear = (cl2 < o2 and cl1 < o1)
        both_below_entry = (cl2 < entry_price and cl1 < entry_price)
        if both_bear and both_below_entry:
            return "2× Bear candles below entry 🔁"

    return None


def _btc_structure_15m(candles_15m: list) -> str:
    return market_structure(candles_15m, lookback=40)


class LiveManager:
    """
    Monitors open positions and exits on adverse pattern detection.
    Add positions via add_position(); run via run().
    """

    def __init__(self, client: AsyncBitunixClient, poll_sec: int = POLL_SEC):
        self.client = client
        self.poll_sec = poll_sec
        self._positions: Dict[str, ManagedPosition] = {}

    def add_position(self, pos: ManagedPosition):
        self._positions[pos.symbol] = pos
        print(f"  📡 LiveManager watching: {pos.direction} {pos.symbol}")

    # ── Core exit ─────────────────────────────────────────────────────────

    async def _close_market(self, pos: ManagedPosition, reason: str):
        side = "BUY" if pos.direction == "SHORT" else "SELL"
        body = {
            "symbol":     pos.symbol,
            "side":       side,
            "tradeSide":  "CLOSE",
            "orderType":  "MARKET",
            "qty":        pos.qty,       # actual qty or "0" for full-close
            "positionId": pos.position_id,
            "reduceOnly": True,
        }
        result = await self.client._post("/api/v1/futures/trade/place_order", body)
        if result.get("code") == 0:
            elapsed = (time.time() - pos.open_time) / 60
            print(f"\n  🔴 CLOSED  {pos.direction} {pos.symbol}")
            print(f"     Reason  : {reason}")
            print(f"     Duration: {elapsed:.1f} min")
            print(f"     orderId : {result['data']['orderId']}\n")
            self._positions.pop(pos.symbol, None)
        else:
            print(f"  ⚠️  Close failed for {pos.symbol}: {result.get('msg')}")

    # ── BTC 15m check ─────────────────────────────────────────────────────

    async def _btc_flipped(self, direction: str) -> bool:
        raw = await self.client.get_klines("BTCUSDT", "15m", 60)
        structure = _btc_structure_15m(raw)
        if direction == "SHORT" and structure == "bullish":
            return True
        if direction == "LONG" and structure == "bearish":
            return True
        return False

    # ── Structural bias check — immediate close if wrong side ─────────────

    async def _structure_invalidated(self, mp: ManagedPosition) -> Optional[str]:
        """
        If BOTH 15m and 1h market structure are against the position direction,
        the trade is structurally invalid — close immediately, don't wait for pattern.
        """
        against = 0
        details = []
        for tf in ("15m", "1h"):
            raw = await self.client.get_klines(mp.symbol, tf, 60)
            ms  = market_structure(raw, lookback=40)
            if mp.direction == "SHORT" and ms == "bullish":
                against += 1
                details.append(f"{tf}=bullish")
            elif mp.direction == "LONG" and ms == "bearish":
                against += 1
                details.append(f"{tf}=bearish")
        if against >= 2:
            return f"ساختار بازار علیه پوزیشن [{', '.join(details)}] ⚡"
        return None

    # ── Main loop ─────────────────────────────────────────────────────────

    async def run(self):
        print(f"\n  📡 LiveManager started — monitoring {len(self._positions)} position(s)")
        print(f"     Pattern TF: {MONITOR_TF}  |  Poll: {self.poll_sec}s\n")

        while self._positions:
            # Sync with exchange positions (remove closed ones)
            open_pos = await self.client.get_positions()
            open_ids = {p["positionId"] for p in open_pos}

            for sym in list(self._positions.keys()):
                mp = self._positions[sym]
                if mp.position_id not in open_ids:
                    print(f"  ✅ {sym} already closed (SL/TP hit)")
                    self._positions.pop(sym, None)

            if not self._positions:
                break

            # Check BTC structure once per loop
            btc_flipped_cache: Optional[bool] = None

            for sym, mp in list(self._positions.items()):
                # ── Priority 1: structural invalidation (immediate close) ──
                struct_reason = await self._structure_invalidated(mp)
                if struct_reason:
                    await self._close_market(mp, struct_reason)
                    continue

                # Fetch 3m candles for pattern detection
                candles = await self.client.get_klines(sym, MONITOR_TF, 20)
                if len(candles) < 5:
                    continue

                current_price = float(candles[-1]['close'])
                pnl_pct = ((mp.entry_price - current_price) / mp.entry_price * 100
                           if mp.direction == "SHORT"
                           else (current_price - mp.entry_price) / mp.entry_price * 100)

                # ── Priority 2: candle pattern check ──────────────────────
                reason = detect_exit_pattern(
                    candles, mp.direction,
                    mp.ob_high, mp.ob_low, mp.entry_price
                )
                if reason:
                    await self._close_market(mp, reason)
                    continue

                # ── Priority 3: BTC 15m flip ──────────────────────────────
                if btc_flipped_cache is None:
                    btc_flipped_cache = await self._btc_flipped(mp.direction)
                if btc_flipped_cache:
                    await self._close_market(mp, "BTC 15m structure flipped ₿")
                    continue

                # Status line
                pnl_sign = "+" if pnl_pct >= 0 else ""
                tp_dist = abs(current_price - mp.tp_price) / mp.entry_price * 100
                print(f"  📊 {sym:<18}  price={_fmt(current_price):>12}"
                      f"  PnL={pnl_sign}{pnl_pct:.2f}%"
                      f"  TP dist={tp_dist:.2f}%  ✓ ok")

            await asyncio.sleep(self.poll_sec)

        print("  📡 LiveManager: no active positions, stopping.")
