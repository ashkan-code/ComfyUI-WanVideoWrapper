#!/usr/bin/env python3
"""
Wyckoff HTF Alert System  --  standalone, no external packages except aiohttp
  1. Scan spring on Weekly / Daily / 4H
  2. Show ranked results with score
  3. Start monitor -- when price arrives, full ICT analysis fires

Run:  python wyckoff_alert.py
"""
import asyncio
import hashlib
import math
import os
import ssl
import sys
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


def _sort_params(params: dict) -> str:
    return "".join(f"{k}{v}" for k, v in sorted(params.items()))


class AsyncBitunixClient:
    def __init__(self, api_key: str, secret_key: str,
                 session: Optional[aiohttp.ClientSession] = None):
        self.api_key    = api_key
        self.secret_key = secret_key
        self._session   = session
        self._owned     = session is None

    async def __aenter__(self):
        if self._owned:
            self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *_):
        if self._owned and self._session:
            await self._session.close()

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
                level      = min(lo_a, lo_b)
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
                level      = max(hi_a, hi_b)
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


def find_impulse_for_ote(raw: list, direction: str,
                         lookback: int = 50) -> Tuple[float, float]:
    klines = _parse_klines(raw)
    if len(klines) < 10:
        lo = min(k["low"]  for k in klines) if klines else 0.0
        hi = max(k["high"] for k in klines) if klines else 0.0
        return lo, hi
    recent = klines[-lookback:]
    sh = _swing_highs(recent, n=2)
    sl = _swing_lows(recent,  n=2)
    if direction == "bullish":
        for si in reversed(sl):
            later = [j for j in sh if j > si]
            if later:
                return recent[si]["low"], recent[later[0]]["high"]
    else:
        for si in reversed(sh):
            later = [j for j in sl if j > si]
            if later:
                return recent[later[0]]["low"], recent[si]["high"]
    return min(k["low"] for k in recent), max(k["high"] for k in recent)


def find_ote_zone(swing_low: float, swing_high: float,
                  direction: str) -> Tuple[float, float]:
    diff = swing_high - swing_low
    if direction == "bullish":
        return swing_high - diff * 0.79, swing_high - diff * 0.618
    else:
        return swing_low + diff * 0.618, swing_low + diff * 0.79


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
            rec4  = kl4[-60:] if len(kl4) >= 60 else kl4
            sh4   = _swing_highs(rec4, n=3)
            sl4   = _swing_lows(rec4,  n=3)
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
            rec1  = kl1[-40:] if len(kl1) >= 40 else kl1
            sh1   = _swing_highs(rec1, n=2)
            sl1   = _swing_lows(rec1,  n=2)
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
#  Display helpers
# =============================================================================

def _fmt(price: float) -> str:
    if price >= 1000: return f"{price:,.2f}"
    if price >= 1:    return f"{price:.4f}"
    return f"{price:.6f}"


def _bar(s: float) -> str:
    f = round(s / 10)
    return "#" * f + "." * (10 - f)


def _rank_label(score: float) -> str:
    if score >= 82: return "ELITE"
    if score >= 68: return "SNIPER"
    if score >= 52: return "VALID"
    return "WEAK"


# =============================================================================
#  Alert data + monitor
# =============================================================================

TF_ALERT_ZONE = {"1w": 0.025, "1d": 0.015, "4h": 0.010}
SL_BUFFER     = 0.005
MAX_SL_PCT    = 0.035
POLL_SEC      = 60


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
    ict_dir: str,
    ms_w: str, ms_d: str, ms_4h: str, ms_1h: str, ms_15: str,
    btc_bias: str,
    fvg_4h: bool, fvg_1h: bool,
    liq_4h: bool, liq_1h: bool,
    spring_4h: bool, spring_1h: bool,
    ote_in: bool,
    rr: float,
    pierce_pct: float,
    wick_ratio: float,
) -> Tuple[float, dict]:
    pts = {}
    pts["W"]  = 8 if ms_w  == ict_dir else (3 if ms_w  == "neutral" else 0)
    pts["D"]  = 8 if ms_d  == ict_dir else (3 if ms_d  == "neutral" else 0)
    pts["4H"] = 7 if ms_4h == ict_dir else (2 if ms_4h == "neutral" else 0)
    pts["1H"] = 5 if ms_1h == ict_dir else (2 if ms_1h == "neutral" else 0)
    btc_ok = ((ict_dir == "bullish" and btc_bias == "bullish") or
              (ict_dir == "bearish" and btc_bias == "bearish"))
    pts["BTC"]  = 10 if btc_ok else (3 if btc_bias == "neutral" else 0)
    pts["FVG4"] = 7 if fvg_4h else 0
    pts["FVG1"] = 5 if fvg_1h else 0
    pts["LIQ4"] = 5 if liq_4h else 0
    pts["LIQ1"] = 3 if liq_1h else 0
    pts["PIERCE"] = min(pierce_pct / 1.5, 1.0) * 8
    pts["WICK"]   = min(wick_ratio / 5.0, 1.0) * 8
    pts["CONF"]   = (4 if spring_4h else 0) + (2 if spring_1h else 0)
    pts["RR"]  = 12 if rr >= 6 else (10 if rr >= 5 else (8 if rr >= 4 else (5 if rr >= 3 else 0)))
    pts["OTE"] = 8 if ote_in else 0
    return min(sum(pts.values()), 100.0), pts


def _print_sniper(rank, alert, entry, sl, tp, tp_reason, rr, leverage,
                  loss_pct, score, pts, ms_w, ms_d, ms_4h, ms_1h, ms_15,
                  btc_bias, fvg_4h, fvg_1h, liq_4h, liq_1h,
                  spring_4h, spring_1h, ote_in, ict_dir):
    icon    = "LONG " if alert.direction == "LONG" else "SHORT"
    rl      = _rank_label(score)
    sl_sign = "-" if alert.direction == "LONG" else "+"
    tp_pct  = abs(tp - entry) / entry * 100
    tp_sign = "+" if alert.direction == "LONG" else "-"
    b_tag   = "BULL" if btc_bias == "bullish" else ("BEAR" if btc_bias == "bearish" else "NEUT")

    def si(ms):
        if ms == ict_dir:   return "[OK]"
        if ms == "neutral": return "[--]"
        return "[NO]"

    struct_line  = f"W{si(ms_w)} D{si(ms_d)} 4H{si(ms_4h)} 1H{si(ms_1h)} 15M{si(ms_15)}"
    score_detail = (
        f"W+{pts['W']:.0f} D+{pts['D']:.0f} 4H+{pts['4H']:.0f} "
        f"1H+{pts['1H']:.0f} BTC+{pts['BTC']:.0f} "
        f"FVG+{pts['FVG4'] + pts['FVG1']:.0f} "
        f"Liq+{pts['LIQ4'] + pts['LIQ1']:.0f} "
        f"Spring+{pts['PIERCE'] + pts['WICK'] + pts['CONF']:.0f} "
        f"RR+{pts['RR']:.0f} OTE+{pts['OTE']:.0f}"
    )
    print(
        f"\n+========================================================+\n"
        f"|  SNIPER #{rank:<2}  {icon}  {alert.symbol:<12} [{alert.tf.upper()}]           |\n"
        f"|  score: {score:>5.1f}/100  {_bar(score)}  {rl:<16}          |\n"
        f"+========================================================+\n"
        f"  Entry     :  {_fmt(entry)}\n"
        f"  Stop Loss :  {_fmt(sl)}  ({sl_sign}{loss_pct:.2f}%)  <- below swept level\n"
        f"  TP        :  {_fmt(tp)}  ({tp_sign}{tp_pct:.2f}%)  <- {tp_reason}\n"
        f"  RRR       :  1:{rr:.1f}\n"
        f"  Leverage  :  {leverage}x\n"
        f"  --------------------------------------------------------\n"
        f"  Structure :  {struct_line}\n"
        f"  BTC       :  {b_tag}\n"
        f"  FVG       :  4H{'[OK]' if fvg_4h else '[NO]'}  1H{'[OK]' if fvg_1h else '[NO]'}\n"
        f"  Liquidity :  4H{'[OK]' if liq_4h else '[NO]'}  1H{'[OK]' if liq_1h else '[NO]'}\n"
        f"  Spring LTF:  4H{'[OK]' if spring_4h else '[NO]'}  1H{'[OK]' if spring_1h else '[NO]'}\n"
        f"  OTE Zone  :  {'[OK] inside OTE' if ote_in else '[NO] outside OTE'}\n"
        f"  --------------------------------------------------------\n"
        f"  Breakdown :  {score_detail}\n"
        f"  HTF spring:  level={_fmt(alert.level)}  swept={_fmt(alert.swept)}"
        f"  pierce={alert.pierce_pct:.2f}%\n"
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

        sp4, _ = (detect_wyckoff_spring(c4h, ict_dir,
                      equal_tol=0.003, min_pierce=0.002, wick_ratio=2.0, max_age=10, min_gap=3)
                  if c4h else (False, {}))
        sp1, _ = (detect_wyckoff_spring(c1h, ict_dir,
                      equal_tol=0.002, min_pierce=0.002, wick_ratio=2.0, max_age=8,  min_gap=3)
                  if c1h else (False, {}))

        sl       = (a.swept * (1 - SL_BUFFER) if a.direction == "LONG"
                    else a.swept * (1 + SL_BUFFER))
        loss_pct = abs(price - sl) / price * 100
        if loss_pct > MAX_SL_PCT * 100:
            loss_pct = MAX_SL_PCT * 100
            sl = (price * (1 - MAX_SL_PCT) if a.direction == "LONG"
                  else price * (1 + MAX_SL_PCT))

        try:
            _, tp, _, tp_reason = find_tiered_tp(c1h, c4h, price, ict_dir, sl, min_rr=3.0)
        except Exception:
            risk      = abs(price - sl)
            tp        = price + risk * 4 if a.direction == "LONG" else price - risk * 4
            tp_reason = "4:1 fallback"

        rr = abs(tp - price) / abs(sl - price) if sl != price else 0
        if rr < 2.0:
            a.triggered = True
            return

        leverage = max(1, min(10, math.floor(15 / loss_pct)))

        sw_lo, sw_hi   = (find_impulse_for_ote(c4h, ict_dir) if c4h
                          else (price * 0.9, price * 1.1))
        ote_lo, ote_hi = find_ote_zone(sw_lo, sw_hi, ict_dir)
        ote_in         = ote_lo <= price <= ote_hi

        score, pts = _sniper_score(
            ict_dir, ms_w, ms_d, ms_4h, ms_1h, ms_15,
            btc_bias, fvg_4h, fvg_1h, liq_4h, liq_1h,
            sp4, sp1, ote_in, rr, a.pierce_pct, a.wick_ratio,
        )

        self._rank += 1
        _print_sniper(
            self._rank, a, price, sl, tp, tp_reason, rr, leverage, loss_pct,
            score, pts, ms_w, ms_d, ms_4h, ms_1h, ms_15,
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
        print(f"  {'#':<3} {'symbol':<16} {'dir':<6} {'tf':<5} {'level':<14} zone")
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


# =============================================================================
#  Scan configuration
# =============================================================================

TF_CFG = {
    "1w": dict(kline_limit=52,  equal_tol=0.008, min_pierce=0.005,
               wick_ratio=2.0, max_age=3, min_gap=4, base_score=40),
    "1d": dict(kline_limit=120, equal_tol=0.005, min_pierce=0.003,
               wick_ratio=2.2, max_age=5, min_gap=5, base_score=30),
    "4h": dict(kline_limit=200, equal_tol=0.003, min_pierce=0.002,
               wick_ratio=2.5, max_age=8, min_gap=5, base_score=20),
}

SCAN_TFS   = ["1w", "1d", "4h"]
BATCH_SIZE = 15
SHOW_TOP   = 8
MIN_SCORE  = 35


def _score_htf(detail: dict, tf: str, raw4h: list,
               ict_dir: str, base_score: int) -> float:
    score = float(base_score)
    c = detail.get("candle", {})
    if c:
        body = abs(float(c.get("close", 0)) - float(c.get("open", 0)))
        if ict_dir == "bullish":
            wick = min(float(c.get("open", 0)), float(c.get("close", 0))) - float(c.get("low", 0))
        else:
            wick = float(c.get("high", 0)) - max(float(c.get("open", 0)), float(c.get("close", 0)))
        ratio = wick / body if body > 0 else 0
        score += min(ratio / 5.0, 1.0) * 20
    score += min(detail.get("pierce", 0) / 2.0, 1.0) * 15
    score += min(detail.get("gap", 0)    / 20.0, 1.0) * 10
    score += max(0, 1.0 - detail.get("age", 99) / 5.0) * 10
    if raw4h and market_structure(raw4h, lookback=60) == ict_dir:
        score += 5
    return min(score, 100.0)


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
            lookback   = cfg["kline_limit"],
            equal_tol  = cfg["equal_tol"],
            min_pierce = cfg["min_pierce"],
            wick_ratio = cfg["wick_ratio"],
            max_age    = cfg["max_age"],
            min_gap    = cfg["min_gap"],
        )
        if not found:
            continue

        score = _score_htf(detail, tf, raw4h, ict_dir, cfg["base_score"])
        c = detail.get("candle", {})
        if c:
            body = abs(float(c.get("close", 0)) - float(c.get("open", 0)))
            if ict_dir == "bullish":
                wk = min(float(c.get("open", 0)), float(c.get("close", 0))) - float(c.get("low", 0))
            else:
                wk = float(c.get("high", 0)) - max(float(c.get("open", 0)), float(c.get("close", 0)))
            wr = wk / body if body > 0 else 0.0
        else:
            wr = 0.0

        alert = PriceAlert(
            symbol     = symbol,
            direction  = direction,
            tf         = tf,
            level      = detail["level"],
            swept      = detail["swept"],
            pierce_pct = detail.get("pierce", 0),
            wick_ratio = wr,
            score      = score,
            btc_bias   = btc_bias,
        )
        if best is None or score > best.score:
            best = alert

    return best


def _fmt_alert(rank: int, a: PriceAlert) -> str:
    icon  = "L" if a.direction == "LONG" else "S"
    kind  = "Spring" if a.direction == "LONG" else "Upthrust"
    rl    = _rank_label(a.score)
    z     = TF_ALERT_ZONE.get(a.tf, 0.015) * 100
    b_ico = "bull" if a.btc_bias == "bullish" else ("bear" if a.btc_bias == "bearish" else "neut")
    return (
        f"+{'─'*58}+\n"
        f"|  #{rank:<2}  {icon} {kind}  {a.symbol:<14} [{a.tf.upper()}]      |\n"
        f"|  score: {a.score:>5.1f}/100  {_bar(a.score)}  {rl:<16}|\n"
        f"+{'─'*58}+\n"
        f"|  level   : {_fmt(a.level):<16}  pierce: {a.pierce_pct:.2f}%           |\n"
        f"|  swept   : {_fmt(a.swept):<16}  wick: {a.wick_ratio:.1f}x              |\n"
        f"|  BTC     : {b_ico:<10}  alert zone: +-{z:.1f}%              |\n"
        f"|  Waiting for price -- sniper signal on trigger          |\n"
        f"+{'─'*58}+"
    )


# =============================================================================
#  Entry point
# =============================================================================

async def main():
    print("""
+====================================================+
|   Wyckoff HTF Alert  --  Weekly / Daily / 4H       |
|   HTF spring scan + price alert + ICT analysis     |
|   DISPLAY ONLY -- no orders placed ever            |
+====================================================+
""")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode    = ssl.CERT_NONE
    conn = aiohttp.TCPConnector(ssl=ssl_ctx)

    async with aiohttp.ClientSession(connector=conn) as session:
        client  = AsyncBitunixClient(API_KEY, SECRET_KEY, session)
        monitor = AlertMonitor(client)

        print("  BTC analysis ...", flush=True)
        btc_tf = {tf: await client.get_klines("BTCUSDT", tf, 100)
                  for tf in ("4h", "1h", "1d")}
        btc_bias, btc_detail = btc_ict_bias(btc_tf)
        b_tag = "BULL" if btc_bias == "bullish" else ("BEAR" if btc_bias == "bearish" else "NEUT")
        print(f"  BTC -> {b_tag}")
        print(f"     {btc_detail}\n")

        if btc_bias == "neutral":
            dirs = [("LONG", "bullish"), ("SHORT", "bearish")]
            print("  BTC neutral -- scanning both directions\n")
        else:
            direction = "LONG" if btc_bias == "bullish" else "SHORT"
            dirs      = [(direction, "bullish" if direction == "LONG" else "bearish")]

        tickers   = await client.get_all_tickers()
        price_map = {t["symbol"]: float(t["lastPrice"])
                     for t in tickers
                     if t.get("lastPrice") and float(t.get("lastPrice", 0)) > 0}
        symbols   = list(price_map.keys())
        print(f"  Scanning {len(symbols)} symbols on {SCAN_TFS} ...\n", flush=True)

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
                print(f"  {done}/{len(symbols)}  found: {len(found)}"
                      f"  [{time.time() - t0:.0f}s]", flush=True)

        elapsed = time.time() - t0
        print(f"\n{'='*56}")
        print(f"  Scan done -- {len(found)} HTF springs from {len(symbols)} symbols  [{elapsed:.0f}s]")
        print(f"{'='*56}\n")

        if not found:
            print("  No HTF spring found.\n")
            return

        found.sort(key=lambda a: a.score, reverse=True)

        print(f"\n{'='*68}")
        print(f"  SNIPER WATCHLIST -- {len(found)} HTF springs (ranked by score)")
        print(f"{'='*68}")
        print(f"  {'#':<4} {'symbol':<16} {'dir':<6} {'tf':<5} {'score':<12} {'level':<14} rank")
        print("  " + "-" * 62)
        for i, a in enumerate(found, 1):
            rl = _rank_label(a.score)
            print(f"  #{i:<3} {a.symbol:<16} {a.direction:<6} {a.tf:<5}"
                  f" {a.score:>5.1f}/100  {_fmt(a.level):<14} {rl}")

        print(f"\n{'='*68}")
        print(f"  Preview top {min(SHOW_TOP, len(found))}:")
        print(f"{'='*68}\n")
        for rank, a in enumerate(found[:SHOW_TOP], 1):
            print(_fmt_alert(rank, a))

        alert_candidates = [a for a in found if a.score >= MIN_SCORE] or found[:5]

        print(f"\n{'='*68}")
        print(f"  Registering {len(alert_candidates)} levels for monitoring:")
        print(f"{'='*68}")
        for a in alert_candidates:
            monitor.add(a)

        print(f"\n  Monitoring -- checking every {POLL_SEC}s")
        print(f"  Ctrl+C to exit\n")

        await monitor.run()


if __name__ == "__main__":
    asyncio.run(main())
