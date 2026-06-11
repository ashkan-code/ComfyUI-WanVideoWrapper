"""
Sniper Alert Monitor -- fires full ICT analysis when price hits Wyckoff HTF level.

Flow:
  1. W/D/4H spring levels registered from wyckoff_alert
  2. Every 60s price checked -- when inside zone
  3. Full ICT MTF analysis + precise Entry/SL/TP
  4. Sniper score 0-100 with rank
  5. Signal printed clean -- no extra noise
"""

import asyncio
import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .client import AsyncBitunixClient
from .ict import (
    market_structure,
    btc_ict_bias,
    detect_fvg,
    detect_liquidity_sweep,
    detect_wyckoff_spring,
    find_tiered_tp,
    find_impulse_for_ote,
    find_ote_zone,
    _parse_klines,
)
from .signals import _fmt

TF_ALERT_ZONE = {
    "1w": 0.025,
    "1d": 0.015,
    "4h": 0.010,
}
SL_BUFFER  = 0.005
MAX_SL_PCT = 0.035
POLL_SEC   = 60


@dataclass
class PriceAlert:
    symbol:      str
    direction:   str
    tf:          str
    level:       float
    swept:       float
    pierce_pct:  float
    wick_ratio:  float
    score:       float
    btc_bias:    str
    triggered:   bool  = False
    detected_at: float = field(default_factory=time.time)


def _sniper_score(
    ict_dir:    str,
    ms_w:  str, ms_d: str, ms_4h: str, ms_1h: str, ms_15: str,
    btc_bias:   str,
    fvg_4h:     bool, fvg_1h: bool,
    liq_4h:     bool, liq_1h: bool,
    spring_4h:  bool, spring_1h: bool,
    ote_in:     bool,
    rr:         float,
    pierce_pct: float,
    wick_ratio: float,
) -> Tuple[float, dict]:
    pts = {}

    pts["W"]  = 8 if ms_w  == ict_dir else (3 if ms_w  == "neutral" else 0)
    pts["D"]  = 8 if ms_d  == ict_dir else (3 if ms_d  == "neutral" else 0)
    pts["4H"] = 7 if ms_4h == ict_dir else (2 if ms_4h == "neutral" else 0)
    pts["1H"] = 5 if ms_1h == ict_dir else (2 if ms_1h == "neutral" else 0)

    btc_ok = (ict_dir == "bullish" and btc_bias == "bullish") or \
             (ict_dir == "bearish" and btc_bias == "bearish")
    pts["BTC"] = 10 if btc_ok else (3 if btc_bias == "neutral" else 0)

    pts["FVG4"] = 7 if fvg_4h else 0
    pts["FVG1"] = 5 if fvg_1h else 0

    pts["LIQ4"] = 5 if liq_4h else 0
    pts["LIQ1"] = 3 if liq_1h else 0

    pierce_pts = min(pierce_pct / 1.5, 1.0) * 8
    wick_pts   = min(wick_ratio / 5.0, 1.0) * 8
    conf_pts   = (4 if spring_4h else 0) + (2 if spring_1h else 0)
    pts["PIERCE"] = pierce_pts
    pts["WICK"]   = wick_pts
    pts["CONF"]   = conf_pts

    pts["RR"] = 12 if rr >= 6 else (10 if rr >= 5 else (8 if rr >= 4 else (5 if rr >= 3 else 0)))

    pts["OTE"] = 8 if ote_in else 0

    total = sum(pts.values())
    return min(total, 100.0), pts


def _rank_label(score: float) -> str:
    if score >= 82: return "ELITE"
    if score >= 68: return "SNIPER"
    if score >= 52: return "VALID"
    return "WEAK"


def _bar(s: float) -> str:
    f = round(s / 10)
    return "#" * f + "." * (10 - f)


def _print_sniper(
    rank:     int,
    alert:    PriceAlert,
    entry:    float,
    sl:       float,
    tp:       float,
    tp_reason:str,
    rr:       float,
    leverage: int,
    loss_pct: float,
    score:    float,
    pts:      dict,
    ms_w:  str, ms_d: str, ms_4h: str, ms_1h: str, ms_15: str,
    btc_bias: str,
    fvg_4h: bool, fvg_1h: bool,
    liq_4h: bool, liq_1h: bool,
    spring_4h: bool, spring_1h: bool,
    ote_in: bool,
    ict_dir: str,
):
    icon      = "LONG " if alert.direction == "LONG" else "SHORT"
    rl        = _rank_label(score)
    sl_sign   = "-" if alert.direction == "LONG" else "+"
    tp_pct    = abs(tp - entry) / entry * 100
    tp_sign   = "+" if alert.direction == "LONG" else "-"
    bar       = _bar(score)

    def si(ms):
        if ms == ict_dir:   return "[OK]"
        if ms == "neutral": return "[--]"
        return "[NO]"

    b_tag = "BULL" if btc_bias == "bullish" else ("BEAR" if btc_bias == "bearish" else "NEUT")

    struct_line = (f"W{si(ms_w)} D{si(ms_d)} 4H{si(ms_4h)} "
                   f"1H{si(ms_1h)} 15M{si(ms_15)}")

    score_detail = (
        f"W+{pts['W']:.0f} D+{pts['D']:.0f} 4H+{pts['4H']:.0f} "
        f"1H+{pts['1H']:.0f} BTC+{pts['BTC']:.0f} "
        f"FVG+{pts['FVG4']+pts['FVG1']:.0f} "
        f"Liq+{pts['LIQ4']+pts['LIQ1']:.0f} "
        f"Spring+{pts['PIERCE']+pts['WICK']+pts['CONF']:.0f} "
        f"RR+{pts['RR']:.0f} OTE+{pts['OTE']:.0f}"
    )

    print(
        f"\n+========================================================+\n"
        f"|  SNIPER #{rank:<2}  {icon}  {alert.symbol:<12} [{alert.tf.upper()}]           |\n"
        f"|  score: {score:>5.1f}/100  {bar}  {rl:<16}          |\n"
        f"+========================================================+\n"
        f"  Entry     :  {_fmt(entry)}\n"
        f"  Stop Loss :  {_fmt(sl)}  ({sl_sign}{loss_pct:.2f}%)  <- below swept low\n"
        f"  TP        :  {_fmt(tp)}  ({tp_sign}{tp_pct:.2f}%)  <- {tp_reason}\n"
        f"  RRR       :  1:{rr:.1f}\n"
        f"  Leverage  :  {leverage}x\n"
        f"  ────────────────────────────────────────────────────\n"
        f"  Structure :  {struct_line}\n"
        f"  BTC       :  {b_tag}\n"
        f"  FVG       :  4H{'[OK]' if fvg_4h else '[NO]'}  1H{'[OK]' if fvg_1h else '[NO]'}\n"
        f"  Liquidity :  4H{'[OK]' if liq_4h else '[NO]'}  1H{'[OK]' if liq_1h else '[NO]'}\n"
        f"  Spring LTF:  4H{'[OK]' if spring_4h else '[NO]'}  1H{'[OK]' if spring_1h else '[NO]'}\n"
        f"  OTE Zone  :  {'[OK] price inside OTE' if ote_in else '[NO] outside OTE'}\n"
        f"  ────────────────────────────────────────────────────\n"
        f"  Breakdown :  {score_detail}\n"
        f"  HTF spring:  level={_fmt(alert.level)}  swept={_fmt(alert.swept)}  pierce={alert.pierce_pct:.2f}%\n"
        f"+========================================================+"
    )


class AlertMonitor:
    def __init__(self, client: AsyncBitunixClient):
        self.client  = client
        self.alerts: List[PriceAlert] = []
        self._rank   = 0

    def add(self, alert: PriceAlert):
        key = (alert.symbol, alert.tf, alert.direction)
        if any((a.symbol, a.tf, a.direction) == key for a in self.alerts):
            return
        self.alerts.append(alert)
        z = TF_ALERT_ZONE.get(alert.tf, 0.015) * 100
        print(f"  + [{alert.tf.upper()}] {alert.direction:<5} {alert.symbol:<16}"
              f"  level={_fmt(alert.level)}  zone=+-{z:.1f}%  score={alert.score:.0f}")

    async def _prices(self) -> Dict[str, float]:
        tickers = await self.client.get_all_tickers()
        return {t["symbol"]: float(t["lastPrice"])
                for t in tickers
                if t.get("lastPrice") and float(t.get("lastPrice", 0)) > 0}

    async def _analyze(self, a: PriceAlert, price: float):
        sym     = a.symbol
        ict_dir = "bullish" if a.direction == "LONG" else "bearish"

        btc_kl = {tf: await self.client.get_klines("BTCUSDT", tf, 100)
                  for tf in ("4h", "1h", "1d")}
        btc_bias, _ = btc_ict_bias(btc_kl)

        c1w  = await self.client.get_klines(sym, "1w",  52)
        c1d  = await self.client.get_klines(sym, "1d", 120)
        c4h  = await self.client.get_klines(sym, "4h", 200)
        c1h  = await self.client.get_klines(sym, "1h", 100)
        c15m = await self.client.get_klines(sym, "15m",  80)

        def ms(kl, lb): return market_structure(kl, lookback=lb) if kl else "neutral"

        ms_w  = ms(c1w,  30)
        ms_d  = ms(c1d,  60)
        ms_4h = ms(c4h,  60)
        ms_1h = ms(c1h,  50)
        ms_15 = ms(c15m, 40)

        fvg_4h = bool(detect_fvg(c4h, ict_dir)) if c4h else False
        fvg_1h = bool(detect_fvg(c1h, ict_dir)) if c1h else False
        liq_4h, _ = detect_liquidity_sweep(c4h, ict_dir) if c4h else (False, "")
        liq_1h, _ = detect_liquidity_sweep(c1h, ict_dir) if c1h else (False, "")

        sp4, _ = detect_wyckoff_spring(c4h, ict_dir,
                     equal_tol=0.003, min_pierce=0.002, wick_ratio=2.0, max_age=10, min_gap=3) \
                 if c4h else (False, {})
        sp1, _ = detect_wyckoff_spring(c1h, ict_dir,
                     equal_tol=0.002, min_pierce=0.002, wick_ratio=2.0, max_age=8,  min_gap=3) \
                 if c1h else (False, {})

        sl = a.swept * (1 - SL_BUFFER) if a.direction == "LONG" \
             else a.swept * (1 + SL_BUFFER)
        loss_pct = abs(price - sl) / price * 100
        if loss_pct > MAX_SL_PCT * 100:
            loss_pct = MAX_SL_PCT * 100
            sl = price * (1 - MAX_SL_PCT) if a.direction == "LONG" \
                 else price * (1 + MAX_SL_PCT)

        try:
            _, tp, _, tp_reason = find_tiered_tp(c1h, c4h, price, ict_dir, sl, min_rr=3.0)
        except Exception:
            risk = abs(price - sl)
            tp = price + risk * 4 if a.direction == "LONG" else price - risk * 4
            tp_reason = "4:1 fallback"

        rr = abs(tp - price) / abs(sl - price) if sl != price else 0
        if rr < 2.0:
            a.triggered = True
            return

        leverage = max(1, min(10, math.floor(15 / loss_pct)))

        sw_lo, sw_hi = find_impulse_for_ote(c4h, ict_dir) if c4h else (price * 0.9, price * 1.1)
        ote_lo, ote_hi = find_ote_zone(sw_lo, sw_hi, ict_dir)
        ote_in = ote_lo <= price <= ote_hi

        score, pts = _sniper_score(
            ict_dir, ms_w, ms_d, ms_4h, ms_1h, ms_15,
            btc_bias,
            fvg_4h, fvg_1h, liq_4h, liq_1h,
            sp4, sp1, ote_in, rr,
            a.pierce_pct, a.wick_ratio,
        )

        self._rank += 1
        _print_sniper(
            self._rank, a, price, sl, tp, tp_reason, rr, leverage, loss_pct,
            score, pts,
            ms_w, ms_d, ms_4h, ms_1h, ms_15,
            btc_bias, fvg_4h, fvg_1h, liq_4h, liq_1h, sp4, sp1, ote_in, ict_dir,
        )
        a.triggered = True

    async def run(self):
        if not self.alerts:
            print("  No alerts registered.")
            return

        print(f"\n{'='*60}")
        print(f"  AlertMonitor -- {len(self.alerts)} levels  [poll={POLL_SEC}s]")
        print(f"{'='*60}")
        print(f"  {'#':<3} {'symbol':<16} {'dir':<6} {'tf':<5} {'level':<14} {'zone'}")
        print("  " + "-" * 52)
        for i, a in enumerate(self.alerts, 1):
            z = TF_ALERT_ZONE.get(a.tf, 0.015) * 100
            print(f"  {i:<3} {a.symbol:<16} {a.direction:<6} {a.tf:<5}"
                  f" {_fmt(a.level):<14} +-{z:.1f}%")
        print(f"{'='*60}\n")

        while True:
            try:
                prices = await self._prices()
                active = [a for a in self.alerts if not a.triggered]
                if not active:
                    print("  All alerts triggered.\n")
                    break

                hits = []
                for a in active:
                    p = prices.get(a.symbol)
                    if not p:
                        continue
                    zone = TF_ALERT_ZONE.get(a.tf, 0.015)
                    hit  = (p <= a.level * (1 + zone)) if a.direction == "LONG" \
                           else (p >= a.level * (1 - zone))
                    if hit:
                        hits.append((a, p))

                for a, p in hits:
                    await self._analyze(a, p)

                if not hits:
                    print(f"  Watching {len(active)} level(s) ...", flush=True)

                await asyncio.sleep(POLL_SEC)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"  AlertMonitor error: {e}")
                await asyncio.sleep(POLL_SEC)
