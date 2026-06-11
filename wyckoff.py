#!/usr/bin/env python3
"""
Wyckoff Spring / Upthrust Scanner -- standalone, no bitunix_scanner/ needed
Display only. NO orders.

Run:  python wyckoff.py
"""
import asyncio
import hashlib
import math
import os
import ssl
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import aiohttp

# ── API keys ──────────────────────────────────────────────────────────────────
API_KEY    = os.getenv("BITUNIX_API_KEY",    "68f0a1765f124bacb847afa8db78e480")
SECRET_KEY = os.getenv("BITUNIX_SECRET_KEY", "159808597389a1cd1fc429f9f469209b")

BASE_URL   = "https://fapi.bitunix.com"
_SEMAPHORE: Optional[asyncio.Semaphore] = None


# =============================================================================
#  Bitunix async client
# =============================================================================

def _get_semaphore() -> asyncio.Semaphore:
    global _SEMAPHORE
    if _SEMAPHORE is None:
        _SEMAPHORE = asyncio.Semaphore(8)
    return _SEMAPHORE


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _make_headers(api_key: str, secret_key: str,
                  query_str: str = "", body_str: str = "") -> dict:
    nonce  = uuid.uuid4().hex
    ts     = str(int(time.time() * 1000))
    digest = _sha256(nonce + ts + api_key + query_str + body_str)
    sign   = _sha256(digest + secret_key)
    return {
        "api-key":      api_key,
        "nonce":        nonce,
        "timestamp":    ts,
        "sign":         sign,
        "Content-Type": "application/json",
    }


class AsyncBitunixClient:
    def __init__(self, api_key: str, secret_key: str,
                 session: Optional[aiohttp.ClientSession] = None):
        self.api_key    = api_key
        self.secret_key = secret_key
        self._session   = session

    async def _get_public(self, path: str, params: dict = None) -> dict:
        sem = _get_semaphore()
        async with sem:
            url = BASE_URL + path
            async with self._session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                return await r.json(content_type=None)

    async def get_all_tickers(self) -> List[dict]:
        data = await self._get_public("/api/v1/futures/market/tickers")
        return data.get("data") or []

    async def get_klines(self, symbol: str, interval: str,
                         limit: int = 200) -> List[dict]:
        data = await self._get_public("/api/v1/futures/market/kline", {
            "symbol":   symbol,
            "interval": interval,
            "limit":    limit,
        })
        return data.get("data") or []


# =============================================================================
#  ICT pure-Python helpers
# =============================================================================

def _parse_klines(raw: list) -> list:
    if not raw:
        return []
    result = []
    for k in raw:
        try:
            result.append({
                "open":  float(k["open"]),
                "high":  float(k["high"]),
                "low":   float(k["low"]),
                "close": float(k["close"]),
                "time":  float(k.get("time", 0)),
            })
        except (KeyError, ValueError, TypeError):
            continue
    result.sort(key=lambda x: x["time"])
    return result


def _atr_vals(klines: list, period: int = 14) -> list:
    n   = len(klines)
    trs = [0.0] * n
    for i in range(1, n):
        h  = klines[i]["high"]
        l  = klines[i]["low"]
        pc = klines[i - 1]["close"]
        trs[i] = max(h - l, abs(h - pc), abs(l - pc))
    atr = [None] * n
    for i in range(period, n):
        atr[i] = sum(trs[i - period + 1: i + 1]) / period
    return atr


def _swing_highs(klines: list, n: int = 3) -> List[int]:
    idxs = []
    for i in range(n, len(klines) - n):
        window = [klines[j]["high"] for j in range(i - n, i + n + 1)]
        if klines[i]["high"] == max(window):
            idxs.append(i)
    return idxs


def _swing_lows(klines: list, n: int = 3) -> List[int]:
    idxs = []
    for i in range(n, len(klines) - n):
        window = [klines[j]["low"] for j in range(i - n, i + n + 1)]
        if klines[i]["low"] == min(window):
            idxs.append(i)
    return idxs


def market_structure(raw: list, lookback: int = 50) -> str:
    klines = _parse_klines(raw)
    if len(klines) > lookback:
        klines = klines[-lookback:]
    if len(klines) < 10:
        return "neutral"
    sh = _swing_highs(klines, n=3)
    sl = _swing_lows(klines,  n=3)
    if len(sh) >= 2 and len(sl) >= 2:
        hh = klines[sh[-1]]["high"] > klines[sh[-2]]["high"]
        hl = klines[sl[-1]]["low"]  > klines[sl[-2]]["low"]
        lh = klines[sh[-1]]["high"] < klines[sh[-2]]["high"]
        ll = klines[sl[-1]]["low"]  < klines[sl[-2]]["low"]
        if hh and hl: return "bullish"
        if lh and ll: return "bearish"
    return "neutral"


def detect_fvg(raw: list, direction: str) -> List[Tuple[float, float]]:
    klines = _parse_klines(raw)
    fvgs: List[Tuple[float, float]] = []
    for i in range(2, len(klines)):
        a = klines[i - 2]
        c = klines[i]
        if direction == "bearish" and a["low"] > c["high"]:
            fvgs.append((float(c["high"]), float(a["low"])))
        elif direction == "bullish" and a["high"] < c["low"]:
            fvgs.append((float(a["high"]), float(c["low"])))
    return list(reversed(fvgs))


def find_liquidity_pools(raw: list, direction: str,
                         entry: float,
                         equal_tol: float = 0.003) -> List[Tuple[float, str]]:
    klines = _parse_klines(raw)
    cands: List[Tuple[float, str]] = []
    if direction == "bearish":
        for idx in _swing_lows(klines, n=3):
            p = klines[idx]["low"]
            if p < entry * 0.9995:
                cands.append((p, "Swing Low"))
        recent = [klines[i]["low"]
                  for i in range(max(0, len(klines) - 40), len(klines))
                  if klines[i]["low"] < entry * 0.9995]
        seen: List[float] = []
        for p in recent:
            if any(abs(p - s) / s <= equal_tol for s in seen):
                cands.append((p, "Equal Lows"))
            seen.append(p)
        cands.sort(key=lambda x: x[0], reverse=True)
    else:
        for idx in _swing_highs(klines, n=3):
            p = klines[idx]["high"]
            if p > entry * 1.0005:
                cands.append((p, "Swing High"))
        recent_h = [klines[i]["high"]
                    for i in range(max(0, len(klines) - 40), len(klines))
                    if klines[i]["high"] > entry * 1.0005]
        seen_h: List[float] = []
        for p in recent_h:
            if any(abs(p - s) / s <= equal_tol for s in seen_h):
                cands.append((p, "Equal Highs"))
            seen_h.append(p)
        cands.sort(key=lambda x: x[0])
    return cands


def detect_liquidity_sweep(raw: list, direction: str) -> Tuple[bool, str]:
    klines = _parse_klines(raw)
    if len(klines) < 15:
        return False, ""
    recent = klines[-30:]
    n = len(recent)
    if direction == "bullish":
        sl_idxs = _swing_lows(recent[:n - 2], n=2)
        for si in reversed(sl_idxs[-4:]):
            level = recent[si]["low"]
            for j in range(si + 1, n):
                c = recent[j]
                if c["low"] < level and c["close"] > level:
                    return True, f"SSL swept {level:.6g}"
    else:
        sh_idxs = _swing_highs(recent[:n - 2], n=2)
        for si in reversed(sh_idxs[-4:]):
            level = recent[si]["high"]
            for j in range(si + 1, n):
                c = recent[j]
                if c["high"] > level and c["close"] < level:
                    return True, f"BSL swept {level:.6g}"
    return False, ""


def detect_wyckoff_spring(raw: list, direction: str,
                           lookback: int = 80,
                           equal_tol: float = 0.001,
                           min_pierce: float = 0.002,
                           wick_ratio: float = 2.5,
                           max_age: int = 4,
                           min_gap: int = 5) -> Tuple[bool, dict]:
    klines = _parse_klines(raw)
    if len(klines) < 30:
        return False, {}
    recent = klines[-lookback:] if len(klines) >= lookback else klines
    n = len(recent)

    if direction == "bullish":
        sl_idxs = _swing_lows(recent[:max(n - 3, 15)], n=3)
        if len(sl_idxs) < 2:
            return False, {}
        for i in range(len(sl_idxs) - 1, 0, -1):
            for j in range(i - 1, -1, -1):
                if sl_idxs[i] - sl_idxs[j] < min_gap:
                    continue
                lo_a = recent[sl_idxs[i]]["low"]
                lo_b = recent[sl_idxs[j]]["low"]
                if abs(lo_a - lo_b) / lo_a > equal_tol:
                    continue
                level = min(lo_a, lo_b)
                second_idx = sl_idxs[i]
                for k in range(second_idx + 1, n):
                    c = recent[k]
                    if c["low"] >= level * (1 - min_pierce):
                        continue
                    if c["close"] < level * 1.001:
                        continue
                    body = abs(c["close"] - c["open"])
                    lw   = min(c["open"], c["close"]) - c["low"]
                    if body == 0 or lw < body * wick_ratio:
                        continue
                    if k < n - max_age:
                        continue
                    return True, {
                        "type":   "Spring",
                        "level":  level,
                        "swept":  c["low"],
                        "close":  c["close"],
                        "pierce": (level - c["low"]) / level * 100,
                        "eq_lo1": lo_a,
                        "eq_lo2": lo_b,
                        "candle": c,
                        "age":    n - 1 - k,
                        "gap":    sl_idxs[i] - sl_idxs[j],
                    }
    else:
        sh_idxs = _swing_highs(recent[:max(n - 3, 15)], n=3)
        if len(sh_idxs) < 2:
            return False, {}
        for i in range(len(sh_idxs) - 1, 0, -1):
            for j in range(i - 1, -1, -1):
                if sh_idxs[i] - sh_idxs[j] < min_gap:
                    continue
                hi_a = recent[sh_idxs[i]]["high"]
                hi_b = recent[sh_idxs[j]]["high"]
                if abs(hi_a - hi_b) / hi_a > equal_tol:
                    continue
                level = max(hi_a, hi_b)
                second_idx = sh_idxs[i]
                for k in range(second_idx + 1, n):
                    c = recent[k]
                    if c["high"] <= level * (1 + min_pierce):
                        continue
                    if c["close"] > level * 0.999:
                        continue
                    body = abs(c["close"] - c["open"])
                    uw   = c["high"] - max(c["open"], c["close"])
                    if body == 0 or uw < body * wick_ratio:
                        continue
                    if k < n - max_age:
                        continue
                    return True, {
                        "type":   "Upthrust",
                        "level":  level,
                        "swept":  c["high"],
                        "close":  c["close"],
                        "pierce": (c["high"] - level) / level * 100,
                        "eq_hi1": hi_a,
                        "eq_hi2": hi_b,
                        "candle": c,
                        "age":    n - 1 - k,
                        "gap":    sh_idxs[i] - sh_idxs[j],
                    }
    return False, {}


def find_tiered_tp(klines_1h: list, klines_4h: list,
                   entry: float, direction: str, sl: float,
                   min_rr: float = 2.0) -> Tuple[float, float, str, str]:
    risk = abs(entry - sl) or entry * 0.01
    tp1: Optional[float] = None
    tp1_r = ""
    tp2: Optional[float] = None
    tp2_r = ""

    for price, label in find_liquidity_pools(klines_1h, direction, entry)[:10]:
        rr = abs(price - entry) / risk
        if rr < min_rr:
            continue
        if direction == "bearish" and price < entry:
            if tp1 is None or price > tp1:
                tp1, tp1_r = price, f"{label} 1h [1:{rr:.1f}]"
        elif direction == "bullish" and price > entry:
            if tp1 is None or price < tp1:
                tp1, tp1_r = price, f"{label} 1h [1:{rr:.1f}]"

    for tf_label, raw in (("4h", klines_4h), ("1h", klines_1h)):
        for flo, fhi in detect_fvg(raw, direction)[:8]:
            mid = (flo + fhi) / 2
            rr  = abs(mid - entry) / risk
            if rr < min_rr * 1.5:
                continue
            if direction == "bearish" and mid < entry:
                if tp2 is None or mid < tp2:
                    tp2, tp2_r = mid, f"FVG {tf_label} [1:{rr:.1f}]"
            elif direction == "bullish" and mid > entry:
                if tp2 is None or mid > tp2:
                    tp2, tp2_r = mid, f"FVG {tf_label} [1:{rr:.1f}]"

    if tp1 is None:
        tp1  = entry - risk * min_rr if direction == "bearish" else entry + risk * min_rr
        tp1_r = "2:1 fallback"
    if tp2 is None:
        tp2  = entry - risk * min_rr * 2 if direction == "bearish" else entry + risk * min_rr * 2
        tp2_r = "4:1 fallback"

    if direction == "bearish" and tp2 > tp1:
        tp2, tp2_r = entry - risk * min_rr * 2, "4:1 adjusted"
    elif direction == "bullish" and tp2 < tp1:
        tp2, tp2_r = entry + risk * min_rr * 2, "4:1 adjusted"

    return tp1, tp2, tp1_r, tp2_r


def btc_ict_bias(tf_klines: dict) -> Tuple[str, str]:
    scores  = {"bullish": 0, "bearish": 0}
    details = []

    raw4h = tf_klines.get("4h", [])
    if raw4h:
        ms4h = market_structure(raw4h, lookback=60)
        details.append(f"4H:{ms4h[0].upper()}")
        if ms4h == "bullish":   scores["bullish"] += 4
        elif ms4h == "bearish": scores["bearish"] += 4
        kl4 = _parse_klines(raw4h)
        if len(kl4) >= 20:
            rec4   = kl4[-60:] if len(kl4) >= 60 else kl4
            sh4    = _swing_highs(rec4, n=3)
            sl4    = _swing_lows(rec4,  n=3)
            last_c = kl4[-1]["close"]
            if len(sh4) >= 2 and last_c > rec4[sh4[-2]]["high"]:
                scores["bullish"] += 3; details.append("4H:BOS+")
            if len(sl4) >= 2 and last_c < rec4[sl4[-2]]["low"]:
                scores["bearish"] += 3; details.append("4H:BOS-")
            if detect_fvg(raw4h, "bullish"): scores["bullish"] += 1
            if detect_fvg(raw4h, "bearish"): scores["bearish"] += 1
            lq_b, _ = detect_liquidity_sweep(raw4h, "bullish")
            lq_s, _ = detect_liquidity_sweep(raw4h, "bearish")
            if lq_b: scores["bullish"] += 1
            if lq_s: scores["bearish"] += 1
            rng_hi = max(k["high"] for k in rec4)
            rng_lo = min(k["low"]  for k in rec4)
            equil  = (rng_hi + rng_lo) / 2
            if last_c < equil:
                scores["bullish"] += 1; details.append("DISC")
            else:
                scores["bearish"] += 1; details.append("PREM")

    raw1h = tf_klines.get("1h", [])
    if raw1h:
        ms1h = market_structure(raw1h, lookback=40)
        details.append(f"1H:{ms1h[0].upper()}")
        if ms1h == "bullish":   scores["bullish"] += 2
        elif ms1h == "bearish": scores["bearish"] += 2
        kl1 = _parse_klines(raw1h)
        if len(kl1) >= 20:
            rec1   = kl1[-40:] if len(kl1) >= 40 else kl1
            sh1    = _swing_highs(rec1, n=2)
            sl1    = _swing_lows(rec1,  n=2)
            last_c = kl1[-1]["close"]
            if len(sh1) >= 2 and last_c > rec1[sh1[-2]]["high"]:
                scores["bullish"] += 1; details.append("1H:BOS+")
            if len(sl1) >= 2 and last_c < rec1[sl1[-2]]["low"]:
                scores["bearish"] += 1; details.append("1H:BOS-")

    raw1d = tf_klines.get("1d", [])
    if raw1d:
        ms1d = market_structure(raw1d, lookback=30)
        details.append(f"D:{ms1d[0].upper()}")
        if ms1d == "bullish":   scores["bullish"] += 2
        elif ms1d == "bearish": scores["bearish"] += 2

    total = scores["bullish"] + scores["bearish"]
    if total == 0:
        return "neutral", " | ".join(details)
    bp = scores["bullish"] / total * 100
    dp = scores["bearish"] / total * 100
    if bp >= 60:
        return "bullish", " | ".join(details) + f"  [{bp:.0f}%+]"
    if dp >= 60:
        return "bearish", " | ".join(details) + f"  [{dp:.0f}%-]"
    return "neutral",  " | ".join(details) + f"  [+{scores['bullish']} -{scores['bearish']}]"


# =============================================================================
#  Spring signal + scoring
# =============================================================================

SL_BUFFER  = 0.005
MIN_RR     = 3.0
BATCH_SIZE = 30
SHOW_TOP   = 5


@dataclass
class SpringSignal:
    symbol:       str
    direction:    str
    tf:           str
    level:        float
    swept:        float
    age:          int
    entry:        float
    sl:           float
    tp:           float
    rr:           float
    leverage:     int
    loss_pct:     float
    score:        float
    score_detail: str
    detail:       dict = field(default_factory=dict)
    btc_bias:     str  = ""
    btc_detail:   str  = ""


def _score_spring(sig: SpringSignal,
                  raw1h: list, raw4h: list,
                  ict_dir: str) -> Tuple[float, str]:
    parts = []
    score = 0.0

    tf_pts = 20 if sig.tf == "1h" else 10
    score += tf_pts
    parts.append(f"TF={tf_pts}")

    c = sig.detail.get("candle", {})
    if c:
        body = abs(float(c.get("close", 0)) - float(c.get("open", 0)))
        if sig.direction == "LONG":
            wick = min(float(c.get("open", 0)), float(c.get("close", 0))) - float(c.get("low", 0))
        else:
            wick = float(c.get("high", 0)) - max(float(c.get("open", 0)), float(c.get("close", 0)))
        ratio  = wick / body if body > 0 else 0
        wk_pts = min(ratio / 4.0, 1.0) * 20
        score += wk_pts
        parts.append(f"wick={wk_pts:.0f}")

    rec_pts = max(0, 15 - sig.age * 1.5)
    score += rec_pts
    parts.append(f"age={rec_pts:.0f}")

    if sig.direction == "LONG":
        l1 = sig.detail.get("eq_lo1", sig.level)
        l2 = sig.detail.get("eq_lo2", sig.level)
    else:
        l1 = sig.detail.get("eq_hi1", sig.level)
        l2 = sig.detail.get("eq_hi2", sig.level)
    tightness = abs(l1 - l2) / sig.level if sig.level > 0 else 0.003
    eq_pts = max(0, (0.003 - tightness) / 0.003) * 10
    score += eq_pts
    parts.append(f"eq={eq_pts:.0f}")

    if raw4h:
        ms4 = market_structure(raw4h, lookback=40)
        if ms4 == ict_dir:
            score += 15; parts.append("4H=[OK]15")
        elif ms4 == "neutral":
            score += 7;  parts.append("4H=[--]7")

    if raw1h and detect_fvg(raw1h, ict_dir):
        score += 10; parts.append("FVG=[OK]10")

    rr_pts = min(sig.rr / 6.0, 1.0) * 10
    score += rr_pts
    parts.append(f"RR={rr_pts:.0f}")

    return min(score, 100.0), " | ".join(parts)


async def _scan_one(client: AsyncBitunixClient,
                    symbol: str, price: float,
                    btc_bias: str, btc_detail: str,
                    direction: str,
                    ict_dir: str) -> Optional[SpringSignal]:
    raw4h = await client.get_klines(symbol, "4h", 80)
    raw1h = await client.get_klines(symbol, "1h", 80)
    best: Optional[SpringSignal] = None

    for tf in ("1h", "15m"):
        raw = raw1h if tf == "1h" else await client.get_klines(symbol, "15m", 80)
        if not raw:
            continue

        found, detail = detect_wyckoff_spring(raw, ict_dir)
        if not found:
            continue

        if direction == "LONG":
            sl       = detail["swept"] * (1 - SL_BUFFER)
            loss_pct = (price - sl) / price * 100
        else:
            sl       = detail["swept"] * (1 + SL_BUFFER)
            loss_pct = (sl - price) / price * 100

        if loss_pct <= 0 or loss_pct > 3.5:
            continue

        try:
            _n, far, _nr, _fr = find_tiered_tp(raw1h, raw4h, price, ict_dir, sl, min_rr=MIN_RR)
            tp = far
        except Exception:
            risk = abs(price - sl)
            tp = (price + risk * 4) if direction == "LONG" else (price - risk * 4)

        rr = abs(tp - price) / abs(sl - price) if sl != price else 0
        if rr < MIN_RR:
            continue

        leverage = max(1, min(10, math.floor(15 / loss_pct)))

        sig = SpringSignal(
            symbol       = symbol,
            direction    = direction,
            tf           = tf,
            level        = detail["level"],
            swept        = detail["swept"],
            age          = detail.get("age", 0),
            entry        = price,
            sl           = sl,
            tp           = tp,
            rr           = rr,
            leverage     = leverage,
            loss_pct     = loss_pct,
            score        = 0.0,
            score_detail = "",
            detail       = detail,
            btc_bias     = btc_bias,
            btc_detail   = btc_detail,
        )
        sig.score, sig.score_detail = _score_spring(sig, raw1h, raw4h, ict_dir)

        if best is None or sig.score > best.score:
            best = sig

    return best


# =============================================================================
#  Display helpers
# =============================================================================

def _fmt_price(p: float) -> str:
    if p >= 1000: return f"{p:,.2f}"
    if p >= 1:    return f"{p:.4f}"
    return f"{p:.6f}"


def _bar(score: float) -> str:
    f = round(score / 10)
    return "#" * f + "." * (10 - f)


def kind_name(direction: str) -> str:
    return "Spring (LONG)" if direction == "LONG" else "Upthrust (SHORT)"


def _format_spring(rank: int, sig: SpringSignal) -> str:
    icon = "LONG " if sig.direction == "LONG" else "SHORT"
    kind = sig.detail.get("type", "Spring")

    if sig.direction == "LONG":
        eq_label = (f"Equal Lows : {_fmt_price(sig.detail.get('eq_lo1', sig.level))}"
                    f" ~ {_fmt_price(sig.detail.get('eq_lo2', sig.level))}")
    else:
        eq_label = (f"Equal Highs: {_fmt_price(sig.detail.get('eq_hi1', sig.level))}"
                    f" ~ {_fmt_price(sig.detail.get('eq_hi2', sig.level))}")

    sl_pct = f"-{sig.loss_pct:.2f}%" if sig.direction == "LONG" else f"+{sig.loss_pct:.2f}%"
    tp_pct = (sig.tp - sig.entry) / sig.entry * 100

    return (
        f"\n{'─'*56}\n"
        f"  #{rank}  {icon} {kind}  --  {sig.symbol}  [{sig.tf.upper()}]\n"
        f"  Score: {sig.score:.0f}/100  {_bar(sig.score)}\n"
        f"{'─'*56}\n"
        f"  BTC       : {sig.btc_bias.upper()}  {sig.btc_detail}\n"
        f"  {eq_label}\n"
        f"  Swept to  : {_fmt_price(sig.swept)}  ({sig.age} candles ago)\n"
        f"  {'─'*50}\n"
        f"  Entry     : MARKET  ~{_fmt_price(sig.entry)}\n"
        f"  Stop Loss : {_fmt_price(sig.sl)}  ({sl_pct})\n"
        f"  TP (100%) : {_fmt_price(sig.tp)}  ({tp_pct:+.2f}%)\n"
        f"  RRR       : 1:{sig.rr:.1f}\n"
        f"  Leverage  : {sig.leverage}x  |  SL={sig.loss_pct:.2f}%\n"
        f"  {'─'*50}\n"
        f"  Breakdown : {sig.score_detail}\n"
        f"{'─'*56}"
    )


# =============================================================================
#  Entry point
# =============================================================================

async def main():
    print("""
+====================================================+
|   Wyckoff Spring / Upthrust Scanner                |
|   All Bitunix symbols -- display only, no orders   |
+====================================================+
""")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode    = ssl.CERT_NONE
    conn = aiohttp.TCPConnector(ssl=ssl_ctx)

    async with aiohttp.ClientSession(connector=conn) as session:
        client = AsyncBitunixClient(API_KEY, SECRET_KEY, session)

        print("  BTC analysis ...", flush=True)
        btc_tf = {tf: await client.get_klines("BTCUSDT", tf, 100)
                  for tf in ("4h", "1h", "1d")}
        btc_bias, btc_detail = btc_ict_bias(btc_tf)
        bias_tag = "BULL" if btc_bias == "bullish" else ("BEAR" if btc_bias == "bearish" else "NEUT")
        print(f"  BTC -> {bias_tag}")
        print(f"     {btc_detail}\n")

        if btc_bias == "neutral":
            print("  BTC neutral -- scanning both directions\n")
            dirs = [("LONG", "bullish"), ("SHORT", "bearish")]
        else:
            direction = "LONG" if btc_bias == "bullish" else "SHORT"
            ict_dir   = "bullish" if direction == "LONG" else "bearish"
            dirs      = [(direction, ict_dir)]

        tickers   = await client.get_all_tickers()
        price_map = {t["symbol"]: float(t["lastPrice"])
                     for t in tickers
                     if t.get("lastPrice") and float(t.get("lastPrice", 0)) > 0}
        symbols   = list(price_map.keys())
        print(f"  Scanning {len(symbols)} symbols ...\n", flush=True)

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
                    if isinstance(r, SpringSignal):
                        found.append(r)
                done = i + len(batch)
                print(f"  {done}/{len(symbols)}  found: {len(found)}"
                      f"  [{time.time() - t0:.0f}s]", flush=True)

        elapsed = time.time() - t0
        print(f"\n{'='*56}")
        print(f"  Done -- {len(found)} springs from {len(symbols)} symbols  [{elapsed:.0f}s]")
        print(f"{'='*56}\n")

        if not found:
            print("  No spring found.\n")
            return

        found.sort(key=lambda s: s.score, reverse=True)

        print(f"\n{'='*60}")
        print(f"  Results -- {len(found)} springs")
        print(f"{'='*60}")
        print(f"  {'#':<4} {'symbol':<16} {'dir':<7} {'TF':<5} {'score':<10}"
              f" {'RRR':<7} {'SL%':<7} {'TP%':<8} pierce")
        print("  " + "-" * 65)
        for i, s in enumerate(found, 1):
            tp_pct  = (s.tp - s.entry) / s.entry * 100
            pierce  = s.detail.get("pierce", 0)
            marker  = "  <- TOP" if s.score >= 70 else ("  <- OK" if s.score >= 55 else "")
            print(f"  #{i:<3} {s.symbol:<16} {s.direction:<7} {s.tf:<5}"
                  f" {s.score:>5.0f}/100  1:{s.rr:.1f}   {s.loss_pct:.1f}%   "
                  f"{tp_pct:+.1f}%   {pierce:.2f}%{marker}")

        print(f"\n{'='*60}")
        print(f"  Full analysis top {min(SHOW_TOP, len(found))}:")
        print(f"{'='*60}\n")
        for rank, sig in enumerate(found[:SHOW_TOP], 1):
            print(_format_spring(rank, sig))

        print(f"\n  Display only -- no orders placed.\n")


if __name__ == "__main__":
    asyncio.run(main())
