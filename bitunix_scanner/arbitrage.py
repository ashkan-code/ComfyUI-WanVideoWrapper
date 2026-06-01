"""
Arbitrage Opportunity Engine — Bitunix Futures  (Sniper Edition)

Sniper filters (on top of base filters):
  ① corr >= 0.72 on 100-candle window
  ② corr >= 0.65 on 50-candle window  (stability check)
  ③ |z| >= 2.0
  ④ half-life <= 96h  (OU mean-reversion speed)
  ⑤ net >= 0.18% after all fees
  ⑥ spread <= 0.15%

Score breakdown (0-100):
  z-score      : 25 pts
  net profit   : 25 pts
  corr long    : 15 pts
  corr stable  : 10 pts
  half-life    : 25 pts  (<24h=25, <48h=15, <72h=8, <96h=3)
"""

import asyncio
import math
from dataclasses import dataclass
from statistics import mean, stdev
from typing import Dict, List, Optional, Tuple

from .client import AsyncBitunixClient

# ── settings ──────────────────────────────────────────────────────────────────
TAKER_FEE        = 0.0006
ROUND_TRIP_FEES  = 4 * TAKER_FEE    # 0.24%
SPREAD_FALLBACK  = 0.0004
MAX_SPREAD       = 0.0015            # 0.15%
MIN_NET_PROFIT   = 0.0018            # 0.18%
MIN_CORR         = 0.72              # 100-candle window
MIN_CORR_RECENT  = 0.65              # 50-candle window (stability)
Z_THRESHOLD      = 2.0               # stricter entry
MAX_HALF_LIFE    = 96                # hours — skip slow-reverting pairs
MAX_FLAT_PCT     = 0.20              # max 20% flat candles — removes sticky coins
MIN_VOLATILITY   = 0.0003            # min avg hourly move 0.03% — removes dead coins
LOOKBACK         = 100
TOP_SYMBOLS      = 100               # top 100 by volume
TOP_CANDS        = 20                # spread fetch for top candidates


# ── dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class ArbOpp:
    sym_a:        str
    sym_b:        str
    direction_a:  str
    direction_b:  str
    price_a:      float
    price_b:      float
    z_score:      float
    corr:         float
    corr_recent:  float
    half_life:    float
    ratio_now:    float
    ratio_mean:   float
    ratio_sd:     float
    gross:        float
    fee_cost:     float
    spread_cost:  float
    net:          float
    sim_usdt:     float
    score:        float
    diverge_pct:  float


# ── helpers ───────────────────────────────────────────────────────────────────

def _closes(klines: list) -> List[float]:
    return [float(k["close"]) for k in klines if k.get("close")]


def _is_sticky(closes: List[float]) -> bool:
    """True if coin price barely moves — too many flat candles."""
    if len(closes) < 10:
        return True
    moves = [abs(closes[i] - closes[i-1]) / closes[i-1]
             for i in range(1, len(closes)) if closes[i-1] > 0]
    if not moves:
        return True
    flat     = sum(1 for m in moves if m < 0.0001)   # < 0.01% move per candle
    flat_pct = flat / len(moves)
    avg_move = sum(moves) / len(moves)
    return flat_pct > MAX_FLAT_PCT or avg_move < MIN_VOLATILITY


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


def _half_life(closes_a: List[float], closes_b: List[float]) -> float:
    """
    Ornstein-Uhlenbeck half-life of the ratio spread (in hours for 1h candles).
    Lower = faster mean reversion = better.
    Returns 999 if pair does not mean-revert.
    """
    n = min(len(closes_a), len(closes_b))
    if n < 20:
        return 999.0
    spread = [a / b for a, b in zip(closes_a[-n:], closes_b[-n:]) if b > 0]
    if len(spread) < 10:
        return 999.0
    y  = spread[1:]
    x  = spread[:-1]
    mx = mean(x)
    my = mean(y)
    denom = sum((xi - mx) ** 2 for xi in x)
    if denom == 0:
        return 999.0
    beta = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / denom
    if beta >= 1.0 or beta <= 0.0:
        return 999.0
    return -math.log(2) / math.log(beta)


async def _get_spread_pct(client: AsyncBitunixClient, sym: str) -> float:
    try:
        depth = await client.get_depth(sym, limit=5)
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

def _score(z: float, net: float, corr: float,
           corr_recent: float, half_life: float) -> float:
    s  = min(abs(z) / 5.0, 1.0) * 25                           # z      (25)
    s += min(net / 0.015, 1.0) * 25                            # profit (25)
    s += min(max(corr - 0.65, 0) / 0.35, 1.0) * 15            # corr   (15)
    s += min(max(corr_recent - 0.60, 0) / 0.40, 1.0) * 10     # stable (10)
    if   half_life < 24:  s += 25
    elif half_life < 48:  s += 15
    elif half_life < 72:  s += 8
    elif half_life < 96:  s += 3
    return min(s, 100.0)


def _rank(score: float) -> str:
    if score >= 80: return "SNIPER"
    if score >= 65: return "STRONG"
    if score >= 50: return "VALID"
    return "WEAK"


def _bar(s: float) -> str:
    f = round(s / 10)
    return "#" * f + "." * (10 - f)


# ── main scanner ──────────────────────────────────────────────────────────────

async def scan(client: AsyncBitunixClient) -> List[ArbOpp]:

    # step 1: top symbols by volume
    tickers = await client.get_all_tickers()
    for t in tickers:
        try:    t["_vol"] = float(t.get("baseVol") or 0)
        except: t["_vol"] = 0.0

    top = sorted(tickers, key=lambda t: t["_vol"], reverse=True)[:TOP_SYMBOLS]
    price_map = {t["symbol"]: float(t["lastPrice"])
                 for t in top if t.get("lastPrice") and float(t.get("lastPrice", 0)) > 0}
    symbols = list(price_map.keys())

    # step 2: fetch 1h klines for all
    tasks   = {sym: client.get_klines(sym, "1h", LOOKBACK) for sym in symbols}
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    klines  = {sym: r for sym, r in zip(tasks.keys(), results)
               if isinstance(r, list) and len(r) >= 30}
    closes  = {sym: _closes(klines[sym]) for sym in klines}
    # remove sticky / dead coins
    valid   = [sym for sym, cl in closes.items() if not _is_sticky(cl)]

    # step 3: all pairs — filter by corr + z + half-life
    candidates = []
    half = LOOKBACK // 2

    for i in range(len(valid)):
        for j in range(i + 1, len(valid)):
            a, b = valid[i], valid[j]
            ca, cb = closes[a], closes[b]

            # correlation — full window
            corr_full = _corr(ca, cb)
            if corr_full < MIN_CORR:
                continue

            # correlation — recent window (stability check)
            corr_rec = _corr(ca[-half:], cb[-half:])
            if corr_rec < MIN_CORR_RECENT:
                continue

            # z-score
            cur, mu, sd = _ratio_stats(ca, cb)
            if mu == 0 or sd == 0:
                continue
            z = (cur - mu) / sd
            if abs(z) < Z_THRESHOLD:
                continue

            # half-life filter — skip slow-reverting pairs
            hl = _half_life(ca, cb)
            if hl > MAX_HALF_LIFE:
                continue

            candidates.append((a, b, corr_full, corr_rec, z, cur, mu, sd, hl))

    if not candidates:
        return []

    # step 4: spread fetch for top candidates
    top_cands = sorted(candidates, key=lambda x: abs(x[4]), reverse=True)[:TOP_CANDS]
    unique_syms = list({s for c in top_cands for s in (c[0], c[1])})
    sp_tasks   = {sym: _get_spread_pct(client, sym) for sym in unique_syms}
    sp_results = await asyncio.gather(*sp_tasks.values(), return_exceptions=True)
    spread_map = {sym: (r if isinstance(r, float) else SPREAD_FALLBACK)
                  for sym, r in zip(sp_tasks.keys(), sp_results)}

    # step 5: profit calculation + final score
    opps: List[ArbOpp] = []

    for a, b, corr_full, corr_rec, z, cur, mu, sd, hl in top_cands:
        sp_a = spread_map.get(a, SPREAD_FALLBACK)
        sp_b = spread_map.get(b, SPREAD_FALLBACK)
        if sp_a > MAX_SPREAD or sp_b > MAX_SPREAD:
            continue

        spread_cost = (sp_a + sp_b) / 2
        diverge_pct = abs(cur - mu) / mu
        gross = diverge_pct * 0.5
        net   = gross - ROUND_TRIP_FEES - spread_cost

        if net < MIN_NET_PROFIT:
            continue

        pa, pb = price_map.get(a, 0), price_map.get(b, 0)
        if pa == 0 or pb == 0:
            continue

        s = _score(z, net, corr_full, corr_rec, hl)

        dir_a = "SHORT" if z > 0 else "LONG"
        dir_b = "LONG"  if z > 0 else "SHORT"

        opps.append(ArbOpp(
            sym_a=a, sym_b=b,
            direction_a=dir_a, direction_b=dir_b,
            price_a=pa, price_b=pb,
            z_score=z, corr=corr_full, corr_recent=corr_rec,
            half_life=hl,
            ratio_now=cur, ratio_mean=mu, ratio_sd=sd,
            gross=gross, fee_cost=ROUND_TRIP_FEES,
            spread_cost=spread_cost, net=net,
            sim_usdt=1000 * net,
            score=s, diverge_pct=diverge_pct * 100,
        ))

    opps.sort(key=lambda x: x.score, reverse=True)
    return opps
