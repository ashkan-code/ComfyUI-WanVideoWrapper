"""
Auto-trader: monitors signals and executes when entry conditions are confirmed.

Confirmation logic (ICT):
  - Price enters the Order Block zone
  - 5m candle closes in the direction of the trade inside the OB zone
  - BTC bias still aligned
  - No existing position for the symbol
"""

import asyncio
import math
import time
from typing import TYPE_CHECKING, Dict, List, Optional

from .client import AsyncBitunixClient
from .ict import btc_ict_bias
from .signals import Signal, _fmt

if TYPE_CHECKING:
    from .live_manager import LiveManager, ManagedPosition

RISK_PCT = 0.90          # fraction of available balance to use as margin per trade
MAX_POSITIONS = 3        # max simultaneous open positions
POLL_INTERVAL = 30       # seconds between price checks
ENTRY_ZONE_TOL = 0.005   # 0.5%: OB zone ± this fraction counts as "in zone"
MAX_LEVERAGE = 10        # hard cap — never exceed 10x regardless of SL distance

# injected by main after construction
_live_manager: Optional["LiveManager"] = None


def _price_decimals(price: float) -> int:
    if price >= 10_000:
        return 1
    if price >= 1_000:
        return 2
    if price >= 100:
        return 3
    if price >= 10:
        return 4
    if price >= 1:
        return 5
    return 6


def _qty_str(entry: float, margin: float, leverage: int) -> Optional[str]:
    """
    Compute position qty.  Returns None if notional is too small to trade.
    """
    notional = margin * leverage
    qty = notional / entry

    if entry >= 1_000:
        # BTC/ETH range: floor to 3 decimal places
        qty = math.floor(qty * 1_000) / 1_000
        if qty < 0.001:
            return None          # balance too low for minimum lot
        return f"{qty:.3f}"
    if entry >= 1.0:
        qty = math.floor(qty * 100) / 100
        if qty < 0.01:
            return None
        return f"{qty:.2f}".rstrip("0").rstrip(".")
    # sub-$1 coins: whole units
    qty = math.floor(qty)
    if qty < 1:
        return None
    return str(int(qty))


def _fmt_price(price: float) -> str:
    dec = _price_decimals(price)
    return f"{price:.{dec}f}"


class AutoTrader:
    def __init__(self, client: AsyncBitunixClient,
                 max_positions: int = MAX_POSITIONS,
                 risk_pct: float = RISK_PCT,
                 poll_sec: int = POLL_INTERVAL,
                 live_manager: Optional["LiveManager"] = None):
        self.client = client
        self.max_positions = max_positions
        self.risk_pct = risk_pct
        self.poll_sec = poll_sec
        self.live_manager = live_manager
        self._signals: Dict[str, Signal] = {}
        self._placed: Dict[str, str] = {}   # symbol → orderId

    def add_signals(self, signals: List[Signal]):
        for s in signals:
            if s.symbol not in self._signals:
                self._signals[s.symbol] = s
        print(f"\n📋 Loaded {len(self._signals)} signal(s) into monitor.")

    # ── Entry confirmation ─────────────────────────────────────────────────

    async def _in_zone(self, signal: Signal) -> bool:
        """Return True if current price is inside the OB zone (± tolerance)."""
        raw = await self.client.get_klines(signal.symbol, "1m", 1)
        if not raw:
            return False
        price = float(raw[-1]["close"])
        lo = signal.zone.price_low * (1 - ENTRY_ZONE_TOL)
        hi = signal.zone.price_high * (1 + ENTRY_ZONE_TOL)
        return lo <= price <= hi

    async def _candle_confirms(self, signal: Signal) -> tuple[bool, float]:
        """
        Confirmation: last closed 5m candle must match trade direction
        AND be inside the OB zone.
        Returns (confirmed, current_price).
        """
        raw = await self.client.get_klines(signal.symbol, "5m", 3)
        if not raw or len(raw) < 2:
            return False, 0.0

        # Use second-to-last (last fully closed candle)
        candle = raw[-2]
        o, c = float(candle["open"]), float(candle["close"])
        price = float(raw[-1]["close"])  # latest 1m-equivalent

        lo = signal.zone.price_low * (1 - ENTRY_ZONE_TOL)
        hi = signal.zone.price_high * (1 + ENTRY_ZONE_TOL)
        in_zone = lo <= c <= hi

        if signal.direction == "SHORT":
            direction_ok = c < o      # bearish close
        else:
            direction_ok = c > o      # bullish close

        return (in_zone and direction_ok), price

    async def _btc_aligned(self, signal: Signal) -> bool:
        """Re-verify BTC bias still matches signal direction."""
        tf_klines = {}
        for tf in ("1h", "4h", "1d"):
            tf_klines[tf] = await self.client.get_klines("BTCUSDT", tf, 50)
        bias, _ = btc_ict_bias(tf_klines)
        return bias == "neutral" or bias == signal.zone.zone_type

    # ── Order execution ────────────────────────────────────────────────────

    async def _execute(self, signal: Signal, available: float) -> Optional[str]:
        if available < 1.0:
            print(f"  ⚠️  Balance too low ({available:.4f} USDT), skipping {signal.symbol}")
            return None

        # Hard cap: never use leverage above MAX_LEVERAGE (10x)
        leverage = min(signal.leverage, MAX_LEVERAGE)

        # Set leverage on exchange before placing order
        lev_result = await self.client.set_leverage(signal.symbol, leverage)
        if lev_result.get("code") not in (0, None):
            msg = lev_result.get("msg", "unknown")
            # Non-fatal: warn and continue (exchange may already have correct leverage)
            print(f"  ⚠️  {signal.symbol}: set_leverage({leverage}x) → {msg}")

        margin = available * self.risk_pct
        qty = _qty_str(signal.entry, margin, leverage)
        if qty is None:
            print(f"  ⚠️  {signal.symbol}: balance too low for minimum lot size, skipping")
            return None

        side = "SELL" if signal.direction == "SHORT" else "BUY"

        body = {
            "symbol": signal.symbol,
            "qty": qty,
            "side": side,
            "tradeSide": "OPEN",
            "orderType": "LIMIT",
            "price": _fmt_price(signal.entry),
            "slPrice": _fmt_price(signal.sl),
            "slStopType": "MARK_PRICE",
            "slOrderType": "MARKET",
            "tpPrice": _fmt_price(signal.tp),
            "tpStopType": "MARK_PRICE",
            "tpOrderType": "MARKET",
        }

        result = await self.client._post("/api/v1/futures/trade/place_order", body)
        code = result.get("code")
        if code == 0:
            oid = result["data"]["orderId"]
            print(f"\n  ✅ ORDER PLACED  [{signal.direction}  {signal.symbol}]")
            print(f"     qty={qty}  entry={_fmt_price(signal.entry)}")
            print(f"     SL={_fmt_price(signal.sl)}  TP={_fmt_price(signal.tp)}")
            print(f"     leverage={leverage}x  orderId={oid}\n")

            # Hand off to LiveManager for candle-by-candle monitoring
            if self.live_manager is not None:
                from .live_manager import ManagedPosition
                # Fetch actual position_id from exchange
                await asyncio.sleep(1.5)
                positions = await self.client.get_positions()
                pos_id = next(
                    (p["positionId"] for p in positions if p["symbol"] == signal.symbol),
                    oid  # fallback to orderId
                )
                mp = ManagedPosition(
                    symbol=signal.symbol,
                    direction=signal.direction,
                    entry_price=signal.entry,
                    sl_price=signal.sl,
                    tp_price=signal.tp,
                    ob_high=signal.zone.price_high,
                    ob_low=signal.zone.price_low,
                    position_id=pos_id,
                )
                self.live_manager.add_position(mp)
            return oid
        else:
            print(f"  ❌ Order failed for {signal.symbol}: {result.get('msg')}")
            return None

    # ── Main loop ──────────────────────────────────────────────────────────

    async def run(self):
        print(f"""
┌─────────────────────────────────────────────┐
│  AUTO-TRADER ACTIVE                         │
│  Signals monitored : {len(self._signals):>3}                   │
│  Max positions     : {self.max_positions:>3}                   │
│  Poll interval     : {self.poll_sec:>3}s                  │
│  Risk per trade    : {self.risk_pct*100:.0f}% of balance        │
│  Confirmation      : 5m candle in OB zone   │
└─────────────────────────────────────────────┘
""")

        while self._signals:
            t_loop = time.time()

            # Current open positions
            positions = await self.client.get_positions()
            open_syms = {p["symbol"] for p in positions}

            if len(open_syms) >= self.max_positions:
                print(f"  [max positions reached ({self.max_positions})] waiting …")
                await asyncio.sleep(self.poll_sec)
                continue

            account = await self.client.get_account()
            available = float(account.get("available", 0))

            to_remove = []

            for sym, signal in list(self._signals.items()):
                # Already has a position
                if sym in open_syms:
                    to_remove.append(sym)
                    continue

                # Already placed a limit order — wait for fill
                if sym in self._placed:
                    continue

                # ── Confirmation checks ────────────────────────────────
                btc_ok = await self._btc_aligned(signal)
                if not btc_ok:
                    print(f"  ⚠️  {sym}: BTC bias shifted → removing signal")
                    to_remove.append(sym)
                    continue

                confirmed, price = await self._candle_confirms(signal)
                dist_pct = (price - signal.entry) / signal.entry * 100 if price else 0

                if confirmed:
                    oid = await self._execute(signal, available)
                    if oid:
                        self._placed[sym] = oid
                else:
                    in_z = await self._in_zone(signal)
                    zone_mark = "🔶 near zone" if in_z else "      "
                    print(f"  ⏳ {sym:<20}  price={_fmt(price) if price else '?':>12}"
                          f"  entry={_fmt(signal.entry):>12}"
                          f"  dist={dist_pct:+.2f}%  {zone_mark}")

            for sym in to_remove:
                self._signals.pop(sym, None)
                self._placed.pop(sym, None)

            elapsed = time.time() - t_loop
            sleep_for = max(1, self.poll_sec - elapsed)
            if self._signals:
                print(f"  ── next check in {sleep_for:.0f}s ──")
                await asyncio.sleep(sleep_for)

        print("\n✅ All signals processed. Auto-trader stopped.")
