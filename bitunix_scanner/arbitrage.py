"""
Arbitrage Opportunity Engine — Bitunix Futures

روش:
  ① همه ارزها → top 80 بر اساس حجم
  ② kline 1h (100 کندل) برای همه با هم fetch
  ③ همه جفت‌های ممکن (≈3000) → محاسبه correlation + z-score
  ④ فیلتر: corr>0.60 AND |z|>1.5 AND net>0.15%
  ⑤ رتبه‌بندی بر اساس امتیاز

هزینه واقعی:
  taker fee   : 0.06% × 4 = 0.24%  (ورود+خروج هر دو لگ)
  spread      : از order book (fallback 0.04%/pair)
  min profit  : 0.15% خالص (محافظه‌کارانه)
"""

import asyncio
import math
from dataclasses import dataclass
from statistics import mean, stdev
from typing import Dict, List, Optional, Tuple

from .client import AsyncBitunixClient

# ── تنظیمات ───────────────────────────────────────────────────────────────────
TAKER_FEE       = 0.0006   # 0.06% per leg
ROUND_TRIP_FEES = 4 * TAKER_FEE   # 0.24% — ورود+خروج دو لگ
SPREAD_FALLBACK = 0.0004   # fallback اگه depth نداشت
MAX_SPREAD      = 0.0020   # بیشتر از 0.2% → رد
MIN_NET_PROFIT  = 0.0015   # 0.15% خالص
MIN_CORR        = 0.60     # حداقل همبستگی
Z_THRESHOLD     = 1.5      # انحراف معیار برای سیگنال
LOOKBACK        = 100      # کندل برای آمار نسبت
TOP_SYMBOLS     = 80       # تعداد ارز بر اساس حجم


# ── dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class ArbOpp:
    sym_a:        str
    sym_b:        str
    direction_a:  str       # LONG | SHORT
    direction_b:  str
    price_a:      float
    price_b:      float
    z_score:      float
    corr:         float
    ratio_now:    float
    ratio_mean:   float
    ratio_sd:     float
    gross:        float     # % قبل از هزینه
    fee_cost:     float     # % کارمزد
    spread_cost:  float     # % اسپرد
    net:          float     # % خالص
    sim_usdt:     float     # USDT سود با 1000
    score:        float     # 0-100
    diverge_pct:  float     # % انحراف نسبت از میانگین


# ── helpers ───────────────────────────────────────────────────────────────────

def _closes(klines: list) -> List[float]:
    return [float(k["close"]) for k in klines if k.get("close")]


def _corr(a: List[float], b: List[float]) -> float:
    n = min(len(a), len(b))
    if n < 20:
        return 0.0
    xa, xb = a[-n:], b[-n:]
    ma, mb = mean(xa), mean(xb)
    num = sum((x - ma) * (y - mb) for x, y in zip(xa, xb))
    da  = math.sqrt(sum((x - ma) ** 2 for x in xa))
    db  = math.sqrt(sum((y - mb) ** 2 for y in xb))
    return num / (da * db) if da * db > 0 else 0.0


def _ratio_stats(a: List[float], b: List[float]) -> Tuple[float, float, float]:
    n  = min(len(a), len(b))
    if n < 10:
        return 0, 0, 0
    rs = [x / y for x, y in zip(a[-n:], b[-n:]) if y > 0]
    if len(rs) < 5:
        return 0, 0, 0
    mu = mean(rs)
    sd = stdev(rs) if len(rs) >= 2 else 0
    return rs[-1], mu, sd


async def _get_spread_pct(client: AsyncBitunixClient, sym: str) -> float:
    try:
        depth = await client.get_depth(sym, limit=5)
        # Bitunix depth formats: bids/asks as list of [price, qty]
        bids = depth.get("bids") or depth.get("b") or []
        asks = depth.get("asks") or depth.get("a") or []
        if bids and asks:
            def _p(x):
                if isinstance(x, (list, tuple)): return float(x[0])
                if isinstance(x, dict): return float(x.get("price") or x.get("p") or 0)
                return float(x)
            bid, ask = _p(bids[0]), _p(asks[0])
            if bid > 0 and ask > 0:
                return (ask - bid) / ((bid + ask) / 2)
    except Exception:
        pass
    return SPREAD_FALLBACK


# ── scoring ───────────────────────────────────────────────────────────────────

def _score(z: float, net: float, spread: float, corr: float) -> float:
    s  = min(abs(z) / 5.0,    1.0) * 30   # z-score  (max 30)
    s += min(net   / 0.015,   1.0) * 35   # profit   (max 35)
    s += min(max(corr - 0.60, 0) / 0.40, 1.0) * 20  # corr (max 20)
    s += max(0, 1 - spread / MAX_SPREAD)  * 15       # spread (max 15)
    return min(s, 100.0)


def _rank(score: float) -> str:
    if score >= 80: return "🔥🔥 ELITE"
    if score >= 65: return "🔥 STRONG"
    if score >= 50: return "✅ VALID"
    return "⚠️  MARGINAL"


def _bar(s: float) -> str:
    f = round(s / 10)
    return "█" * f + "░" * (10 - f)


# ── main scanner ──────────────────────────────────────────────────────────────

async def scan(client: AsyncBitunixClient) -> List[ArbOpp]:
    """
    اسکن کامل:
    1. top 80 ارز بر اساس حجم
    2. fetch 1h klines همه با هم
    3. همه جفت‌ها → corr + z-score
    4. فیلتر + امتیاز + مرتب‌سازی
    """

    # ── step 1: top symbols ───────────────────────────────────────────────────
    tickers = await client.get_all_tickers()
    for t in tickers:
        try:    t["_vol"] = float(t.get("baseVol") or 0)
        except: t["_vol"] = 0.0

    top = sorted(tickers, key=lambda t: t["_vol"], reverse=True)[:TOP_SYMBOLS]
    price_map = {t["symbol"]: float(t["lastPrice"])
                 for t in top if t.get("lastPrice") and float(t.get("lastPrice", 0)) > 0}
    symbols = list(price_map.keys())

    # ── step 2: fetch klines ──────────────────────────────────────────────────
    tasks   = {sym: client.get_klines(sym, "1h", LOOKBACK) for sym in symbols}
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    klines  = {sym: r for sym, r in zip(tasks.keys(), results)
               if isinstance(r, list) and len(r) >= 25}
    closes  = {sym: _closes(klines[sym]) for sym in klines}
    valid   = list(closes.keys())

    # ── step 3: همه جفت‌ها ────────────────────────────────────────────────────
    candidates = []
    for i in range(len(valid)):
        for j in range(i + 1, len(valid)):
            a, b = valid[i], valid[j]
            ca, cb = closes[a], closes[b]

            corr_val = _corr(ca, cb)
            if corr_val < MIN_CORR:
                continue

            cur, mu, sd = _ratio_stats(ca, cb)
            if mu == 0 or sd == 0:
                continue

            z = (cur - mu) / sd
            if abs(z) < Z_THRESHOLD:
                continue

            candidates.append((a, b, corr_val, z, cur, mu, sd))

    if not candidates:
        return []

    # ── step 4: spread fetch برای کاندیداهای برتر ─────────────────────────────
    top_cands = sorted(candidates, key=lambda x: abs(x[3]), reverse=True)[:50]
    unique_syms = list({s for c in top_cands for s in (c[0], c[1])})
    spread_tasks   = {sym: _get_spread_pct(client, sym) for sym in unique_syms}
    spread_results = await asyncio.gather(*spread_tasks.values(), return_exceptions=True)
    spread_map = {sym: (r if isinstance(r, float) else SPREAD_FALLBACK)
                  for sym, r in zip(spread_tasks.keys(), spread_results)}

    # ── step 5: محاسبه دقیق سود ──────────────────────────────────────────────
    opps: List[ArbOpp] = []

    for a, b, corr_val, z, cur, mu, sd in top_cands:
        sp_a  = spread_map.get(a, SPREAD_FALLBACK)
        sp_b  = spread_map.get(b, SPREAD_FALLBACK)

        if sp_a > MAX_SPREAD or sp_b > MAX_SPREAD:
            continue

        spread_cost = (sp_a + sp_b) / 2

        # انحراف نسبت از میانگین
        diverge_pct = abs(cur - mu) / mu

        # تخمین سود واقعی:
        # پوزیشن ۵۰/۵۰ — وقتی نسبت برگشت به میانگین:
        # یک لگ سود کرده، دیگری ضرر یا صفر
        # expected move ≈ diverge_pct × 0.5 (محافظه‌کارانه)
        gross = diverge_pct * 0.5
        net   = gross - ROUND_TRIP_FEES - spread_cost

        if net < MIN_NET_PROFIT:
            continue

        pa, pb = price_map.get(a, 0), price_map.get(b, 0)
        if pa == 0 or pb == 0:
            continue

        s = _score(z, net, spread_cost, corr_val)

        dir_a = "SHORT" if z > 0 else "LONG"
        dir_b = "LONG"  if z > 0 else "SHORT"

        opps.append(ArbOpp(
            sym_a=a, sym_b=b,
            direction_a=dir_a, direction_b=dir_b,
            price_a=pa, price_b=pb,
            z_score=z, corr=corr_val,
            ratio_now=cur, ratio_mean=mu, ratio_sd=sd,
            gross=gross, fee_cost=ROUND_TRIP_FEES,
            spread_cost=spread_cost, net=net,
            sim_usdt=1000 * net,
            score=s, diverge_pct=diverge_pct * 100,
        ))

    opps.sort(key=lambda x: x.score, reverse=True)
    return opps
