#!/usr/bin/env python3
"""
Wyckoff HTF Alert System
  ۱. اسکن فنر روی Weekly / Daily / 4H
  ۲. نمایش رتبه‌بندی با امتیاز
  ۳. شروع monitor — وقتی قیمت رسید ICT کامل تحلیل می‌کنه

اجرا:  python wyckoff_alert.py
"""
import asyncio, os, ssl, sys, time, math
sys.path.insert(0, os.path.dirname(__file__))

import aiohttp

from bitunix_scanner.client import AsyncBitunixClient
from bitunix_scanner.ict import (
    btc_ict_bias, detect_wyckoff_spring,
    _parse_klines, _swing_lows, _swing_highs, _atr_vals,
    market_structure, detect_fvg,
)
from bitunix_scanner.signals import _fmt
from bitunix_scanner.alert_monitor import AlertMonitor, PriceAlert

API_KEY    = os.getenv("BITUNIX_API_KEY",    "7bee3f4756a0dbc89ae152f34c2175ac")
SECRET_KEY = os.getenv("BITUNIX_SECRET_KEY", "4e0a845778d49068297106a64cbcda61")

# ── پارامترهای اسکن هر TF ─────────────────────────────────────────────────────

TF_CFG = {
    "1w": dict(
        kline_limit = 52,
        equal_tol   = 0.008,   # 0.8% — weekly کندل‌ها نویز بیشتر دارن
        min_pierce  = 0.005,   # 0.5% minimum stop hunt
        wick_ratio  = 2.0,     # کمی آسان‌تر برای weekly
        max_age     = 3,       # فقط 3 هفته اخیر
        min_gap     = 4,       # حداقل 4 هفته بین دو سقف/کف
        base_score  = 40,      # وزن TF (weekly = مهم‌ترین)
    ),
    "1d": dict(
        kline_limit = 120,
        equal_tol   = 0.005,   # 0.5%
        min_pierce  = 0.003,   # 0.3%
        wick_ratio  = 2.2,
        max_age     = 5,       # 5 روز اخیر
        min_gap     = 5,       # حداقل 5 روز بین دو سطح
        base_score  = 30,
    ),
    "4h": dict(
        kline_limit = 200,
        equal_tol   = 0.003,   # 0.3%
        min_pierce  = 0.002,   # 0.2%
        wick_ratio  = 2.5,
        max_age     = 8,       # 8 × 4h = 32 ساعت
        min_gap     = 5,
        base_score  = 20,
    ),
}

SCAN_TFS   = ["1w", "1d", "4h"]
BATCH_SIZE = 15     # همزمان — HTF کندل‌ها سنگین‌تره
SHOW_TOP   = 8      # نمایش top N در جدول
MIN_SCORE  = 35     # حداقل امتیاز برای ثبت alert


# ── امتیازدهی ─────────────────────────────────────────────────────────────────

def _score_htf(detail: dict, tf: str, raw4h: list, ict_dir: str,
               base_score: int) -> float:
    score = float(base_score)

    c = detail.get("candle", {})
    if c:
        body = abs(float(c.get("close", 0)) - float(c.get("open", 0)))
        if ict_dir == "bullish":
            wick = min(float(c.get("open", 0)), float(c.get("close", 0))) - float(c.get("low", 0))
        else:
            wick = float(c.get("high", 0)) - max(float(c.get("open", 0)), float(c.get("close", 0)))
        ratio = wick / body if body > 0 else 0
        score += min(ratio / 5.0, 1.0) * 20   # max 20

    # pierce depth — عمق stop hunt
    pierce = detail.get("pierce", 0)
    score += min(pierce / 2.0, 1.0) * 15      # max 15

    # gap — فاصله بین دو کف/سقف
    gap = detail.get("gap", 0)
    score += min(gap / 20.0, 1.0) * 10        # max 10

    # recency
    age = detail.get("age", 99)
    score += max(0, 1.0 - age / 5.0) * 10     # max 10

    # 4H alignment
    if raw4h:
        ms4 = market_structure(raw4h, lookback=60)
        if ms4 == ict_dir:
            score += 5

    return min(score, 100.0)


# ── اسکن یک ارز روی همه TFها ─────────────────────────────────────────────────

async def _scan_one(client: AsyncBitunixClient,
                    symbol: str, price: float,
                    btc_bias: str, btc_detail: str,
                    direction: str, ict_dir: str):
    raw4h = await client.get_klines(symbol, "4h", 200)
    best  = None

    for tf in SCAN_TFS:
        cfg = TF_CFG[tf]
        raw = await client.get_klines(symbol, tf, cfg["kline_limit"])
        if not raw or len(raw) < 20:
            continue

        found, detail = detect_wyckoff_spring(
            raw, ict_dir,
            lookback    = cfg["kline_limit"],
            equal_tol   = cfg["equal_tol"],
            min_pierce  = cfg["min_pierce"],
            wick_ratio  = cfg["wick_ratio"],
            max_age     = cfg["max_age"],
            min_gap     = cfg["min_gap"],
        )
        if not found:
            continue

        score = _score_htf(detail, tf, raw4h, ict_dir, cfg["base_score"])

        alert = PriceAlert(
            symbol     = symbol,
            direction  = direction,
            tf         = tf,
            level      = detail["level"],
            swept      = detail["swept"],
            pierce_pct = detail.get("pierce", 0),
            score      = score,
            btc_bias   = btc_bias,
        )

        # بالاترین امتیاز در هر TF — نگه‌داشتن بهترین
        if best is None or score > best.score:
            best = alert

    return best


# ── فرمت ─────────────────────────────────────────────────────────────────────

def _bar(s: float) -> str:
    f = round(s / 10)
    return "█" * f + "░" * (10 - f)


def _fmt_alert(rank: int, a: PriceAlert) -> str:
    icon  = "🟢" if a.direction == "LONG" else "🔴"
    kind  = "Spring" if a.direction == "LONG" else "Upthrust"
    age_h = int(a.detected_at)   # placeholder
    return (
        f"{'━'*56}\n"
        f"  #{rank}  {icon} {kind}  ─  {a.symbol}  [{a.tf.upper()}]\n"
        f"  امتیاز : {a.score:.0f}/100  {_bar(a.score)}\n"
        f"{'━'*56}\n"
        f"  سطح فنر : {_fmt(a.level)}\n"
        f"  Swept    : {_fmt(a.swept)}  (pierce {a.pierce_pct:.2f}%)\n"
        f"  BTC Bias : {a.btc_bias.upper()}\n"
        f"  Alert    : وقتی قیمت به سطح نزدیک شد → تحلیل ICT کامل\n"
        f"{'━'*56}"
    )


# ── main ──────────────────────────────────────────────────────────────────────

async def main():
    print("""
╔══════════════════════════════════════════════════════╗
║   Wyckoff HTF Alert  —  Weekly / Daily / 4H        ║
║   اسکن فنر HTF + هشدار قیمتی + تحلیل ICT          ║
╚══════════════════════════════════════════════════════╝
""")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode    = ssl.CERT_NONE
    conn = aiohttp.TCPConnector(ssl=ssl_ctx)

    async with aiohttp.ClientSession(connector=conn) as session:
        client = AsyncBitunixClient(API_KEY, SECRET_KEY, session)
        monitor = AlertMonitor(client)

        # ── BTC bias ─────────────────────────────────────────────────────────
        print("  📊 BTC تحلیل …", flush=True)
        btc_tf = {tf: await client.get_klines("BTCUSDT", tf, 100)
                  for tf in ("4h", "1h", "1d")}
        btc_bias, btc_detail = btc_ict_bias(btc_tf)
        b_icon = "🟢" if btc_bias=="bullish" else ("🔴" if btc_bias=="bearish" else "🟡")
        print(f"  {b_icon} BTC → {btc_bias.upper()}")
        print(f"     {btc_detail}\n")

        if btc_bias == "neutral":
            dirs = [("LONG", "bullish"), ("SHORT", "bearish")]
            print("  🟡 BTC بی‌تصمیمه — هر دو جهت اسکن میشه\n")
        else:
            direction = "LONG" if btc_bias == "bullish" else "SHORT"
            dirs      = [(direction, "bullish" if direction == "LONG" else "bearish")]

        # ── همه ارزها ────────────────────────────────────────────────────────
        tickers = await client.get_all_tickers()
        price_map = {t["symbol"]: float(t["lastPrice"])
                     for t in tickers
                     if t.get("lastPrice") and float(t.get("lastPrice", 0)) > 0}
        symbols = list(price_map.keys())
        print(f"  🔍 اسکن {len(symbols)} ارز روی {SCAN_TFS} …\n", flush=True)

        t0    = time.time()
        found = []

        for direction, ict_dir in dirs:
            for i in range(0, len(symbols), BATCH_SIZE):
                batch   = symbols[i: i + BATCH_SIZE]
                tasks   = [_scan_one(client, sym, price_map[sym],
                                     btc_bias, btc_detail, direction, ict_dir)
                           for sym in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for r in results:
                    if isinstance(r, PriceAlert):
                        found.append(r)
                done = i + len(batch)
                print(f"  {done}/{len(symbols)}  یافته: {len(found)}"
                      f"  [{time.time()-t0:.0f}s]", flush=True)

        elapsed = time.time() - t0
        print(f"\n{'═'*56}")
        print(f"  اسکن تموم شد — {len(found)} فنر HTF از {len(symbols)} ارز  [{elapsed:.0f}s]")
        print(f"{'═'*56}\n")

        if not found:
            print("  هیچ فنر HTF‌ای پیدا نشد.\n")
            return

        # رتبه‌بندی
        found.sort(key=lambda a: a.score, reverse=True)

        # جدول
        print(f"\n{'═'*62}")
        print(f"  نتایج — {len(found)} فنر HTF")
        print(f"{'═'*62}")
        print(f"  {'#':<4} {'ارز':<16} {'جهت':<6} {'TF':<5} {'امتیاز':<10} {'سطح':<14} {'Pierce'}")
        print("  " + "─" * 58)
        for i, a in enumerate(found, 1):
            marker = "  ← 🔥" if a.score >= 65 else ("  ← ✅" if a.score >= 50 else "")
            print(f"  #{i:<3} {a.symbol:<16} {a.direction:<6} {a.tf:<5}"
                  f" {a.score:>5.0f}/100  {_fmt(a.level):<14} {a.pierce_pct:.2f}%{marker}")

        print(f"\n{'═'*62}")
        print(f"  تحلیل کامل top {min(SHOW_TOP, len(found))}:")
        print(f"{'═'*62}\n")

        top = found[:SHOW_TOP]
        for rank, a in enumerate(top, 1):
            print(_fmt_alert(rank, a))

        # ── ثبت alertها ──────────────────────────────────────────────────────
        alert_candidates = [a for a in found if a.score >= MIN_SCORE]
        if not alert_candidates:
            alert_candidates = found[:5]   # حداقل 5 تا

        print(f"\n{'═'*62}")
        print(f"  ثبت {len(alert_candidates)} alert برای نظارت قیمتی:")
        print(f"{'═'*62}")
        for a in alert_candidates:
            monitor.add(a)

        from bitunix_scanner.alert_monitor import POLL_SEC as _poll
        print(f"\n  🔔 شروع نظارت — هر {_poll} ثانیه چک میشه")
        print(f"  Ctrl+C برای خروج\n")

        await monitor.run()


if __name__ == "__main__":
    asyncio.run(main())
