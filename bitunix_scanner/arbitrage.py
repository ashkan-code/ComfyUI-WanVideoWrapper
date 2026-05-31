"""
Triangular / Synthetic Arbitrage Engine — Bitunix Futures

از آنجا که Bitunix فقط USDT pairs داره، دو نوع فرصت رو پیدا می‌کنه:

  ① True Triangular  : اگه روزی cross-pair (مثلاً ETHBTC) اضافه شد → گراف رو
                       پیمایش می‌کنه و حلقه‌های ۳ ضلعی واقعی پیدا می‌کنه.

  ② Synthetic Arb    : نسبت قیمت دو ارز همبسته (مثلاً ETHUSDT/BTCUSDT)
                       از میانگین N کندل خارج شد → پوزیشن جهت‌دار می‌گیریم
                       و منتظر برگشت می‌مونیم.

هزینه‌ها (محافظه‌کارانه):
  taker fee  : 0.06% در هر لگ  → round-trip دو لگ: 0.24%
  spread     : از bid-ask order book گرفته میشه؛ fallback: 0.04%/pair
  funding    : هر 8 ساعت چک میشه
  min profit : ≥ 0.35% بعد از همه هزینه‌ها
"""

import asyncio
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from statistics import mean, stdev
from typing import Dict, List, Optional, Tuple

from .client import AsyncBitunixClient

# ── هزینه‌ها ──────────────────────────────────────────────────────────────────
TAKER_FEE     = 0.0006   # 0.06% هر لگ
MIN_NET_PROFIT = 0.0035  # حداقل 0.35% خالص برای نشون دادن
SPREAD_FALLBACK = 0.0004 # 0.04% اگه order book در دسترس نبود
MAX_SPREAD     = 0.0015  # بیشتر از 0.15% → رد کن
CORR_LOOKBACK  = 100     # تعداد کندل برای محاسبه میانگین نسبت
Z_THRESHOLD    = 2.0     # انحراف معیار برای سیگنال
MIN_CORR       = 0.80    # حداقل همبستگی تاریخی

# جفت‌های از پیش‌تعریف‌شده بر اساس همبستگی بالا
KNOWN_PAIRS: List[Tuple[str, str]] = [
    ("ETHUSDT",  "BTCUSDT"),
    ("SOLUSDT",  "ETHUSDT"),
    ("AVAXUSDT", "SOLUSDT"),
    ("BNBUSDT",  "ETHUSDT"),
    ("LINKUSDT", "ETHUSDT"),
    ("DOTUSDT",  "SOLUSDT"),
    ("MATICUSDT","ETHUSDT"),
    ("APTUSDT",  "SOLUSDT"),
    ("ARBUSDT",  "ETHUSDT"),
    ("OPUSDT",   "ETHUSDT"),
    ("SUIUSDT",  "SOLUSDT"),
    ("NEARUSDT", "SOLUSDT"),
    ("ATOMUSDT", "DOTUSDT"),
    ("ADAUSDT",  "SOLUSDT"),
    ("XRPUSDT",  "BNBUSDT"),
    ("LTCUSDT",  "BTCUSDT"),
    ("BCHUSDT",  "BTCUSDT"),
    ("TRXUSDT",  "BNBUSDT"),
    ("FILUSDT",  "ETHUSDT"),
    ("AAVEUSDT", "ETHUSDT"),
]


# ── dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class SpreadInfo:
    symbol:      str
    bid:         float
    ask:         float
    spread_pct:  float
    mid:         float


@dataclass
class ArbOpp:
    kind:          str      # "triangle" | "synthetic"
    sym_a:         str
    sym_b:         str
    sym_c:         str      # برای triangle سومی، برای synthetic ""
    direction_a:   str      # "LONG" | "SHORT"
    direction_b:   str
    price_a:       float
    price_b:       float
    ratio_now:     float    # نسبت فعلی A/B
    ratio_mean:    float    # میانگین تاریخی
    z_score:       float    # انحراف معیار
    gross_profit:  float    # درصد قبل از هزینه
    fee_cost:      float
    spread_cost:   float
    net_profit:    float    # درصد خالص
    sim_profit:    float    # USDT سود با ۱۰۰۰ USDT
    score:         float    # امتیاز 0-100
    detail:        str      # توضیح مختصر


# ── spread fetcher ────────────────────────────────────────────────────────────

async def get_spread(client: AsyncBitunixClient, sym: str) -> SpreadInfo:
    try:
        depth = await client.get_depth(sym, limit=5)
        bids  = depth.get("bids") or depth.get("b") or []
        asks  = depth.get("asks") or depth.get("a") or []
        if bids and asks:
            bid = float(bids[0][0]) if isinstance(bids[0], (list, tuple)) else float(bids[0].get("price", 0))
            ask = float(asks[0][0]) if isinstance(asks[0], (list, tuple)) else float(asks[0].get("price", 0))
            if bid > 0 and ask > 0:
                mid = (bid + ask) / 2
                return SpreadInfo(sym, bid, ask, (ask - bid) / mid, mid)
    except Exception:
        pass
    # fallback: از قیمت تیکر
    return SpreadInfo(sym, 0, 0, SPREAD_FALLBACK, 0)


async def get_spreads_batch(client: AsyncBitunixClient,
                            symbols: List[str]) -> Dict[str, SpreadInfo]:
    tasks = {sym: get_spread(client, sym) for sym in symbols}
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    out = {}
    for sym, r in zip(tasks.keys(), results):
        if isinstance(r, SpreadInfo):
            out[sym] = r
        else:
            out[sym] = SpreadInfo(sym, 0, 0, SPREAD_FALLBACK, 0)
    return out


# ── ratio calculator ──────────────────────────────────────────────────────────

def _ratio_stats(closes_a: List[float], closes_b: List[float]) -> Tuple[float, float, float]:
    """
    نسبت A/B، میانگین، و انحراف معیار.
    returns: (current_ratio, mean_ratio, std_ratio)
    """
    if len(closes_a) < 10 or len(closes_b) < 10:
        return 0, 0, 0
    n   = min(len(closes_a), len(closes_b))
    ca  = closes_a[-n:]
    cb  = closes_b[-n:]
    ratios = [a / b for a, b in zip(ca, cb) if b > 0]
    if len(ratios) < 5:
        return 0, 0, 0
    mu  = mean(ratios)
    sd  = stdev(ratios) if len(ratios) >= 2 else 0
    cur = ratios[-1]
    return cur, mu, sd


def _correlation(a: List[float], b: List[float]) -> float:
    n  = min(len(a), len(b))
    if n < 10:
        return 0
    xa = a[-n:]; xb = b[-n:]
    ma = mean(xa); mb = mean(xb)
    num = sum((x - ma) * (y - mb) for x, y in zip(xa, xb))
    da  = math.sqrt(sum((x - ma)**2 for x in xa))
    db  = math.sqrt(sum((y - mb)**2 for y in xb))
    return num / (da * db) if da * db > 0 else 0


def _closes(klines: list) -> List[float]:
    return [float(k["close"]) for k in klines if k.get("close")]


# ── scoring ───────────────────────────────────────────────────────────────────

def _score(z: float, net_pct: float, spread_pct: float, corr: float) -> float:
    s  = min(abs(z) / 4.0, 1.0) * 30          # z-score (max 30)
    s += min(net_pct / 0.02, 1.0) * 35        # net profit (max 35)
    s += max(0, (0.001 - spread_pct) / 0.001) * 15   # tight spread (max 15)
    s += min(max(corr - 0.8, 0) / 0.2, 1.0) * 20   # correlation (max 20)
    return min(s, 100.0)


def _rank(score: float) -> str:
    if score >= 80: return "🔥🔥 ELITE"
    if score >= 65: return "🔥 STRONG"
    if score >= 50: return "✅ VALID"
    return "⚠️  WEAK"


def _bar(s: float) -> str:
    f = round(s / 10)
    return "█" * f + "░" * (10 - f)


# ── true triangular arb (اگه cross-pair وجود داشت) ───────────────────────────

def find_true_triangles(tickers: List[dict]) -> List[ArbOpp]:
    """
    ساخت گراف قیمتی و پیدا کردن حلقه‌های ۳-ضلعی سودده.
    فعلاً Bitunix فقط USDT pairs داره → معمولاً خالی برمی‌گرده.
    """
    graph: Dict[str, Dict[str, dict]] = defaultdict(dict)

    for t in tickers:
        sym  = t.get("symbol", "")
        last = float(t.get("lastPrice") or 0)
        if last <= 0:
            continue
        # تلاش برای parse کردن جفت‌ارزی
        for quote in ("USDT", "BTC", "ETH", "BNB"):
            if sym.endswith(quote) and len(sym) > len(quote):
                base = sym[: -len(quote)]
                if base:
                    graph[base][quote] = {"sym": sym, "price": last}
                    graph[quote][base] = {"sym": sym, "price": 1.0 / last}
                    break

    found = []
    currencies = [c for c in graph if c != "USDT"]
    for b in currencies:
        if "USDT" not in graph or b not in graph["USDT"]:
            continue
        for c in currencies:
            if c == b:
                continue
            if b not in graph or c not in graph[b]:
                continue
            if c not in graph or "USDT" not in graph[c]:
                continue

            r1 = graph["USDT"][b]["price"]
            r2 = graph[b][c]["price"]
            r3 = graph[c]["USDT"]["price"]

            gross = r1 * r2 * r3 - 1
            fees  = 3 * TAKER_FEE
            spread = 3 * SPREAD_FALLBACK
            net   = gross - fees - spread

            if net >= MIN_NET_PROFIT:
                found.append(ArbOpp(
                    kind="triangle",
                    sym_a=f"{b}USDT", sym_b=graph[b][c]["sym"],
                    sym_c=f"{c}USDT",
                    direction_a="BUY", direction_b="BUY",
                    price_a=1/r1, price_b=1/r2,
                    ratio_now=gross+1, ratio_mean=1.0, z_score=0,
                    gross_profit=gross, fee_cost=fees,
                    spread_cost=spread, net_profit=net,
                    sim_profit=1000 * net,
                    score=_score(3.0, net, SPREAD_FALLBACK, 0.95),
                    detail=f"USDT→{b}→{c}→USDT  gross={gross*100:.3f}%",
                ))

    found.sort(key=lambda x: x.net_profit, reverse=True)
    return found


# ── synthetic arb ─────────────────────────────────────────────────────────────

async def find_synthetic_opps(
    client: AsyncBitunixClient,
    price_map: Dict[str, float],
    pairs: List[Tuple[str, str]] = None,
) -> List[ArbOpp]:
    """
    برای هر جفت همبسته:
      ① ضریب نسبت فعلی vs میانگین تاریخی
      ② اگه z-score > Z_THRESHOLD → سیگنال
      ③ محاسبه سود خالص بعد از هزینه‌ها
    """
    if pairs is None:
        pairs = KNOWN_PAIRS

    # فیلتر جفت‌هایی که قیمت دارن
    valid_pairs = [(a, b) for a, b in pairs
                   if a in price_map and b in price_map]
    if not valid_pairs:
        return []

    # fetch klines همه با هم
    all_syms = list({s for pair in valid_pairs for s in pair})
    kline_tasks = {sym: client.get_klines(sym, "1h", CORR_LOOKBACK)
                   for sym in all_syms}
    kline_results = await asyncio.gather(*kline_tasks.values(), return_exceptions=True)
    klines_map = {}
    for sym, r in zip(kline_tasks.keys(), kline_results):
        if isinstance(r, list):
            klines_map[sym] = r

    # fetch spreads برای جفت‌های valid
    spread_syms = [s for pair in valid_pairs for s in pair]
    spreads = await get_spreads_batch(client, spread_syms)

    found = []
    for sym_a, sym_b in valid_pairs:
        ka = klines_map.get(sym_a, [])
        kb = klines_map.get(sym_b, [])
        if len(ka) < 20 or len(kb) < 20:
            continue

        ca = _closes(ka)
        cb = _closes(kb)

        cur_ratio, mu, sd = _ratio_stats(ca, cb)
        if mu == 0 or sd == 0:
            continue

        z = (cur_ratio - mu) / sd
        if abs(z) < Z_THRESHOLD:
            continue

        corr = _correlation(ca, cb)
        if corr < MIN_CORR:
            continue

        pa = price_map[sym_a]
        pb = price_map[sym_b]

        # spread از order book (یا fallback)
        sp_a = spreads.get(sym_a, SpreadInfo(sym_a, 0, 0, SPREAD_FALLBACK, 0)).spread_pct
        sp_b = spreads.get(sym_b, SpreadInfo(sym_b, 0, 0, SPREAD_FALLBACK, 0)).spread_pct

        if sp_a > MAX_SPREAD or sp_b > MAX_SPREAD:
            continue

        # هزینه round-trip (ورود + خروج هر دو لگ)
        total_spread = (sp_a + sp_b) / 2
        total_fees   = 4 * TAKER_FEE           # 2 لگ × (ورود + خروج)
        total_cost   = total_fees + total_spread

        # تخمین سود از بازگشت به میانگین
        # اگه z=+2.5 → نسبت 2.5σ بالاتر → انتظار داریم به mu برگرده
        revert_pct = abs(z - math.copysign(Z_THRESHOLD * 0.5, z)) * (sd / mu)
        gross      = revert_pct
        net        = gross - total_cost

        if net < MIN_NET_PROFIT:
            continue

        score = _score(z, net, total_spread, corr)
        if score < 30:
            continue

        # جهت: اگه z مثبت → A گران‌تر از حد معمول → SHORT A + LONG B
        if z > 0:
            dir_a, dir_b = "SHORT", "LONG"
            detail = f"{sym_a} گران‌تر از حد (z={z:.2f}σ) → SHORT {sym_a} + LONG {sym_b}"
        else:
            dir_a, dir_b = "LONG", "SHORT"
            detail = f"{sym_a} ارزون‌تر از حد (z={z:.2f}σ) → LONG {sym_a} + SHORT {sym_b}"

        found.append(ArbOpp(
            kind="synthetic",
            sym_a=sym_a, sym_b=sym_b, sym_c="",
            direction_a=dir_a, direction_b=dir_b,
            price_a=pa, price_b=pb,
            ratio_now=cur_ratio, ratio_mean=mu,
            z_score=z, gross_profit=gross,
            fee_cost=total_fees, spread_cost=total_spread,
            net_profit=net, sim_profit=1000 * net,
            score=score, detail=detail,
        ))

    found.sort(key=lambda x: x.score, reverse=True)
    return found
