"""
Alert Monitor — وقتی قیمت به سطح فنر HTF رسید، ICT کامل تحلیل کن.

جریان:
  ۱. سطح‌های فنر W/D/4H از wyckoff_alert.py ثبت میشن
  ۲. هر 60 ثانیه قیمت تمام ارزها چک میشه
  ۳. وقتی قیمت وارد zone فنر شد → تحلیل ICT مولتی TF
  ۴. نمایش verdict کامل (STRONG / MODERATE / WEAK)
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .client import AsyncBitunixClient
from .ict import (
    market_structure,
    btc_ict_bias,
    detect_fvg,
    detect_liquidity_sweep,
    detect_wyckoff_spring,
)
from .signals import _fmt

# وقتی قیمت در این فاصله از سطح فنر بود → trigger
TF_ALERT_ZONE = {
    "1w": 0.025,   # 2.5% برای هفتگی (حرکت بزرگتر)
    "1d": 0.015,   # 1.5% برای روزانه
    "4h": 0.010,   # 1.0% برای چهار ساعته
}

POLL_SEC = 60   # هر 60 ثانیه چک کن


@dataclass
class PriceAlert:
    symbol:      str
    direction:   str    # LONG | SHORT
    tf:          str    # 1w | 1d | 4h
    level:       float  # سطح Equal Lows/Highs
    swept:       float  # نقطه‌ای که wick تا اون رفت
    pierce_pct:  float  # چقدر زیر/بالای سطح رفت
    score:       float  # امتیاز 0–100
    btc_bias:    str
    triggered:   bool  = False
    detected_at: float = field(default_factory=time.time)


def _ms_icon(ms: str, ict_dir: str) -> str:
    if ms == ict_dir:    return "✅"
    if ms == "neutral":  return "🟡"
    return "❌"


class AlertMonitor:
    def __init__(self, client: AsyncBitunixClient):
        self.client = client
        self.alerts: List[PriceAlert] = []

    def add(self, alert: PriceAlert):
        key = (alert.symbol, alert.tf, alert.direction)
        if any((a.symbol, a.tf, a.direction) == key for a in self.alerts):
            return
        self.alerts.append(alert)
        z = TF_ALERT_ZONE.get(alert.tf, 0.015) * 100
        print(f"  🔔 [{alert.tf.upper()}] {alert.direction:<5} {alert.symbol:<16}"
              f"  level={_fmt(alert.level)}  zone=±{z:.1f}%  score={alert.score:.0f}")

    # ── price fetch ───────────────────────────────────────────────────────────

    async def _prices(self) -> Dict[str, float]:
        tickers = await self.client.get_all_tickers()
        return {t["symbol"]: float(t["lastPrice"])
                for t in tickers
                if t.get("lastPrice") and float(t.get("lastPrice", 0)) > 0}

    # ── ICT full analysis ─────────────────────────────────────────────────────

    async def _ict_report(self, a: PriceAlert, price: float):
        sym     = a.symbol
        ict_dir = "bullish" if a.direction == "LONG" else "bearish"
        icon    = "🟢" if a.direction == "LONG" else "🔴"

        # BTC bias
        btc_kl = {tf: await self.client.get_klines("BTCUSDT", tf, 100)
                  for tf in ("4h", "1h", "1d")}
        btc_bias, btc_det = btc_ict_bias(btc_kl)
        b_icon = "🟢" if btc_bias == "bullish" else ("🔴" if btc_bias == "bearish" else "🟡")

        # Symbol klines
        c1w  = await self.client.get_klines(sym, "1w",  52)
        c1d  = await self.client.get_klines(sym, "1d", 120)
        c4h  = await self.client.get_klines(sym, "4h", 180)
        c1h  = await self.client.get_klines(sym, "1h", 100)
        c15m = await self.client.get_klines(sym, "15m",  80)

        def ms(kl, lb):
            return market_structure(kl, lookback=lb) if kl else "neutral"

        ms_w  = ms(c1w,  30)
        ms_d  = ms(c1d,  60)
        ms_4h = ms(c4h,  60)
        ms_1h = ms(c1h,  50)
        ms_15 = ms(c15m, 40)

        # FVG
        fvg4 = detect_fvg(c4h, ict_dir) if c4h else []
        fvg1 = detect_fvg(c1h, ict_dir) if c1h else []

        # Liquidity sweep
        l4ok, l4d = detect_liquidity_sweep(c4h, ict_dir) if c4h else (False, "—")
        l1ok, l1d = detect_liquidity_sweep(c1h, ict_dir) if c1h else (False, "—")

        # HTF spring still valid on lower TFs?
        sp4ok, _ = detect_wyckoff_spring(c4h, ict_dir,
                                          equal_tol=0.003, min_pierce=0.002,
                                          wick_ratio=2.0, max_age=10, min_gap=3) if c4h else (False, {})
        sp1ok, _ = detect_wyckoff_spring(c1h, ict_dir,
                                          equal_tol=0.002, min_pierce=0.002,
                                          wick_ratio=2.0, max_age=8, min_gap=3) if c1h else (False, {})

        # Alignment score
        htf_list = [(ms_w, "W"), (ms_d, "D"), (ms_4h, "4H"), (ms_1h, "1H")]
        aligned  = sum(1 for s, _ in htf_list if s == ict_dir)
        btc_ok   = (a.direction == "LONG"  and btc_bias == "bullish") or \
                   (a.direction == "SHORT" and btc_bias == "bearish")

        # Verdict
        total_pts = aligned * 2 + (2 if btc_ok else 0) + (1 if fvg4 else 0) + \
                    (1 if fvg1 else 0) + (1 if l4ok else 0) + (1 if sp4ok or sp1ok else 0)
        if total_pts >= 9:
            verdict = "🔥 STRONG — ساختار کامله، ورود منطقیه"
        elif total_pts >= 6:
            verdict = "✅ MODERATE — منتظر کندل تأیید ۱۵M بمون"
        else:
            verdict = "⚠️  WEAK — ساختار ضعیفه، ورود نکن"

        fvg4_str = _fmt(fvg4[0][0]) + "–" + _fmt(fvg4[0][1]) if fvg4 else "—"
        fvg1_str = _fmt(fvg1[0][0]) + "–" + _fmt(fvg1[0][1]) if fvg1 else "—"

        print(f"""
{'═'*62}
  🚨  ALERT  {icon}  {a.direction}  {sym}  [{a.tf.upper()}]
  قیمت: {_fmt(price)}   سطح فنر: {_fmt(a.level)}   pierce: {a.pierce_pct:.2f}%
{'═'*62}
  {b_icon} BTC  {btc_bias.upper()}  |  {btc_det}
  {'─'*58}
  ساختار مولتی تایم فریم:
    Weekly  {_ms_icon(ms_w,  ict_dir)}  {ms_w.upper()}
    Daily   {_ms_icon(ms_d,  ict_dir)}  {ms_d.upper()}
    4H      {_ms_icon(ms_4h, ict_dir)}  {ms_4h.upper()}
    1H      {_ms_icon(ms_1h, ict_dir)}  {ms_1h.upper()}
    15M     {_ms_icon(ms_15, ict_dir)}  {ms_15.upper()}
  {'─'*58}
  FVG 4H  : {"✅ " + fvg4_str if fvg4 else "❌ نیست"}
  FVG 1H  : {"✅ " + fvg1_str if fvg1 else "❌ نیست"}
  Liq 4H  : {"✅ " + l4d if l4ok else "❌ " + (l4d or "—")}
  Liq 1H  : {"✅ " + l1d if l1ok else "❌ " + (l1d or "—")}
  فنر 4H  : {"✅ تأیید شد" if sp4ok else "❌ —"}
  فنر 1H  : {"✅ تأیید شد" if sp1ok else "❌ —"}
  {'─'*58}
  همراستایی : {aligned}/4 TF هم‌جهت
  BTC       : {"✅ هم‌راستا" if btc_ok else "❌ مخالف"}  |  امتیاز کل: {total_pts}/12
  {'─'*58}
  ➤  {verdict}
{'═'*62}
""")
        a.triggered = True

    # ── main monitoring loop ──────────────────────────────────────────────────

    async def run(self):
        if not self.alerts:
            print("  ⚠️  هیچ alert‌ای ثبت نشده.")
            return

        print(f"\n{'═'*60}")
        print(f"  🔔 AlertMonitor — {len(self.alerts)} سطح در نظارت  [poll={POLL_SEC}s]")
        print(f"{'═'*60}")
        print(f"  {'#':<3} {'ارز':<16} {'جهت':<6} {'TF':<5} {'سطح':<14} {'zone'}")
        print("  " + "─" * 52)
        for i, a in enumerate(self.alerts, 1):
            z = TF_ALERT_ZONE.get(a.tf, 0.015) * 100
            print(f"  {i:<3} {a.symbol:<16} {a.direction:<6} {a.tf:<5} {_fmt(a.level):<14} ±{z:.1f}%")
        print(f"{'═'*60}\n")

        while True:
            try:
                prices  = await self._prices()
                active  = [a for a in self.alerts if not a.triggered]

                if not active:
                    print("  ✅ همه alertها trigger شدن.\n")
                    break

                hits = []
                for a in active:
                    p = prices.get(a.symbol)
                    if not p:
                        continue
                    zone = TF_ALERT_ZONE.get(a.tf, 0.015)
                    if a.direction == "LONG":
                        hit = p <= a.level * (1 + zone)
                    else:
                        hit = p >= a.level * (1 - zone)
                    if hit:
                        hits.append((a, p))

                for a, p in hits:
                    await self._ict_report(a, p)

                if not hits:
                    remaining = len(active)
                    print(f"  ⏳ {remaining} alert فعال — قیمت‌ها چک شدن …", flush=True)

                await asyncio.sleep(POLL_SEC)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"  ⚠️  AlertMonitor error: {e}")
                await asyncio.sleep(POLL_SEC)
