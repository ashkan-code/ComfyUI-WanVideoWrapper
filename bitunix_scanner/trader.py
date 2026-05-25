"""
Auto-trader with ICT confidence scoring.

Confidence score (0–100):
  OB Zone score    35 pts  (quality of multi-TF OB confluence)
  BTC alignment    25 pts  (how strongly BTC confirms direction)
  TF count         15 pts  (number of TFs with OB in zone)
  Structure align  15 pts  (15m + 1h market structure)
  Entry trigger    10 pts  (candle + volume quality at entry)

Execution rules:
  ≥ 90 pts → FULL MARGIN  (فول مارجین — اعتماد بالا)
  ≥ 70 pts → NORMAL RISK  (self.risk_pct)
  < 70 pts → SKIP         (سیگنال ضعیف — رد می‌شود)

All trades:
  - Max leverage 10x (set on exchange before order)
  - BTC alignment required
  - Price must be in OB zone
  - Candle OR volume confirmation required
  - LiveManager attached immediately after fill
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

RISK_PCT       = 0.90   # default margin fraction when confidence 70–89
MAX_POSITIONS  = 3
POLL_INTERVAL  = 30
ENTRY_ZONE_TOL = 0.005  # ±0.5% OB zone tolerance
MAX_LEVERAGE   = 10

CONF_FULL  = 90   # ≥ this → full margin
CONF_MIN   = 70   # < this → skip trade


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


def _conf_bar(score: float) -> str:
    filled = round(score / 100 * 10)
    return "█" * filled + "░" * (10 - filled)


class AutoTrader:
    def __init__(self, client: AsyncBitunixClient,
                 max_positions: int = MAX_POSITIONS,
                 risk_pct: float = RISK_PCT,
                 poll_sec: int = POLL_INTERVAL,
                 live_manager: Optional["LiveManager"] = None):
        self.client        = client
        self.max_positions = max_positions
        self.risk_pct      = risk_pct
        self.poll_sec      = poll_sec
        self.live_manager  = live_manager
        self._signals: Dict[str, Signal] = {}
        self._placed:  Dict[str, str]    = {}   # symbol → orderId

    def add_signals(self, signals: List[Signal]):
        for s in signals:
            if s.symbol not in self._signals:
                self._signals[s.symbol] = s
        print(f"\n📋 Loaded {len(self._signals)} signal(s) into monitor.")

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _get_vol(candle: dict) -> float:
        for k in ("volume", "vol", "baseVol", "qty"):
            if k in candle:
                try: return float(candle[k])
                except (ValueError, TypeError): pass
        return 0.0

    # ── Entry checks ───────────────────────────────────────────────────────

    async def _in_zone(self, signal: Signal) -> Tuple[bool, float]:
        raw = await self.client.get_klines(signal.symbol, "1m", 1)
        if not raw:
            return False, 0.0
        price = float(raw[-1]["close"])
        lo = signal.zone.price_low  * (1 - ENTRY_ZONE_TOL)
        hi = signal.zone.price_high * (1 + ENTRY_ZONE_TOL)
        return lo <= price <= hi, price

    async def _candle_confirms(self, signal: Signal) -> Tuple[bool, float]:
        """Last closed 5m candle in trade direction + inside OB zone."""
        raw = await self.client.get_klines(signal.symbol, "5m", 3)
        if not raw or len(raw) < 2:
            return False, 0.0
        candle = raw[-2]
        o, c   = float(candle["open"]), float(candle["close"])
        price  = float(raw[-1]["close"])
        lo = signal.zone.price_low  * (1 - ENTRY_ZONE_TOL)
        hi = signal.zone.price_high * (1 + ENTRY_ZONE_TOL)
        in_zone     = lo <= c <= hi
        direction_ok = (c < o) if signal.direction == "SHORT" else (c > o)
        return (in_zone and direction_ok), price

    async def _volume_breaks(self, signal: Signal) -> Tuple[bool, float]:
        """Last closed 5m candle volume > 1.5× 20-candle avg + in trade direction."""
        raw = await self.client.get_klines(signal.symbol, "5m", 25)
        if not raw or len(raw) < 22:
            return False, 0.0
        closed   = raw[:-1]
        last     = closed[-1]
        avg_vol  = sum(self._get_vol(c) for c in closed[-21:-1]) / 20
        last_vol = self._get_vol(last)
        if avg_vol == 0:
            return False, 0.0
        ratio = last_vol / avg_vol
        o, c  = float(last["open"]), float(last["close"])
        direction_ok = (c < o) if signal.direction == "SHORT" else (c > o)
        return (ratio >= 1.5 and direction_ok), ratio

    async def _btc_bias(self) -> Tuple[str, str]:
        """Return (bias, detail) from BTC multi-TF ICT analysis."""
        tf_klines = {tf: await self.client.get_klines("BTCUSDT", tf, 50)
                     for tf in ("1h", "4h", "1d")}
        return btc_ict_bias(tf_klines)

    async def _symbol_structure(self, symbol: str) -> Tuple[str, str]:
        """Return (ms_15m, ms_1h) market structure strings."""
        c15 = await self.client.get_klines(symbol, "15m", 60)
        c1h = await self.client.get_klines(symbol, "1h",  60)
        return market_structure(c15, 40), market_structure(c1h, 40)

    # ── Confidence scoring ─────────────────────────────────────────────────

    def _calc_confidence(self,
                         signal:      Signal,
                         btc_bias:    str,
                         ms_15m:      str,
                         ms_1h:       str,
                         candle_ok:   bool,
                         vol_ok:      bool,
                         vol_ratio:   float) -> float:
        """
        Return 0–100 confidence score for this trade setup.
        """
        score = 0.0
        direction_type = "bullish" if signal.direction == "LONG" else "bearish"

        # 1. OB zone quality (35 pts)
        score += (signal.zone.score / 21) * 35

        # 2. BTC alignment strength (25 pts)
        if btc_bias == direction_type:
            score += 25
        elif btc_bias == "neutral":
            score += 12

        # 3. TF confluence count (15 pts)
        score += (signal.zone.tf_count / 6) * 15

        # 4. Structure alignment on 15m + 1h (15 pts)
        aligned_15 = ms_15m == direction_type
        aligned_1h = ms_1h  == direction_type
        if aligned_15 and aligned_1h:
            score += 15
        elif aligned_15 or aligned_1h:
            score += 8

        # 5. Entry trigger quality (10 pts)
        if candle_ok and vol_ok:
            score += 10 if vol_ratio >= 2.0 else 9
        elif vol_ok:
            score += 8  if vol_ratio >= 2.0 else 6
        elif candle_ok:
            score += 7

        return min(score, 100.0)

    # ── Order execution ────────────────────────────────────────────────────

    async def _execute(self, signal: Signal,
                       available: float,
                       confidence: float) -> Optional[str]:
        if available < 1.0:
            print(f"  ⚠️  Balance too low ({available:.4f} USDT), skipping {signal.symbol}")
            return None

        leverage = min(signal.leverage, MAX_LEVERAGE)

        # Set leverage on exchange
        lev_result = await self.client.set_leverage(signal.symbol, leverage)
        if lev_result.get("code") not in (0, None):
            print(f"  ⚠️  {signal.symbol}: set_leverage({leverage}x) → {lev_result.get('msg')}")

        # Margin allocation based on confidence
        if confidence >= CONF_FULL:
            margin      = available * 0.99   # فول مارجین
            margin_tag  = "FULL MARGIN 💥"
        else:
            margin      = available * self.risk_pct
            margin_tag  = f"{self.risk_pct*100:.0f}% margin"

        qty = _qty_str(signal.entry, margin, leverage)
        if qty is None:
            print(f"  ⚠️  {signal.symbol}: balance too low for minimum lot size, skipping")
            return None

        side = "SELL" if signal.direction == "SHORT" else "BUY"
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
            "tpPrice":     _fmt_price(signal.tp),
            "tpStopType":  "MARK_PRICE",
            "tpOrderType": "MARKET",
        }

        result = await self.client._post("/api/v1/futures/trade/place_order", body)
        if result.get("code") == 0:
            oid = result["data"]["orderId"]
            conf_bar = _conf_bar(confidence)
            print(f"""
  ╔══════════════════════════════════════════════════╗
  ║  ✅ ORDER PLACED  {signal.direction}  {signal.symbol:<16}      ║
  ╠══════════════════════════════════════════════════╣
  ║  اعتماد   : {confidence:5.1f}%  {conf_bar}  {margin_tag:<14}║
  ║  qty      : {qty:<10} entry : {_fmt_price(signal.entry):<12}     ║
  ║  SL       : {_fmt_price(signal.sl):<12} TP    : {_fmt_price(signal.tp):<12}     ║
  ║  Leverage : {leverage}x          orderId: {oid[:12]}…  ║
  ╚══════════════════════════════════════════════════╝
""")

            # Hand off to LiveManager immediately
            if self.live_manager is not None:
                from .live_manager import ManagedPosition
                await asyncio.sleep(1.5)
                positions = await self.client.get_positions()
                pos_id = next(
                    (p["positionId"] for p in positions if p["symbol"] == signal.symbol),
                    oid
                )
                actual_qty = next(
                    (p["qty"] for p in positions if p["symbol"] == signal.symbol),
                    qty
                )
                mp = ManagedPosition(
                    symbol      = signal.symbol,
                    direction   = signal.direction,
                    entry_price = signal.entry,
                    sl_price    = signal.sl,
                    tp_price    = signal.tp,
                    ob_high     = signal.zone.price_high,
                    ob_low      = signal.zone.price_low,
                    position_id = pos_id,
                    qty         = str(actual_qty),
                )
                self.live_manager.add_position(mp)
            return oid
        else:
            print(f"  ❌ Order failed for {signal.symbol}: {result.get('msg')}")
            return None

    # ── Main loop ──────────────────────────────────────────────────────────

    async def run(self):
        print(f"""
┌──────────────────────────────────────────────────┐
│  AUTO-TRADER ACTIVE  (ICT Sniper Mode)           │
│  Signals     : {len(self._signals):>3}                             │
│  Max pos     : {self.max_positions:>3}   Poll: {self.poll_sec:>3}s                  │
│  Full margin : اعتماد ≥ {CONF_FULL}%                    │
│  Normal risk : اعتماد {CONF_MIN}–{CONF_FULL-1}%  ({self.risk_pct*100:.0f}% balance)  │
│  Skip        : اعتماد < {CONF_MIN}%                     │
│  Leverage    : max {MAX_LEVERAGE}x (set on exchange)        │
│  Triggers    : کندل تأیید  یا  شکست حجم          │
└──────────────────────────────────────────────────┘
""")

        while self._signals:
            t_loop = time.time()

            positions = await self.client.get_positions()
            open_syms = {p["symbol"] for p in positions}

            if len(open_syms) >= self.max_positions:
                print(f"  [max positions reached ({self.max_positions})] waiting …")
                await asyncio.sleep(self.poll_sec)
                continue

            account   = await self.client.get_account()
            available = float(account.get("available", 0))

            # Fetch BTC bias once per loop (shared)
            btc_bias, btc_detail = await self._btc_bias()

            to_remove = []

            for sym, signal in list(self._signals.items()):
                if sym in open_syms:
                    to_remove.append(sym)
                    continue
                if sym in self._placed:
                    continue

                # ── 1. BTC alignment (mandatory) ──────────────────────────
                direction_type = "bullish" if signal.direction == "LONG" else "bearish"
                if btc_bias not in (direction_type, "neutral"):
                    print(f"  ⚠️  {sym}: BTC turned {btc_bias.upper()} → signal removed")
                    to_remove.append(sym)
                    continue

                # ── 2. Price must be in OB zone ───────────────────────────
                in_z, price = await self._in_zone(signal)
                dist_pct = (price - signal.entry) / signal.entry * 100 if price else 0
                if not in_z:
                    print(f"  ⏳ {sym:<18} price={_fmt(price):>12}  "
                          f"dist={dist_pct:+.2f}%  (خارج zone)")
                    continue

                # ── 3. Candle OR volume confirmation ──────────────────────
                candle_ok, _  = await self._candle_confirms(signal)
                vol_ok, ratio = await self._volume_breaks(signal)

                if not candle_ok and not vol_ok:
                    print(f"  🔶 {sym:<18} price={_fmt(price):>12}  "
                          f"در zone — منتظر تأیید  vol={ratio:.1f}×")
                    continue

                # ── 4. Symbol market structure ────────────────────────────
                ms_15m, ms_1h = await self._symbol_structure(sym)

                # ── 5. Confidence score ───────────────────────────────────
                confidence = self._calc_confidence(
                    signal, btc_bias, ms_15m, ms_1h,
                    candle_ok, vol_ok, ratio
                )
                trigger_tag = (
                    "کندل+حجم" if (candle_ok and vol_ok)
                    else "کندل" if candle_ok
                    else f"حجم {ratio:.1f}×"
                )

                print(f"  🎯 {sym:<18}  اعتماد: {confidence:.1f}%  {_conf_bar(confidence)}"
                      f"  تأیید: {trigger_tag}  BTC: {btc_bias}")

                if confidence < CONF_MIN:
                    print(f"     ↳ اعتماد پایین ({confidence:.0f}% < {CONF_MIN}%) — رد شد")
                    continue

                # ── 6. Execute ────────────────────────────────────────────
                oid = await self._execute(signal, available, confidence)
                if oid:
                    self._placed[sym] = oid

            for sym in to_remove:
                self._signals.pop(sym, None)
                self._placed.pop(sym, None)

            elapsed   = time.time() - t_loop
            sleep_for = max(1, self.poll_sec - elapsed)
            if self._signals:
                print(f"  ── BTC: {btc_bias.upper()} [{btc_detail}]  "
                      f"next check in {sleep_for:.0f}s ──")
                await asyncio.sleep(sleep_for)

        print("\n✅ All signals processed. Auto-trader stopped.")
