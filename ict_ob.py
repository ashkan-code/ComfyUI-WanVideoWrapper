#!/usr/bin/env python3
"""
ICT OB + RSI Confluence Scanner  --  standalone
  1. BTC ICT bias (4H + 1H + Daily)
  2. Strict OB detection: 4H + 1H + 15M + 5M
     - OB = last opposite-color candle within 5 bars before strong BOS
     - Displacement body >= 0.6 ATR  (strong impulse required)
     - Unmitigated only
  3. Multi-TF OB confluence (zone overlap across TFs)
  4. Distance filter: price within 2% of zone -- NOT inside yet
  5. RSI 15M confirmation: oversold (<35) for LONG, overbought (>65) for SHORT
  6. Score: TF confluence + RSI extremity + impulse strength

DISPLAY ONLY -- no orders placed.
Run:  python ict_ob.py
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

API_KEY    = os.getenv("BITUNIX_API_KEY",    "68f0a1765f124bacb847afa8db78e480")
SECRET_KEY = os.getenv("BITUNIX_SECRET_KEY", "159808597389a1cd1fc429f9f469209b")
BASE_URL   = "https://fapi.bitunix.com"
_SEMAPHORE: Optional[asyncio.Semaphore] = None

# ── Config ────────────────────────────────────────────────────────────────────
SCAN_TFS      = ["4h", "1h", "15m", "5m"]
TF_LIMITS     = {"4h": 150, "1h": 200, "15m": 200, "5m": 300}
TF_SCORE      = {"4h": 30,  "1h": 35,  "15m": 25,  "5m": 10}
TF_MAX_AGE    = {"4h": 50,  "1h": 80,  "15m": 96,  "5m": 144}
TF_SL_PRIO    = ["5m", "15m", "1h", "4h"]

MIN_TFS       = 2
MIN_RR        = 2.5
SL_BUFFER     = 0.003      # 0.3%
MAX_SL_PCT    = 0.025      # 2.5% max SL
BATCH_SIZE    = 20
SHOW_TOP      = 10
OB_TOL        = 0.003      # 0.3% zone overlap tolerance

# Distance: price must be OUTSIDE the zone, within this % of zone edge
MAX_DIST_PCT  = 2.0        # show if price is within 2% of zone
MIN_DIST_PCT  = 0.0        # 0% = allow "at zone edge" too

# RSI 15M thresholds
RSI_BULL_ENTER  = 35.0     # oversold  -> confirms bullish OB approach
RSI_BEAR_ENTER  = 65.0     # overbought -> confirms bearish OB approach
RSI_BULL_STRONG = 25.0     # extreme oversold  -> bonus
RSI_BEAR_STRONG = 75.0     # extreme overbought -> bonus


# =============================================================================
#  Bitunix client
# =============================================================================

def _get_semaphore() -> asyncio.Semaphore:
    global _SEMAPHORE
    if _SEMAPHORE is None:
        _SEMAPHORE = asyncio.Semaphore(8)
    return _SEMAPHORE


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


class AsyncBitunixClient:
    def __init__(self, api_key: str, secret_key: str,
                 session: Optional[aiohttp.ClientSession] = None):
        self.api_key = api_key
        self.secret_key = secret_key
        self._session = session

    async def _get(self, path: str, params: dict = None) -> dict:
        async with _get_semaphore():
            url = BASE_URL + path
            async with self._session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                return await r.json(content_type=None)

    async def get_all_tickers(self) -> List[dict]:
        return (await self._get("/api/v1/futures/market/tickers")).get("data") or []

    async def get_klines(self, symbol: str, interval: str, limit: int = 200) -> List[dict]:
        return (await self._get("/api/v1/futures/market/kline",
                {"symbol": symbol, "interval": interval, "limit": limit})).get("data") or []


# =============================================================================
#  Core helpers
# =============================================================================

def _parse_klines(raw: list) -> list:
    if not raw:
        return []
    result = []
    for k in raw:
        try:
            result.append({
                "open":  float(k["open"]), "high": float(k["high"]),
                "low":   float(k["low"]),  "close": float(k["close"]),
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
        h, l, pc = klines[i]["high"], klines[i]["low"], klines[i-1]["close"]
        trs[i] = max(h - l, abs(h - pc), abs(l - pc))
    atr = [None] * n
    for i in range(period, n):
        atr[i] = sum(trs[i - period + 1: i + 1]) / period
    return atr


def _swing_highs(klines: list, n: int = 3) -> List[int]:
    idxs = []
    for i in range(n, len(klines) - n):
        w = [klines[j]["high"] for j in range(i - n, i + n + 1)]
        if klines[i]["high"] == max(w):
            idxs.append(i)
    return idxs


def _swing_lows(klines: list, n: int = 3) -> List[int]:
    idxs = []
    for i in range(n, len(klines) - n):
        w = [klines[j]["low"] for j in range(i - n, i + n + 1)]
        if klines[i]["low"] == min(w):
            idxs.append(i)
    return idxs


def _rsi(klines: list, period: int = 14) -> float:
    """Wilder RSI for the last bar."""
    closes = [k["close"] for k in klines]
    if len(closes) < period + 2:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
    if al == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + ag / al))


def market_structure(raw: list, lookback: int = 50) -> str:
    klines = _parse_klines(raw)
    if len(klines) > lookback:
        klines = klines[-lookback:]
    if len(klines) < 10:
        return "neutral"
    sh = _swing_highs(klines, n=3)
    sl = _swing_lows(klines,  n=3)
    if len(sh) >= 2 and len(sl) >= 2:
        if (klines[sh[-1]]["high"] > klines[sh[-2]]["high"] and
                klines[sl[-1]]["low"] > klines[sl[-2]]["low"]):
            return "bullish"
        if (klines[sh[-1]]["high"] < klines[sh[-2]]["high"] and
                klines[sl[-1]]["low"] < klines[sl[-2]]["low"]):
            return "bearish"
    return "neutral"


def detect_fvg(raw: list, direction: str) -> List[Tuple[float, float]]:
    klines = _parse_klines(raw)
    fvgs: List[Tuple[float, float]] = []
    for i in range(2, len(klines)):
        a, c = klines[i - 2], klines[i]
        if direction == "bearish" and a["low"] > c["high"]:
            fvgs.append((float(c["high"]), float(a["low"])))
        elif direction == "bullish" and a["high"] < c["low"]:
            fvgs.append((float(a["high"]), float(c["low"])))
    return list(reversed(fvgs))


def detect_liquidity_sweep(raw: list, direction: str) -> Tuple[bool, str]:
    klines = _parse_klines(raw)
    if len(klines) < 15:
        return False, ""
    recent = klines[-30:]
    n = len(recent)
    if direction == "bullish":
        for si in reversed(_swing_lows(recent[:n-2], n=2)[-4:]):
            lvl = recent[si]["low"]
            for j in range(si + 1, n):
                if recent[j]["low"] < lvl and recent[j]["close"] > lvl:
                    return True, f"SSL {lvl:.6g}"
    else:
        for si in reversed(_swing_highs(recent[:n-2], n=2)[-4:]):
            lvl = recent[si]["high"]
            for j in range(si + 1, n):
                if recent[j]["high"] > lvl and recent[j]["close"] < lvl:
                    return True, f"BSL {lvl:.6g}"
    return False, ""


def btc_ict_bias(tf_klines: dict) -> Tuple[str, str]:
    scores  = {"bullish": 0, "bearish": 0}
    details = []
    raw4h = tf_klines.get("4h", [])
    if raw4h:
        ms = market_structure(raw4h, lookback=60)
        details.append(f"4H:{ms[0].upper()}")
        if ms == "bullish":   scores["bullish"] += 4
        elif ms == "bearish": scores["bearish"] += 4
        kl = _parse_klines(raw4h)
        if len(kl) >= 20:
            rec = kl[-60:] if len(kl) >= 60 else kl
            sh4 = _swing_highs(rec, n=3)
            sl4 = _swing_lows(rec,  n=3)
            lc  = kl[-1]["close"]
            if len(sh4) >= 2 and lc > rec[sh4[-2]]["high"]:
                scores["bullish"] += 3; details.append("4H:BOS+")
            if len(sl4) >= 2 and lc < rec[sl4[-2]]["low"]:
                scores["bearish"] += 3; details.append("4H:BOS-")
            if detect_fvg(raw4h, "bullish"): scores["bullish"] += 1
            if detect_fvg(raw4h, "bearish"): scores["bearish"] += 1
            lq_b, _ = detect_liquidity_sweep(raw4h, "bullish")
            lq_s, _ = detect_liquidity_sweep(raw4h, "bearish")
            if lq_b: scores["bullish"] += 1
            if lq_s: scores["bearish"] += 1
            rhi = max(k["high"] for k in rec)
            rlo = min(k["low"]  for k in rec)
            if lc < (rhi + rlo) / 2:
                scores["bullish"] += 1; details.append("DISC")
            else:
                scores["bearish"] += 1; details.append("PREM")
    raw1h = tf_klines.get("1h", [])
    if raw1h:
        ms = market_structure(raw1h, lookback=40)
        details.append(f"1H:{ms[0].upper()}")
        if ms == "bullish":   scores["bullish"] += 2
        elif ms == "bearish": scores["bearish"] += 2
        kl = _parse_klines(raw1h)
        if len(kl) >= 20:
            rec = kl[-40:] if len(kl) >= 40 else kl
            sh1 = _swing_highs(rec, n=2)
            sl1 = _swing_lows(rec,  n=2)
            lc  = kl[-1]["close"]
            if len(sh1) >= 2 and lc > rec[sh1[-2]]["high"]:
                scores["bullish"] += 1; details.append("1H:BOS+")
            if len(sl1) >= 2 and lc < rec[sl1[-2]]["low"]:
                scores["bearish"] += 1; details.append("1H:BOS-")
    raw1d = tf_klines.get("1d", [])
    if raw1d:
        ms = market_structure(raw1d, lookback=30)
        details.append(f"D:{ms[0].upper()}")
        if ms == "bullish":   scores["bullish"] += 2
        elif ms == "bearish": scores["bearish"] += 2
    total = scores["bullish"] + scores["bearish"]
    if total == 0:
        return "neutral", " | ".join(details)
    bp = scores["bullish"] / total * 100
    dp = scores["bearish"] / total * 100
    if bp >= 60: return "bullish", " | ".join(details) + f"  [{bp:.0f}%+]"
    if dp >= 60: return "bearish", " | ".join(details) + f"  [{dp:.0f}%-]"
    return "neutral",  " | ".join(details) + f"  [+{scores['bullish']} -{scores['bearish']}]"


# =============================================================================
#  Strict ICT OB detection  --  improved
# =============================================================================

def detect_obs_strict(raw: list, direction: str,
                      lookback: int = 200,
                      max_age: int = 999) -> List[dict]:
    """
    Strict ICT Order Block:
      - BOS candle: closes above/below prior swing high/low
      - Displacement: body of BOS candle >= 0.6 * ATR  (strong impulse)
      - OB candle: last opposite-color candle within 5 bars BEFORE the BOS
      - OB body >= 0.08 * ATR  (not a doji)
      - Unmitigated: no close through OB body after creation
      - Age <= max_age bars
    """
    klines = _parse_klines(raw)
    n = len(klines)
    if n < 30:
        return []
    recent = klines[-lookback:] if n > lookback else klines
    n = len(recent)
    atr = _atr_vals(recent)
    sh  = _swing_highs(recent, n=3)
    sl  = _swing_lows(recent,  n=3)
    seen: set = set()
    result: List[dict] = []

    if direction == "bullish":
        for i in range(6, n):
            a = atr[i]
            if a is None or a == 0:
                continue
            # 1. BOS: close above prior swing high
            prev_sh = [j for j in sh if j < i]
            if not prev_sh:
                continue
            sh_price = recent[prev_sh[-1]]["high"]
            if recent[i]["close"] <= sh_price:
                continue
            # 2. Displacement: body of BOS candle >= 0.6 ATR
            bos_body = abs(recent[i]["close"] - recent[i]["open"])
            if bos_body < a * 0.6:
                continue
            # 3. OB = last BEARISH candle within 5 bars before BOS
            ob_idx = next((k for k in range(i - 1, max(i - 6, -1), -1)
                           if recent[k]["close"] < recent[k]["open"]), None)
            if ob_idx is None or ob_idx in seen:
                continue
            age = n - 1 - ob_idx
            if age > max_age:
                continue
            ob_c    = recent[ob_idx]
            ob_high = max(ob_c["open"], ob_c["close"])
            ob_low  = min(ob_c["open"], ob_c["close"])
            # 4. OB body must be real (not doji)
            if ob_high - ob_low < a * 0.08:
                continue
            # 5. Mitigation: no close below OB body since creation
            if any(recent[j]["close"] < ob_low for j in range(ob_idx + 1, n)):
                continue
            seen.add(ob_idx)
            result.append({
                "direction": "bullish",
                "ob_high": ob_high, "ob_low": ob_low,
                "wick_high": ob_c["high"], "wick_low": ob_c["low"],
                "bar_idx": ob_idx, "bos_price": sh_price,
                "body": ob_high - ob_low, "atr": a, "age": age,
                "impulse": bos_body / a,   # impulse ratio (body / ATR)
            })

    else:  # bearish
        for i in range(6, n):
            a = atr[i]
            if a is None or a == 0:
                continue
            prev_sl = [j for j in sl if j < i]
            if not prev_sl:
                continue
            sl_price = recent[prev_sl[-1]]["low"]
            if recent[i]["close"] >= sl_price:
                continue
            bos_body = abs(recent[i]["close"] - recent[i]["open"])
            if bos_body < a * 0.6:
                continue
            ob_idx = next((k for k in range(i - 1, max(i - 6, -1), -1)
                           if recent[k]["close"] > recent[k]["open"]), None)
            if ob_idx is None or ob_idx in seen:
                continue
            age = n - 1 - ob_idx
            if age > max_age:
                continue
            ob_c    = recent[ob_idx]
            ob_high = max(ob_c["open"], ob_c["close"])
            ob_low  = min(ob_c["open"], ob_c["close"])
            if ob_high - ob_low < a * 0.08:
                continue
            if any(recent[j]["close"] > ob_high for j in range(ob_idx + 1, n)):
                continue
            seen.add(ob_idx)
            result.append({
                "direction": "bearish",
                "ob_high": ob_high, "ob_low": ob_low,
                "wick_high": ob_c["high"], "wick_low": ob_c["low"],
                "bar_idx": ob_idx, "bos_price": sl_price,
                "body": ob_high - ob_low, "atr": a, "age": age,
                "impulse": bos_body / a,
            })

    return sorted(result, key=lambda x: x["bar_idx"], reverse=True)[:5]


# =============================================================================
#  Multi-TF confluence
# =============================================================================

def find_ob_confluence(tf_obs: Dict[str, List[dict]],
                       current_price: float,
                       direction: str) -> List[dict]:
    """
    Groups overlapping OBs across TFs.
    Filters: price within MAX_DIST_PCT of zone edge but NOT inside zone.
    SL from tightest TF wick (5M > 15M > 1H > 4H).
    """
    all_obs: List[dict] = []
    for tf, obs_list in tf_obs.items():
        for ob in obs_list:
            if ob["direction"] == direction:
                all_obs.append({**ob, "tf": tf})
    if not all_obs:
        return []

    zones: List[dict] = []
    used  = set()

    for i, ob1 in enumerate(all_obs):
        if i in used:
            continue
        group = [ob1]
        used.add(i)
        for j, ob2 in enumerate(all_obs):
            if j in used:
                continue
            tol = current_price * OB_TOL
            if (ob1["ob_low"] - tol <= ob2["ob_high"] and
                    ob2["ob_low"] - tol <= ob1["ob_high"]):
                group.append(ob2)
                used.add(j)

        tf_set = set(g["tf"] for g in group)
        if len(tf_set) < MIN_TFS:
            continue

        # Confluence zone = tightest intersection
        z_high = min(g["ob_high"] for g in group)
        z_low  = max(g["ob_low"]  for g in group)
        if z_low >= z_high:
            anchor = min(group, key=lambda g: g["ob_high"] - g["ob_low"])
            z_high, z_low = anchor["ob_high"], anchor["ob_low"]

        # ── Distance filter: price outside zone, within MAX_DIST_PCT ─────────
        if direction == "bullish":
            # Price must be ABOVE zone (hasn't entered yet)
            if current_price <= z_high:
                continue   # already inside or below — skip
            dist_pct = (current_price - z_high) / current_price * 100
        else:
            # Price must be BELOW zone
            if current_price >= z_low:
                continue   # already inside or above — skip
            dist_pct = (z_low - current_price) / current_price * 100

        if dist_pct > MAX_DIST_PCT:
            continue  # too far

        # SL = tightest TF wick
        sl_raw = None
        sl_tf  = ""
        for tf_prio in TF_SL_PRIO:
            tg = [g for g in group if g["tf"] == tf_prio]
            if tg:
                if direction == "bullish":
                    sl_raw = min(g["wick_low"]  for g in tg) * (1 - SL_BUFFER)
                else:
                    sl_raw = max(g["wick_high"] for g in tg) * (1 + SL_BUFFER)
                sl_tf = tf_prio
                break
        if sl_raw is None:
            continue

        entry    = (z_high + z_low) / 2
        loss_pct = abs(entry - sl_raw) / entry * 100
        if loss_pct <= 0 or loss_pct > MAX_SL_PCT * 100:
            continue

        best_imp  = max(g["impulse"] for g in group)
        atr_avg   = sum(g["atr"] for g in group) / len(group)
        score_base = sum(TF_SCORE.get(g["tf"], 5) for g in group)
        tfs_sorted = sorted(tf_set, key=lambda t: TF_SCORE.get(t, 0), reverse=True)

        zones.append({
            "direction": direction,
            "zone_high": z_high, "zone_low": z_low,
            "entry":     entry,  "sl":       sl_raw,
            "sl_tf":     sl_tf,  "loss_pct": loss_pct,
            "dist_pct":  dist_pct,
            "score_base": score_base,
            "best_imp":   best_imp,
            "atr":        atr_avg,
            "tfs":        tfs_sorted,
            "tf_count":   len(tf_set),
            "group":      group,
        })

    return sorted(zones, key=lambda z: z["score_base"] + z["best_imp"] * 5, reverse=True)


# =============================================================================
#  TP finder (15M / 5M / 1H)
# =============================================================================

def _find_tp(klines_15m: list, klines_5m: list, klines_1h: list,
             entry: float, direction: str, sl: float) -> Tuple[float, str]:
    risk     = abs(entry - sl) or entry * 0.01
    min_dist = risk * MIN_RR

    for raw, lbl in ((klines_15m, "15m"), (klines_5m, "5m"), (klines_1h, "1h")):
        klines = _parse_klines(raw)
        if not klines:
            continue
        cands: List[Tuple[float, str]] = []

        if direction == "bullish":
            for idx in _swing_highs(klines, n=2):
                p = klines[idx]["high"]
                if p > entry + min_dist:
                    cands.append((p, f"SH {lbl}"))
            recent = [klines[i]["high"]
                      for i in range(max(0, len(klines)-80), len(klines))]
            seen: List[float] = []
            for p in recent:
                if any(abs(p-s)/s < 0.002 for s in seen) and p > entry + min_dist:
                    cands.append((p, f"EQH {lbl}"))
                seen.append(p)
            for flo, fhi in detect_fvg(raw, "bullish")[:4]:
                m = (flo + fhi) / 2
                if m > entry + min_dist:
                    cands.append((m, f"FVG {lbl}"))
            valid = [(p, r) for p, r in cands if p > entry + min_dist]
            if valid:
                return min(valid, key=lambda x: x[0])
        else:
            for idx in _swing_lows(klines, n=2):
                p = klines[idx]["low"]
                if p < entry - min_dist:
                    cands.append((p, f"SL {lbl}"))
            recent_l = [klines[i]["low"]
                        for i in range(max(0, len(klines)-80), len(klines))]
            seen_l: List[float] = []
            for p in recent_l:
                if any(abs(p-s)/s < 0.002 for s in seen_l) and p < entry - min_dist:
                    cands.append((p, f"EQL {lbl}"))
                seen_l.append(p)
            for flo, fhi in detect_fvg(raw, "bearish")[:4]:
                m = (flo + fhi) / 2
                if m < entry - min_dist:
                    cands.append((m, f"FVG {lbl}"))
            valid = [(p, r) for p, r in cands if p < entry - min_dist]
            if valid:
                return max(valid, key=lambda x: x[0])

    tp = entry + min_dist if direction == "bullish" else entry - min_dist
    return tp, f"{MIN_RR:.1f}:1 fallback"


# =============================================================================
#  Signal dataclass + scan
# =============================================================================

@dataclass
class OBSignal:
    symbol:    str
    direction: str
    zone_high: float
    zone_low:  float
    entry:     float
    sl:        float
    tp:        float
    rr:        float
    leverage:  int
    loss_pct:  float
    score:     float
    tfs:       List[str]
    tf_count:  int
    sl_tf:     str
    dist_pct:  float
    rsi_15m:   float
    tp_reason: str
    btc_bias:  str
    group:     List[dict] = field(default_factory=list)


async def _scan_one(client: AsyncBitunixClient,
                    symbol: str, price: float,
                    btc_bias: str, direction: str,
                    ict_dir: str) -> Optional[OBSignal]:

    kdata: Dict[str, list] = {}
    for tf in SCAN_TFS:
        kdata[tf] = await client.get_klines(symbol, tf, TF_LIMITS[tf])

    # RSI 15M -- must pass first (cheap filter)
    kl15 = _parse_klines(kdata.get("15m", []))
    if not kl15:
        return None
    rsi = _rsi(kl15[-50:] if len(kl15) >= 50 else kl15)

    rsi_ok = ((ict_dir == "bullish" and rsi <= RSI_BULL_ENTER) or
              (ict_dir == "bearish" and rsi >= RSI_BEAR_ENTER))
    if not rsi_ok:
        return None

    # Detect OBs per TF
    tf_obs: Dict[str, List[dict]] = {}
    for tf in SCAN_TFS:
        raw = kdata.get(tf, [])
        tf_obs[tf] = detect_obs_strict(raw, ict_dir,
                                        max_age=TF_MAX_AGE[tf]) if raw else []

    zones = find_ob_confluence(tf_obs, price, ict_dir)
    if not zones:
        return None

    best     = zones[0]
    entry    = best["entry"]
    sl       = best["sl"]
    loss_pct = best["loss_pct"]

    tp, tp_reason = _find_tp(
        kdata.get("15m", []), kdata.get("5m", []), kdata.get("1h", []),
        entry, ict_dir, sl,
    )

    rr = abs(tp - entry) / abs(sl - entry) if sl != entry else 0
    if rr < MIN_RR:
        return None

    leverage = max(1, min(10, math.floor(15 / loss_pct)))

    # Score: TF confluence (max 100) + impulse (max 15) + RR (max 10) + RSI (max 15)
    imp_pts = min(best["best_imp"] * 5, 15)
    rr_pts  = 10 if rr >= 5 else (8 if rr >= 4 else (5 if rr >= MIN_RR else 0))
    if ict_dir == "bullish":
        rsi_pts = 15 if rsi <= RSI_BULL_STRONG else (10 if rsi <= RSI_BULL_ENTER else 0)
    else:
        rsi_pts = 15 if rsi >= RSI_BEAR_STRONG else (10 if rsi >= RSI_BEAR_ENTER else 0)
    score = min(best["score_base"] + imp_pts + rr_pts + rsi_pts, 100.0)

    return OBSignal(
        symbol    = symbol, direction = direction,
        zone_high = best["zone_high"], zone_low = best["zone_low"],
        entry     = entry, sl = sl, tp = tp, rr = rr,
        leverage  = leverage, loss_pct = loss_pct, score = score,
        tfs       = best["tfs"], tf_count = best["tf_count"],
        sl_tf     = best["sl_tf"], dist_pct = best["dist_pct"],
        rsi_15m   = rsi, tp_reason = tp_reason, btc_bias = btc_bias,
        group     = best["group"],
    )


# =============================================================================
#  Display
# =============================================================================

def _fmt(p: float) -> str:
    if p >= 1000: return f"{p:,.2f}"
    if p >= 1:    return f"{p:.4f}"
    return f"{p:.6f}"


def _bar(s: float) -> str:
    f = round(s / 10)
    return "#" * f + "." * (10 - f)


def _rank_label(s: float) -> str:
    if s >= 82: return "ELITE"
    if s >= 68: return "SNIPER"
    if s >= 52: return "VALID"
    return "WEAK"


def _rsi_label(rsi: float, direction: str) -> str:
    if direction == "LONG":
        if rsi <= RSI_BULL_STRONG: return f"RSI {rsi:.1f}  [*** EXTREME OVERSOLD ***]"
        return f"RSI {rsi:.1f}  [oversold -- confirmed]"
    else:
        if rsi >= RSI_BEAR_STRONG: return f"RSI {rsi:.1f}  [*** EXTREME OVERBOUGHT ***]"
        return f"RSI {rsi:.1f}  [overbought -- confirmed]"


def _format_ob(rank: int, sig: OBSignal) -> str:
    icon    = "LONG " if sig.direction == "LONG" else "SHORT"
    tfs_str = " + ".join(t.upper() for t in sig.tfs)
    sl_sign = "-" if sig.direction == "LONG" else "+"
    tp_pct  = abs(sig.tp - sig.entry) / sig.entry * 100
    tp_sign = "+" if sig.direction == "LONG" else "-"
    rl      = _rank_label(sig.score)

    tf_lines = []
    seen_tfs: set = set()
    for ob in sorted(sig.group, key=lambda g: TF_SCORE.get(g.get("tf",""), 0), reverse=True):
        tf = ob.get("tf", "?")
        if tf in seen_tfs:
            continue
        seen_tfs.add(tf)
        tf_lines.append(
            f"    {tf.upper():<5}: [{_fmt(ob['ob_low'])} -- {_fmt(ob['ob_high'])}]"
            f"  age={ob['age']}bars  impulse={ob['impulse']:.1f}xATR"
        )

    return (
        f"\n+{'='*64}+\n"
        f"|  #{rank:<2}  {icon}  {sig.symbol:<16}  [{tfs_str}]     |\n"
        f"|  score: {sig.score:>5.1f}/100  {_bar(sig.score)}  {rl}             |\n"
        f"+{'='*64}+\n"
        f"  Price      : {_fmt(sig.entry)}  "
        f"({sig.dist_pct:.2f}% from zone edge -- approaching)\n"
        f"  OB Zone    : {_fmt(sig.zone_low)} -- {_fmt(sig.zone_high)}\n"
        f"  {_rsi_label(sig.rsi_15m, sig.direction)}\n"
        f"  {'─'*58}\n"
        f"  Entry      : {_fmt(sig.entry)}\n"
        f"  Stop Loss  : {_fmt(sig.sl)}  ({sl_sign}{sig.loss_pct:.2f}%)"
        f"  <- {sig.sl_tf.upper()} wick\n"
        f"  TP         : {_fmt(sig.tp)}  ({tp_sign}{tp_pct:.2f}%)"
        f"  <- {sig.tp_reason}\n"
        f"  RRR        : 1:{sig.rr:.1f}\n"
        f"  Leverage   : {sig.leverage}x\n"
        f"  BTC        : {sig.btc_bias.upper()}\n"
        f"  TF OB stack:\n"
        + "\n".join(tf_lines) +
        f"\n+{'='*64}+"
    )


# =============================================================================
#  Entry point
# =============================================================================

async def main():
    print("""
+========================================================+
|  ICT OB + RSI Confluence Scanner                      |
|  OB: 4H + 1H + 15M + 5M  --  strict BOS + displacement|
|  Filter: price within 2% of zone + RSI 15M at extreme |
|  DISPLAY ONLY -- no orders placed                     |
+========================================================+
""")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode    = ssl.CERT_NONE
    conn = aiohttp.TCPConnector(ssl=ssl_ctx)

    async with aiohttp.ClientSession(connector=conn) as session:
        client = AsyncBitunixClient(API_KEY, SECRET_KEY, session)

        print("  BTC bias ...", flush=True)
        btc_tf = {tf: await client.get_klines("BTCUSDT", tf, 100)
                  for tf in ("4h", "1h", "1d")}
        btc_bias, btc_detail = btc_ict_bias(btc_tf)
        b_tag = "BULL" if btc_bias == "bullish" else ("BEAR" if btc_bias == "bearish" else "NEUT")
        print(f"  BTC -> {b_tag}  |  {btc_detail}\n")

        if btc_bias == "neutral":
            dirs = [("LONG", "bullish"), ("SHORT", "bearish")]
            print("  BTC neutral -- scanning both directions\n")
        else:
            dirs = [("LONG" if btc_bias == "bullish" else "SHORT", btc_bias)]

        tickers   = await client.get_all_tickers()
        price_map = {t["symbol"]: float(t["lastPrice"])
                     for t in tickers
                     if t.get("lastPrice") and float(t.get("lastPrice", 0)) > 0}
        symbols   = list(price_map.keys())
        print(f"  {len(symbols)} symbols  |  TF: {' + '.join(SCAN_TFS)}\n"
              f"  Filters: OB confluence + RSI15 "
              f"({'< '+str(RSI_BULL_ENTER) if 'bullish' in [d[1] for d in dirs] else ''}"
              f"{'> '+str(RSI_BEAR_ENTER) if 'bearish' in [d[1] for d in dirs] else ''})"
              f" + price within {MAX_DIST_PCT}% of zone\n",
              flush=True)

        t0    = time.time()
        found: List[OBSignal] = []

        for direction, ict_dir in dirs:
            for i in range(0, len(symbols), BATCH_SIZE):
                batch   = symbols[i: i + BATCH_SIZE]
                tasks   = [_scan_one(client, sym, price_map[sym],
                                     btc_bias, direction, ict_dir)
                           for sym in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for r in results:
                    if isinstance(r, OBSignal):
                        found.append(r)
                done = i + len(batch)
                print(f"  {done}/{len(symbols)}  signals: {len(found)}"
                      f"  [{time.time()-t0:.0f}s]", flush=True)

        elapsed = time.time() - t0
        print(f"\n{'='*58}")
        print(f"  Done  --  {len(found)} OB+RSI confluence signals  [{elapsed:.0f}s]")
        print(f"{'='*58}\n")

        if not found:
            print("  No signals -- OB zones not near price or RSI not extreme.\n")
            return

        found.sort(key=lambda s: s.score, reverse=True)

        # Summary table
        print(f"\n{'='*74}")
        print(f"  ICT OB + RSI SIGNALS  ({len(found)} total)")
        print(f"{'='*74}")
        print(f"  {'#':<4} {'symbol':<16} {'dir':<6} {'TFs':<18} {'score':<10}"
              f" {'RSI15':<8} {'dist%':<8} {'RRR'}")
        print("  " + "-" * 72)
        for i, s in enumerate(found, 1):
            tfs_str  = "+".join(t.upper() for t in s.tfs)
            rsi_flag = "**" if ((s.direction == "LONG" and s.rsi_15m <= RSI_BULL_STRONG) or
                                (s.direction == "SHORT" and s.rsi_15m >= RSI_BEAR_STRONG)) else ""
            print(f"  #{i:<3} {s.symbol:<16} {s.direction:<6} {tfs_str:<18}"
                  f" {s.score:>5.1f}/100  {s.rsi_15m:>5.1f}{rsi_flag:<3}"
                  f" {s.dist_pct:.2f}%   1:{s.rr:.1f}")

        print(f"\n{'='*74}")
        print(f"  Full analysis top {min(SHOW_TOP, len(found))}:")
        print(f"{'='*74}")
        for rank, sig in enumerate(found[:SHOW_TOP], 1):
            print(_format_ob(rank, sig))

        print(f"\n  DISPLAY ONLY -- no orders placed.\n")


if __name__ == "__main__":
    asyncio.run(main())
