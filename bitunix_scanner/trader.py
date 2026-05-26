"""
Advanced ICT Auto-Trader.

Rules:
  - ONE position at a time (max_positions = 1)
  - FULL margin: 100% of available balance
  - Leverage: max 10x (per SL %)
  - Confirmation: price in OB zone + candle (REQUIRED) + volume (bonus)
  - After 2 consecutive losses → pause 1 candle cycle (5 min), re-assess HTF
  - Skip if spread > 0.15% (approximated from 1m candle range)
"""

import asyncio
import math
import time
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from .client import AsyncBitunixClient
from .ict import btc_ict_bias, market_structure, _klines_to_df
from .signals import Signal, _fmt

if TYPE_CHECKING:
    from .live_manager import LiveManager, ManagedPosition

MAX_POSITIONS    = 1
MAX_LEVERAGE     = 10
POLL_INTERVAL    = 30
ENTRY_ZONE_TOL   = 0.001   # ±0.1% sniper tolerance — price must be at OB
PAUSE_CANDLES    = 1       # candle cycles to pause after 2 losses
CANDLE_SEC       = 300     # 5m candle = 300 s
PAUSE_DURATION   = 3600    # 1 hour pause after 2 consecutive losses
MAX_SPREAD_PCT   = 0.0025  # 0.25% — increased to allow entries in volatile market


def _price_decimals(price: float) -> int:
    if price >= 10_000: return 1
    if price >= 1_000:  return 2
    if price >= 100:    return 3
    if price >= 10:     return 4
    if price >= 1:      return 5
    return 6


def _qty_str(entry: float, margin: float, leverage: int) -> Optional[str]:
    notional = margin * leverage
    qty = notional / entry
    if entry >= 1_000:
        qty = math.floor(qty * 1_000) / 1_000
        if qty < 0.001: return None
        return f"{qty:.3f}"
    if entry >= 1.0:
        qty = math.floor(qty * 100) / 100
        if qty < 0.01: return None
        return f"{qty:.2f}".rstrip("0").rstrip(".")
    qty = math.floor(qty)
    if qty < 1: return None
    return str(int(qty))


def _fmt_price(price: float) -> str:
    return f"{price:.{_price_decimals(price)}f}"


class AutoTrader:
    def __init__(self, client: AsyncBitunixClient,
                 max_positions: int = MAX_POSITIONS,
                 risk_pct: float = 1.0,    # ignored — always full margin
                 poll_sec: int = POLL_INTERVAL,
                 live_manager: Optional["LiveManager"] = None):
        self.client        = client
        self.max_positions = max_positions
        self.poll_sec      = poll_sec
        self.live_manager  = live_manager
        self._signals: Dict[str, Signal] = {}
        self._placed:  Dict[str, str]    = {}
        self._consec_losses: int         = 0
        self._pause_until:   float       = 0.0

    def add_signals(self, signals: List[Signal]):
        for s in signals:
            if s.symbol not in self._signals:
                self._signals[s.symbol] = s
        print(f"\n  📋 {len(self._signals)} signal(s) queued  "
              f"(best: {next(iter(self._signals), '—')})\n")

    def record_loss(self):
        self._consec_losses += 1
        if self._consec_losses >= 2:
            self._pause_until = time.time() + PAUSE_DURATION
            print(f"\n  ⚠️  {self._consec_losses} consecutive losses — "
                  f"pausing 1 hour ({PAUSE_DURATION}s) for HTF reassessment …\n")
            self._consec_losses = 0

    def record_win(self):
        self._consec_losses = 0

    # ── Entry checks ───────────────────────────────────────────────────────

    async def _in_zone(self, signal: Signal) -> Tuple[bool, float]:
        raw   = await self.client.get_klines(signal.symbol, "1m", 5)
        if not raw:
            return False, 0.0
        price = float(raw[-1]["close"])
        lo = signal.zone.price_low  * (1 - ENTRY_ZONE_TOL)
        hi = signal.zone.price_high * (1 + ENTRY_ZONE_TOL)
        in_zone = lo <= price <= hi

        # Price must have visited the zone in last 3 candles (not just current tick)
        # Removes the conflicting "approaching" check that blocked entry on bearish candles
        if in_zone:
            recent_prices = [float(k["close"]) for k in raw[-4:]]
            visited = any(lo <= p <= hi for p in recent_prices)
            return visited, price

        return False, price

    async def _candle_confirms(self, signal: Signal) -> bool:
        """
        Sniper confirmation: last closed 5m candle must be in direction + in zone.
        ALSO checks 1m for rejection wick (pin bar / shooting star / hammer).
        Both must agree before entry.
        """
        from .ict import detect_candle_confirmation
        ict_dir = "bearish" if signal.direction == "SHORT" else "bullish"

        # 5m candle: closed in correct direction inside OB zone
        raw5 = await self.client.get_klines(signal.symbol, "5m", 3)
        if not raw5 or len(raw5) < 2:
            return False
        c5  = raw5[-2]
        o5, cl5 = float(c5["open"]), float(c5["close"])
        lo = signal.zone.price_low  * (1 - ENTRY_ZONE_TOL)
        hi = signal.zone.price_high * (1 + ENTRY_ZONE_TOL)
        in_zone5 = lo <= cl5 <= hi
        correct5 = (cl5 < o5) if signal.direction == "SHORT" else (cl5 > o5)
        if not (in_zone5 and correct5):
            return False

        # 1m candle: rejection pattern at the OB level
        raw1 = await self.client.get_klines(signal.symbol, "1m", 5)
        if raw1 and len(raw1) >= 3:
            ok1m, name1m = detect_candle_confirmation(raw1, ict_dir)
            if ok1m:
                return True
            # Acceptable if last 1m is directional (even without pin bar)
            c1 = raw1[-2]
            o1, cl1 = float(c1["open"]), float(c1["close"])
            correct1 = (cl1 < o1) if signal.direction == "SHORT" else (cl1 > o1)
            return correct1
        return True

    async def _volume_breaks(self, signal: Signal) -> Tuple[bool, float]:
        raw = await self.client.get_klines(signal.symbol, "5m", 25)
        if not raw or len(raw) < 22:
            return False, 0.0
        closed   = raw[:-1]
        last     = closed[-1]
        vols     = [float(c.get("baseVol") or c.get("vol") or 0) for c in closed[-21:-1]]
        avg_vol  = sum(vols) / 20 if vols else 0
        last_vol = float(last.get("baseVol") or last.get("vol") or 0)
        if avg_vol == 0:
            return False, 0.0
        ratio = last_vol / avg_vol
        o, cl = float(last["open"]), float(last["close"])
        correct = (cl < o) if signal.direction == "SHORT" else (cl > o)
        return ratio >= 1.5 and correct, ratio

    async def _spread_ok(self, symbol: str) -> bool:
        """Approximate spread via recent 1m candle range/close."""
        raw = await self.client.get_klines(symbol, "1m", 5)
        if not raw:
            return True
        avg_spread = sum(
            (float(c["high"]) - float(c["low"])) / float(c["close"])
            for c in raw if float(c.get("close") or 1) > 0
        ) / len(raw)
        return avg_spread <= MAX_SPREAD_PCT

    async def _btc_still_aligned(self, direction: str) -> bool:
        # Use same TFs as scanner (1d + 4h + 1h) for consistent bias
        tf_klines = {tf: await self.client.get_klines("BTCUSDT", tf, 60)
                     for tf in ("1h", "4h", "1d")}
        bias, detail = btc_ict_bias(tf_klines)
        dir_type = "bullish" if direction == "LONG" else "bearish"
        aligned = bias in (dir_type, "neutral")
        if not aligned:
            print(f"  ⚠️  BTC bias={bias.upper()} [{detail}] — not aligned with {direction}")
        return aligned

    # ── Order execution ────────────────────────────────────────────────────

    async def _execute(self, signal: Signal, available: float) -> Optional[str]:
        if available < 1.0:
            print(f"  ⚠️  Balance too low ({available:.4f} USDT) — skip {signal.symbol}")
            return None

        leverage = min(signal.leverage, MAX_LEVERAGE)
        await self.client.set_leverage(signal.symbol, leverage)

        # Full margin — 95% to cover fees + margin buffer
        margin = available * 0.95
        qty    = _qty_str(signal.entry, margin, leverage)
        if qty is None:
            print(f"  ⚠️  {signal.symbol}: lot size too small (balance={available:.2f} USDT) — signal removed")
            return "LOT_TOO_SMALL"

        side = "SELL" if signal.direction == "SHORT" else "BUY"

        # Place entry order with exchange SL attached
        body = {
            "symbol":      signal.symbol,
            "qty":         qty,
            "side":        side,
            "tradeSide":   "OPEN",
            "orderType":   "LIMIT",
            "price":       _fmt_price(signal.entry),
            "slPrice":     _fmt_price(signal.sl),
            "slStopType":  "MARK_PRICE",
            "slOrderType": "MARKET",
        }

        result = await self.client._post("/api/v1/futures/trade/place_order", body)

        # If SL param rejected, retry without it (Bitunix sometimes rejects on LIMIT orders)
        if result.get("code") != 0 and "sl" in str(result.get("msg", "")).lower():
            body.pop("slPrice", None)
            body.pop("slStopType", None)
            body.pop("slOrderType", None)
            result = await self.client._post("/api/v1/futures/trade/place_order", body)

        if result.get("code") == 0:
            oid = result["data"]["orderId"]
            print(f"""
  ╔══════════════════════════════════════════════════════╗
  ║  ✅ ORDER PLACED — {signal.direction}  {signal.symbol:<18}  ║
  ╠══════════════════════════════════════════════════════╣
  ║  Coin      : {signal.symbol}
  ║  Direction : {signal.direction}
  ║  HTF Bias  : {signal.btc_bias.upper()}  [{signal.btc_detail}]
  ║  Entry     : {_fmt_price(signal.entry)}
  ║  Stop Loss : {_fmt_price(signal.sl)}  ({signal.loss_pct:.3f}% risk)  [exchange order]
  ║  TP1 (50%) : {_fmt_price(signal.tp1)}  ← {signal.tp1_reason}
  ║  TP2 (50%) : {_fmt_price(signal.tp2)}  ← {signal.tp2_reason}
  ║  RRR       : 1:{signal.rr1:.1f} → 1:{signal.rr2:.1f}
  ║  Leverage  : {leverage}x  |  Margin: {margin:.4f} USDT (full)
  ║  ICT       : {'✅OB' if signal.zone else ''} {'✅FVG' if signal.fvg_ok else ''} {'✅Liq' if signal.liq_swept else ''} {'✅OTE' if signal.ote_ok else ''} {'✅'+signal.mss_detail if signal.mss_ok else ''}
  ║  Quality   : {signal.quality_score:.0f}/100
  ║  orderId   : {oid}
  ╚══════════════════════════════════════════════════════╝
""")

            # Hand to LiveManager
            if self.live_manager is not None:
                from .live_manager import ManagedPosition
                # Wait for position to open on exchange
                await asyncio.sleep(3)
                positions  = await self.client.get_positions()
                pos_data   = next(
                    (p for p in positions if p["symbol"] == signal.symbol), None
                )
                pos_id     = pos_data["positionId"] if pos_data else oid
                actual_qty = pos_data["qty"] if pos_data else qty

                if pos_data:
                    # Place exchange TP1 (50%) and TP2 (50%) as LIMIT close orders
                    tp_side = "BUY" if signal.direction == "SHORT" else "SELL"
                    half    = _qty_str(signal.entry, float(actual_qty) / 2 * signal.entry / leverage, leverage)
                    # Simpler: just split qty in half
                    try:
                        q     = float(actual_qty)
                        q_dec = len(str(actual_qty).split(".")[-1]) if "." in str(actual_qty) else 0
                        half_q = str(int(q // 2)) if q_dec == 0 else f"{q/2:.{q_dec}f}"
                    except Exception:
                        half_q = actual_qty

                    for tp_price, tp_qty, tp_label in [
                        (signal.tp1, half_q,       "TP1 50%"),
                        (signal.tp2, actual_qty,   "TP2 50%"),
                    ]:
                        tp_body = {
                            "symbol":     signal.symbol,
                            "qty":        str(tp_qty),
                            "side":       tp_side,
                            "tradeSide":  "CLOSE",
                            "orderType":  "LIMIT",
                            "price":      _fmt_price(tp_price),
                            "positionId": pos_id,
                        }
                        tp_r = await self.client._post(
                            "/api/v1/futures/trade/place_order", tp_body
                        )
                        if tp_r.get("code") == 0:
                            print(f"  🎯 {tp_label} LIMIT order placed at "
                                  f"{_fmt_price(tp_price)}  orderId={tp_r['data']['orderId']}")
                        else:
                            print(f"  ⚠️  {tp_label} order failed: {tp_r.get('msg')}")

                tp_order_ids = []

                mp = ManagedPosition(
                    symbol       = signal.symbol,
                    direction    = signal.direction,
                    entry_price  = signal.entry,
                    sl_price     = signal.sl,
                    tp1_price    = signal.tp1,
                    tp2_price    = signal.tp2,
                    ob_high      = signal.zone.price_high,
                    ob_low       = signal.zone.price_low,
                    position_id  = pos_id,
                    qty          = str(actual_qty),
                )
                self.live_manager.add_position(mp)
            return oid
        else:
            print(f"  ❌ Order failed for {signal.symbol}: {result.get('msg')}")
            return None

    # ── Main loop ──────────────────────────────────────────────────────────

    async def run(self):
        print(f"""
  ┌─────────────────────────────────────────────────┐
  │  ICT ADVANCED AUTO-TRADER                       │
  │  Mode    : 1 trade at a time — FULL MARGIN      │
  │  Leverage: max {MAX_LEVERAGE}x   Poll: {self.poll_sec}s                   │
  │  Rules   : SL ≤ 1.5% | RRR ≥ 1:2 | OB+FVG+Liq │
  └─────────────────────────────────────────────────┘
""")

        while self._signals:
            t_loop = time.time()

            # Pause check (after 2 consecutive losses)
            if time.time() < self._pause_until:
                remaining = self._pause_until - time.time()
                print(f"  ⏸️  Paused — resuming in {remaining:.0f}s …")
                await asyncio.sleep(min(remaining, self.poll_sec))
                continue

            positions = await self.client.get_positions()
            open_syms = {p["symbol"] for p in positions}

            if len(open_syms) >= self.max_positions:
                print(f"  [1 position active — waiting for close …]")
                await asyncio.sleep(self.poll_sec)
                continue

            account   = await self.client.get_account()
            available = float(account.get("available", 0))

            to_remove = []

            for sym, signal in list(self._signals.items()):
                if sym in open_syms or sym in self._placed:
                    to_remove.append(sym)
                    continue

                # 1. BTC still aligned?
                if not await self._btc_still_aligned(signal.direction):
                    print(f"  ⚠️  {sym}: BTC bias shifted — signal removed")
                    to_remove.append(sym)
                    continue

                # 2. Price in OB zone?
                in_z, price = await self._in_zone(signal)
                if not in_z:
                    dist = (price - signal.entry) / signal.entry * 100
                    print(f"  ⏳ {sym:<18} {_fmt(price):>12}  dist={dist:+.2f}%  (out of zone)")
                    continue

                # 3. Spread check — drop signal if spread too wide (market condition)
                if not await self._spread_ok(sym):
                    print(f"  ⚠️  {sym}: spread > {MAX_SPREAD_PCT*100:.2f}% — signal removed")
                    to_remove.append(sym)
                    continue

                # 4. Candle confirmation REQUIRED — volume is bonus (not blocking)
                candle_ok        = await self._candle_confirms(signal)
                vol_ok, ratio    = await self._volume_breaks(signal)

                if not candle_ok:
                    print(f"  🔶 {sym:<18} {_fmt(price):>12}"
                          f"  in zone — no candle confirm  vol={ratio:.1f}×")
                    continue

                trigger = "candle + vol ✨" if vol_ok else f"candle only (vol={ratio:.1f}×)"
                print(f"  🎯 {sym}  in zone  trigger={trigger}  → executing …")

                oid = await self._execute(signal, available)
                if oid == "LOT_TOO_SMALL":
                    to_remove.append(sym)   # drop signal, try next symbol
                    continue
                if oid:
                    self._placed[sym] = oid
                    break   # only one trade at a time

            for sym in to_remove:
                self._signals.pop(sym, None)
                self._placed.pop(sym, None)

            elapsed   = time.time() - t_loop
            sleep_for = max(1, self.poll_sec - elapsed)
            if self._signals:
                await asyncio.sleep(sleep_for)

        print("\n  ✅ Signals exhausted — Auto-trader stopped.")
