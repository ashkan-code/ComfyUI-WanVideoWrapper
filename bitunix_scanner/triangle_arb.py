"""
True Triangular Arbitrage — Bitunix Spot Convert

چرخه سه‌گانه:
  USDT → A → B → USDT

منطق:
  • اگه Spot API در دسترس بود → bid/ask از spot tickers
  • اگه Spot بلاک بود → bid/ask از futures depth (واقعی‌ترین fallback)
  • نرخ ضمنی cross: bid_A / ask_B  (فروش A، خرید B)

چه زمانی سودده است؟
  • وقتی صرافی نرخ Convert را کمی با تأخیر آپدیت کنه
  • وقتی price impact در یک طرف بیشتر باشه
  • اسپرد دو طرف با هم سود بده (نادر روی یک صرافی)

هزینه‌ها:
  Convert fee   : 0.10% هر لگ
  Slippage       : 0.05% هر لگ
  ─────────────────────────────
  Total 3 لگ   : 0.45%
"""

import asyncio
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .spot_client import SpotClient

# ── تنظیمات ───────────────────────────────────────────────────────────────────
CONVERT_FEE_PER_LEG = 0.001    # 0.10% Convert fee
SLIPPAGE_PER_LEG    = 0.0005   # 0.05% slippage
COST_PER_LEG        = CONVERT_FEE_PER_LEG + SLIPPAGE_PER_LEG  # 0.15%
TOTAL_COST          = 3 * COST_PER_LEG                         # 0.45%
MIN_NET_PROFIT      = 0.001    # 0.10% حداقل سود خالص
BASE_AMOUNT         = 1000.0   # USDT — برای نمایش سود
MAX_SPREAD_PCT      = 0.005    # رد اگه اسپرد > 0.5%
TOP_BY_VOLUME       = 80       # فقط top N بر اساس حجم
NEAR_MISS_SHOW      = 5        # نمایش N نزدیک‌ترین حتی اگه سودده نباشن


@dataclass
class Triangle:
    a:           str
    b:           str
    ask_a:       float
    bid_a:       float
    ask_b:       float
    bid_b:       float
    spread_a:    float
    spread_b:    float
    gross:       float
    fee_cost:    float
    spread_cost: float
    net:         float
    profit_usdt: float
    score:       float
    profitable:  bool = True


def _score(net: float, spread_avg: float) -> float:
    s  = min(net / 0.02, 1.0) * 60
    s += max(0, 1 - spread_avg / MAX_SPREAD_PCT) * 40
    return min(s, 100.0)


def _rank(score: float) -> str:
    if score >= 80: return "🔥🔥 ELITE"
    if score >= 60: return "🔥 STRONG"
    if score >= 40: return "✅ VALID"
    return "⚠️  WEAK"


def _bar(s: float) -> str:
    f = round(s / 10)
    return "█" * f + "░" * (10 - f)


# ── داده بازار ────────────────────────────────────────────────────────────────

@dataclass
class PairInfo:
    base:   str
    bid:    float
    ask:    float
    spread: float
    vol:    float


def _float(d: dict, keys: list) -> float:
    for k in keys:
        v = d.get(k)
        if v is not None:
            try:
                f = float(v)
                if math.isfinite(f):
                    return f
            except Exception:
                pass
    return 0.0


def _extract_base(sym: str) -> str:
    for sep in ["/", "_", "-"]:
        if sep in sym:
            return sym.split(sep)[0].upper()
    for q in ["USDT", "USDC", "BUSD"]:
        if sym.endswith(q) and len(sym) > len(q):
            return sym[:-len(q)].upper()
    return ""


def _parse_tickers_with_ba(tickers: List[dict]) -> Dict[str, PairInfo]:
    """استخراج bid/ask از spot tickers (داری bid/ask مستقیم)"""
    result: Dict[str, PairInfo] = {}
    for t in tickers:
        sym = t.get("symbol", "")
        base = _extract_base(sym)
        if not base or base == "USDT":
            continue

        bid  = _float(t, ["bid", "bidPrice", "best_bid", "bestBid"])
        ask  = _float(t, ["ask", "askPrice", "best_ask", "bestAsk"])
        last = _float(t, ["lastPrice", "last", "price"])

        if bid <= 0 or ask <= 0:
            if last > 0:
                bid = last * 0.9995
                ask = last * 1.0005
            else:
                continue

        if ask <= bid or ask <= 0:
            continue

        spread = (ask - bid) / ((ask + bid) / 2)
        if spread > MAX_SPREAD_PCT * 4:
            continue

        vol = _float(t, ["baseVol", "vol24h", "volume", "quoteVol"])
        result[base] = PairInfo(base, bid, ask, spread, vol)
    return result


async def _fetch_ba_from_depth(spot: SpotClient,
                               symbols: List[str]) -> Dict[str, Tuple[float, float]]:
    """
    Fetch bid/ask از depth API برای چند symbol.
    returns: {base: (bid, ask)}
    """
    sem = asyncio.Semaphore(10)

    async def _one(sym: str) -> Tuple[str, float, float]:
        async with sem:
            depth = await spot.get_orderbook(sym + "USDT", limit=1)
            bids  = depth.get("bids") or []
            asks  = depth.get("asks") or []
            if not bids or not asks:
                return sym, 0.0, 0.0
            def _p(x):
                if isinstance(x, (list, tuple)):
                    return float(x[0])
                if isinstance(x, dict):
                    return float(x.get("price") or x.get("p") or 0)
                return float(x)
            return sym, _p(bids[0]), _p(asks[0])

    tasks = [_one(s) for s in symbols]
    raw   = await asyncio.gather(*tasks, return_exceptions=True)
    result = {}
    for r in raw:
        if isinstance(r, tuple) and len(r) == 3:
            sym, bid, ask = r
            if bid > 0 and ask > 0:
                result[sym] = (bid, ask)
    return result


# ── اسکن مثلث‌ها ──────────────────────────────────────────────────────────────

async def scan_triangles(spot: SpotClient) -> List[Triangle]:
    """
    اسکن کامل: USDT → A → B → USDT
    برمیگردونه لیست سودده + (اگه هیچی نبود) نزدیک‌ترین مسیرها
    """

    tickers = await spot.get_tickers()
    if not tickers:
        return []

    # ── step 1: ساخت جدول قیمت ───────────────────────────────────────────────
    pairs = _parse_tickers_with_ba(tickers)

    if len(pairs) < 5:
        return []

    # top N بر اساس حجم
    top_bases = sorted(pairs, key=lambda b: pairs[b].vol, reverse=True)[:TOP_BY_VOLUME]

    # اگه futures fallback بود → bid/ask از tickers تخمینی‌ه، بگیر از depth
    if spot._use_futures_fallback:
        ba_map = await _fetch_ba_from_depth(spot, top_bases)
        for base, (bid, ask) in ba_map.items():
            if base in pairs and bid > 0 and ask > 0:
                sp = (ask - bid) / ((ask + bid) / 2)
                pairs[base] = PairInfo(base, bid, ask, sp, pairs[base].vol)

    top_pairs = {b: pairs[b] for b in top_bases if b in pairs}
    bases = list(top_pairs.keys())

    # ── step 2: همه مثلث‌ها ───────────────────────────────────────────────────
    all_tris: List[Triangle] = []

    for i in range(len(bases)):
        a = bases[i]
        pa = top_pairs[a]

        for j in range(len(bases)):
            if j == i:
                continue
            b = bases[j]
            pb = top_pairs[b]

            # لگ ۱: USDT→A   qty_a = 1 / ask_a
            # لگ ۲: A→B       implicit: qty_b = qty_a × bid_a/ask_b
            # لگ ۳: B→USDT    final = qty_b × bid_b
            qty_a = 1.0 / pa.ask
            qty_b = qty_a * (pa.bid / pb.ask)
            final = qty_b * pb.bid

            gross = final - 1.0
            spread_cost = (pa.spread + pb.spread) / 2
            net = gross - TOTAL_COST - spread_cost

            profitable = net >= MIN_NET_PROFIT
            if not profitable and net < -0.02:
                continue   # خیلی ضررده — نمایش نده

            s = _score(net, (pa.spread + pb.spread) / 2) if profitable else 0.0

            all_tris.append(Triangle(
                a=a, b=b,
                ask_a=pa.ask, bid_a=pa.bid,
                ask_b=pb.ask, bid_b=pb.bid,
                spread_a=pa.spread, spread_b=pb.spread,
                gross=gross, fee_cost=TOTAL_COST,
                spread_cost=spread_cost, net=net,
                profit_usdt=BASE_AMOUNT * net,
                score=s, profitable=profitable,
            ))

    profitable  = [t for t in all_tris if t.profitable]
    profitable.sort(key=lambda x: x.net, reverse=True)

    if profitable:
        return profitable

    # اگه هیچی سودده نبود → برگردون نزدیک‌ترین‌ها برای نمایش
    near = sorted(all_tris, key=lambda x: x.net, reverse=True)[:NEAR_MISS_SHOW]
    for t in near:
        t.profitable = False
    return near
