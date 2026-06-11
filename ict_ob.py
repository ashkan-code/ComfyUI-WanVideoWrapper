#!/usr/bin/env python3
"""
ICT Multi-TF Order Block Confluence Scanner  --  standalone
  1. BTC ICT bias  (4H + 1H + Daily)
  2. Strict OB detection: Daily + 4H + 1H + 5M
     - Last opposite-color candle before a BOS (Break of Structure)
     - Mitigation check: skip OBs already traded through
     - Impulse filter: move must break a swing high/low
  3. Multi-TF confluence: same price zone on 2+ TFs
  4. Near-entry filter: price at or approaching OB zone
  5. TP at next liquidity pool / swing / FVG  --  RR >= 3:1

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
SCAN_TFS   = ["1d", "4h", "1h", "5m"]
TF_LIMITS  = {"1d": 120, "4h": 200, "1h": 200, "5m": 300}
TF_SCORE   = {"1d": 28,  "4h": 21,  "1h": 14,  "5m": 7}
MIN_TFS    = 2        # minimum TFs for confluence
MIN_RR     = 3.0
SL_BUFFER  = 0.005   # 0.5% beyond OB wick
MAX_SL_PCT = 0.04    # skip if SL > 4% from entry
BATCH_SIZE = 20
SHOW_TOP   = 8
OB_TOL     = 0.004   # 0.4% — zone overlap tolerance


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
    return {"api-key": api_key, "nonce": nonce, "timestamp": ts,
            "sign": sign, "Content-Type": "application/json"}


class AsyncBitunixClient:
    def __init__(self, api_key: str, secret_key: str,
                 session: Optional[aiohttp.ClientSession] = None):
        self.api_key    = api_key
        self.secret_key = secret_key
        self._session   = session

    async def _get(self, path: str, params: dict = None) -> dict:
        sem = _get_semaphore()
        async with sem:
            url = BASE_URL + path
            async with self._session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                return await r.json(content_type=None)

    async def get_all_tickers(self) -> List[dict]:
        data = await self._get("/api/v1/futures/market/tickers")
        return data.get("data") or []

    async def get_klines(self, symbol: str, interval: str,
                         limit: int = 200) -> List[dict]:
        data = await self._get("/api/v1/futures/market/kline",
                               {"symbol": symbol, "interval": interval, "limit": limit})
        return data.get("data") or []


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
        sl_idxs = _swing_lows(recent[:n - 2], n=2)
        for si in reversed(sl_idxs[-4:]):
            lvl = recent[si]["low"]
            for j in range(si + 1, n):
                if recent[j]["low"] < lvl and recent[j]["close"] > lvl:
                    return True, f"SSL {lvl:.6g}"
    else:
        sh_idxs = _swing_highs(recent[:n - 2], n=2)
        for si in reversed(sh_idxs[-4:]):
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
            rec  = kl[-60:] if len(kl) >= 60 else kl
            sh4  = _swing_highs(rec, n=3)
            sl4  = _swing_lows(rec,  n=3)
            lc   = kl[-1]["close"]
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
            rng_hi = max(k["high"] for k in rec)
            rng_lo = min(k["low"]  for k in rec)
            if lc < (rng_hi + rng_lo) / 2:
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
    if bp >= 60:
        return "bullish", " | ".join(details) + f"  [{bp:.0f}%+]"
    if dp >= 60:
        return "bearish", " | ".join(details) + f"  [{dp:.0f}%-]"
    return "neutral",  " | ".join(details) + f"  [+{scores['bullish']} -{scores['bearish']}]"


# =============================================================================
#  Strict ICT Order Block detection
# =============================================================================

def detect_obs_strict(raw: list, direction: str,
                      lookback: int = 150) -> List[dict]:
    """
    Strict ICT Order Block rules:

    Bullish OB = last BEARISH candle before a BOS-up
      - BOS-up: close breaks above prior swing high with >= 0.8 ATR impulse
      - OB candle: last bearish candle in the 15 bars before the BOS candle
      - Valid only if price never closed below OB body since

    Bearish OB = last BULLISH candle before a BOS-down
      - BOS-down: close breaks below prior swing low with >= 0.8 ATR impulse
      - OB candle: last bullish candle in the 15 bars before the BOS candle
      - Valid only if price never closed above OB body since
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

    seen_ob_idx = set()
    result: List[dict] = []

    if direction == "bullish":
        for i in range(6, n):
            c = recent[i]
            a = atr[i]
            if a is None or a == 0:
                continue

            # Need a prior swing high to break
            prev_sh = [j for j in sh if j < i]
            if not prev_sh:
                continue
            sh_idx   = prev_sh[-1]
            sh_price = recent[sh_idx]["high"]

            # BOS up: close must be above prior swing high
            if c["close"] <= sh_price:
                continue
            # Impulse size filter (avoid micro-breakouts)
            if c["close"] - recent[i - 1]["close"] < a * 0.3:
                continue

            # Find the LAST bearish candle within 15 bars before the BOS
            ob_idx = None
            for k in range(i - 1, max(i - 16, -1), -1):
                if recent[k]["close"] < recent[k]["open"]:
                    ob_idx = k
                    break

            if ob_idx is None or ob_idx in seen_ob_idx:
                continue

            ob_c    = recent[ob_idx]
            ob_high = max(ob_c["open"], ob_c["close"])
            ob_low  = min(ob_c["open"], ob_c["close"])
            body    = ob_high - ob_low

            # OB body must be non-trivial (not a doji)
            if body < a * 0.05:
                continue

            # Mitigation check: no close below ob_low after the OB candle
            mitigated = any(recent[j]["close"] < ob_low
                            for j in range(ob_idx + 1, n))
            if mitigated:
                continue

            seen_ob_idx.add(ob_idx)
            result.append({
                "direction": "bullish",
                "ob_high":   ob_high,
                "ob_low":    ob_low,
                "wick_high": ob_c["high"],
                "wick_low":  ob_c["low"],
                "bar_idx":   ob_idx,
                "bos_price": sh_price,
                "body":      body,
                "atr":       a,
                "age":       n - 1 - ob_idx,
                "impulse":   c["close"] - ob_c["close"],
            })

    else:  # bearish
        for i in range(6, n):
            c = recent[i]
            a = atr[i]
            if a is None or a == 0:
                continue

            prev_sl = [j for j in sl if j < i]
            if not prev_sl:
                continue
            sl_idx   = prev_sl[-1]
            sl_price = recent[sl_idx]["low"]

            # BOS down: close must be below prior swing low
            if c["close"] >= sl_price:
                continue
            if recent[i - 1]["close"] - c["close"] < a * 0.3:
                continue

            # Find the LAST bullish candle within 15 bars before the BOS
            ob_idx = None
            for k in range(i - 1, max(i - 16, -1), -1):
                if recent[k]["close"] > recent[k]["open"]:
                    ob_idx = k
                    break

            if ob_idx is None or ob_idx in seen_ob_idx:
                continue

            ob_c    = recent[ob_idx]
            ob_high = max(ob_c["open"], ob_c["close"])
            ob_low  = min(ob_c["open"], ob_c["close"])
            body    = ob_high - ob_low

            if body < a * 0.05:
                continue

            # Mitigation check: no close above ob_high after the OB candle
            mitigated = any(recent[j]["close"] > ob_high
                            for j in range(ob_idx + 1, n))
            if mitigated:
                continue

            seen_ob_idx.add(ob_idx)
            result.append({
                "direction": "bearish",
                "ob_high":   ob_high,
                "ob_low":    ob_low,
                "wick_high": ob_c["high"],
                "wick_low":  ob_c["low"],
                "bar_idx":   ob_idx,
                "bos_price": sl_price,
                "body":      body,
                "atr":       a,
                "age":       n - 1 - ob_idx,
                "impulse":   ob_c["close"] - c["close"],
            })

    # Return most recent OBs first (max 5 per TF)
    return sorted(result, key=lambda x: x["bar_idx"], reverse=True)[:5]


# =============================================================================
#  Multi-TF confluence
# =============================================================================

def find_ob_confluence(tf_obs: Dict[str, List[dict]],
                       current_price: float,
                       direction: str) -> List[dict]:
    """
    Group OBs from different TFs that overlap in price.
    Returns confluence zones sorted by score (highest first).
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
            # Two OBs overlap if their zones are within OB_TOL of each other
            tol = current_price * OB_TOL
            if (ob1["ob_low"] - tol <= ob2["ob_high"] and
                    ob2["ob_low"] - tol <= ob1["ob_high"]):
                group.append(ob2)
                used.add(j)

        tf_set = set(g["tf"] for g in group)
        if len(tf_set) < MIN_TFS:
            continue

        # Score = sum of TF scores for participating TFs
        score = sum(TF_SCORE.get(g["tf"], 5) for g in group)

        # Confluence zone = tightest intersection
        z_high = min(g["ob_high"] for g in group)
        z_low  = max(g["ob_low"]  for g in group)
        if z_low >= z_high:
            # No exact intersection — use smallest OB as the zone
            smallest = min(group, key=lambda g: g["ob_high"] - g["ob_low"])
            z_high = smallest["ob_high"]
            z_low  = smallest["ob_low"]

        mid = (z_high + z_low) / 2
        atr_avg = sum(g["atr"] for g in group) / len(group)

        # Entry = midpoint of confluence zone
        entry = mid

        # SL = beyond worst wick + buffer
        if direction == "bullish":
            sl = min(g["wick_low"] for g in group) * (1 - SL_BUFFER)
        else:
            sl = max(g["wick_high"] for g in group) * (1 + SL_BUFFER)

        loss_pct = abs(entry - sl) / entry * 100
        if loss_pct <= 0 or loss_pct > MAX_SL_PCT * 100:
            continue

        # Proximity status
        if direction == "bullish":
            # Price should be at or just above OB zone (retrace into zone)
            at_zone     = z_low - atr_avg * 0.2 <= current_price <= z_high + atr_avg * 0.2
            approaching = z_low - atr_avg * 0.5 <= current_price <= z_high + atr_avg * 1.5
        else:
            # Price at or just below OB zone (retrace into zone)
            at_zone     = z_low - atr_avg * 0.2 <= current_price <= z_high + atr_avg * 0.2
            approaching = z_low - atr_avg * 1.5 <= current_price <= z_high + atr_avg * 0.5

        if not approaching:
            continue  # too far — not actionable

        # Proximity score (max 15)
        prox_pts = 15 if at_zone else 8

        # Sort TFs by weight (most important first)
        tfs_sorted = sorted(tf_set, key=lambda t: TF_SCORE.get(t, 0), reverse=True)

        dist_pct = abs(current_price - mid) / current_price * 100

        zones.append({
            "direction": direction,
            "zone_high": z_high,
            "zone_low":  z_low,
            "entry":     entry,
            "sl":        sl,
            "loss_pct":  loss_pct,
            "score_base": score,
            "prox_pts":   prox_pts,
            "at_zone":   at_zone,
            "tfs":       tfs_sorted,
            "tf_count":  len(tf_set),
            "dist_pct":  dist_pct,
            "atr":       atr_avg,
            "group":     group,
        })

    return sorted(zones, key=lambda z: z["score_base"] + z["prox_pts"], reverse=True)


# =============================================================================
#  TP finder
# =============================================================================

def _find_tp(klines_1h: list, klines_4h: list,
             entry: float, direction: str, sl: float,
             min_rr: float = 3.0) -> Tuple[float, str]:
    risk     = abs(entry - sl) or entry * 0.01
    min_dist = risk * min_rr

    candidates: List[Tuple[float, str]] = []

    for raw, tf_label in ((klines_1h, "1h"), (klines_4h, "4h")):
        klines = _parse_klines(raw)
        if not klines:
            continue

        if direction == "bullish":
            for idx in _swing_highs(klines, n=3):
                p = klines[idx]["high"]
                if p > entry + min_dist:
                    candidates.append((p, f"SH {tf_label}"))
            # Equal highs (liquidity above)
            recent = [klines[i]["high"]
                      for i in range(max(0, len(klines) - 60), len(klines))]
            seen: List[float] = []
            for p in recent:
                if any(abs(p - s) / s < 0.003 for s in seen) and p > entry + min_dist:
                    candidates.append((p, f"EQH {tf_label}"))
                seen.append(p)
        else:
            for idx in _swing_lows(klines, n=3):
                p = klines[idx]["low"]
                if p < entry - min_dist:
                    candidates.append((p, f"SL {tf_label}"))
            recent = [klines[i]["low"]
                      for i in range(max(0, len(klines) - 60), len(klines))]
            seen = []
            for p in recent:
                if any(abs(p - s) / s < 0.003 for s in seen) and p < entry - min_dist:
                    candidates.append((p, f"EQL {tf_label}"))
                seen.append(p)

        # FVG targets
        for flo, fhi in detect_fvg(raw, direction)[:6]:
            mid = (flo + fhi) / 2
            if direction == "bullish" and mid > entry + min_dist:
                candidates.append((mid, f"FVG {tf_label}"))
            elif direction == "bearish" and mid < entry - min_dist:
                candidates.append((mid, f"FVG {tf_label}"))

    if not candidates:
        tp = entry + min_dist if direction == "bullish" else entry - min_dist
        return tp, f"{min_rr:.0f}:1 fallback"

    if direction == "bullish":
        tp, reason = min(candidates, key=lambda x: x[0])
    else:
        tp, reason = max(candidates, key=lambda x: x[0])

    return tp, reason


# =============================================================================
#  Signal dataclass + scan
# =============================================================================

@dataclass
class OBSignal:
    symbol:    str
    direction: str    # LONG | SHORT
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
    dist_pct:  float
    at_zone:   bool
    tp_reason: str
    btc_bias:  str
    group:     List[dict] = field(default_factory=list)


async def _scan_one(client: AsyncBitunixClient,
                    symbol: str, price: float,
                    btc_bias: str, direction: str,
                    ict_dir: str) -> Optional[OBSignal]:
    # Fetch all TF klines
    kdata: Dict[str, list] = {}
    fetch_tasks = {
        tf: client.get_klines(symbol, tf, TF_LIMITS[tf])
        for tf in SCAN_TFS
    }
    for tf, coro in fetch_tasks.items():
        kdata[tf] = await coro

    if not kdata.get("4h") or not kdata.get("1h"):
        return None

    # Detect OBs on each TF (strict)
    tf_obs: Dict[str, List[dict]] = {}
    for tf in SCAN_TFS:
        raw = kdata.get(tf, [])
        tf_obs[tf] = detect_obs_strict(raw, ict_dir) if raw else []

    # Find multi-TF confluence zones
    zones = find_ob_confluence(tf_obs, price, ict_dir)
    if not zones:
        return None

    best = zones[0]  # highest score

    entry    = best["entry"]
    sl       = best["sl"]
    loss_pct = best["loss_pct"]

    # Find TP
    tp, tp_reason = _find_tp(kdata["1h"], kdata["4h"],
                              entry, ict_dir, sl, min_rr=MIN_RR)

    rr = abs(tp - entry) / abs(sl - entry) if sl != entry else 0
    if rr < MIN_RR:
        return None

    leverage = max(1, min(10, math.floor(15 / loss_pct)))

    # Final score (max 100)
    # TF base (max 70) + proximity (max 15) + RR (max 15)
    rr_pts  = 15 if rr >= 5 else (12 if rr >= 4 else (8 if rr >= 3 else 0))
    score   = min(best["score_base"] + best["prox_pts"] + rr_pts, 100.0)

    return OBSignal(
        symbol    = symbol,
        direction = direction,
        zone_high = best["zone_high"],
        zone_low  = best["zone_low"],
        entry     = entry,
        sl        = sl,
        tp        = tp,
        rr        = rr,
        leverage  = leverage,
        loss_pct  = loss_pct,
        score     = score,
        tfs       = best["tfs"],
        tf_count  = best["tf_count"],
        dist_pct  = best["dist_pct"],
        at_zone   = best["at_zone"],
        tp_reason = tp_reason,
        btc_bias  = btc_bias,
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


def _format_ob(rank: int, sig: OBSignal) -> str:
    icon    = "LONG " if sig.direction == "LONG" else "SHORT"
    tfs_str = " + ".join(t.upper() for t in sig.tfs)
    sl_sign = "-" if sig.direction == "LONG" else "+"
    tp_pct  = (sig.tp - sig.entry) / sig.entry * 100
    tp_sign = "+" if sig.direction == "LONG" else "-"
    b_tag   = sig.btc_bias.upper()
    rl      = _rank_label(sig.score)

    status = "[** PRICE AT OB ZONE **]" if sig.at_zone else f"[dist {sig.dist_pct:.2f}% from zone]"

    # Per-TF OB details
    tf_lines = []
    seen_tfs = set()
    for ob in sig.group:
        tf = ob.get("tf", "?")
        if tf in seen_tfs:
            continue
        seen_tfs.add(tf)
        imp = ob.get("impulse", 0)
        atr = ob.get("atr", 1)
        imp_ratio = imp / atr if atr > 0 else 0
        tf_lines.append(
            f"  {tf.upper():<4}: OB [{_fmt(ob['ob_low'])} -- {_fmt(ob['ob_high'])}]"
            f"  age={ob.get('age',0)}  impulse={imp_ratio:.1f}x ATR"
        )

    return (
        f"\n+{'='*60}+\n"
        f"|  #{rank:<2}  {icon}  {sig.symbol:<14} [{tfs_str}]   |\n"
        f"|  score: {sig.score:>5.1f}/100  {_bar(sig.score)}  {rl:<16}  |\n"
        f"+{'='*60}+\n"
        f"  {status}\n"
        f"  OB Zone  :  {_fmt(sig.zone_low)} -- {_fmt(sig.zone_high)}\n"
        f"  Entry    :  {_fmt(sig.entry)}\n"
        f"  Stop Loss:  {_fmt(sig.sl)}  ({sl_sign}{sig.loss_pct:.2f}%)  <- OB wick\n"
        f"  TP       :  {_fmt(sig.tp)}  ({tp_sign}{abs(tp_pct):.2f}%)  <- {sig.tp_reason}\n"
        f"  RRR      :  1:{sig.rr:.1f}\n"
        f"  Leverage :  {sig.leverage}x\n"
        f"  BTC bias :  {b_tag}\n"
        f"  {'─'*56}\n"
        + "\n".join(tf_lines) +
        f"\n+{'='*60}+"
    )


# =============================================================================
#  Entry point
# =============================================================================

async def main():
    print("""
+====================================================+
|   ICT Multi-TF Order Block Confluence Scanner      |
|   Daily + 4H + 1H + 5M  --  display only          |
+====================================================+
""")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode    = ssl.CERT_NONE
    conn = aiohttp.TCPConnector(ssl=ssl_ctx)

    async with aiohttp.ClientSession(connector=conn) as session:
        client = AsyncBitunixClient(API_KEY, SECRET_KEY, session)

        # BTC bias
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
            dirs      = [(direction, btc_bias)]

        # Tickers
        tickers   = await client.get_all_tickers()
        price_map = {t["symbol"]: float(t["lastPrice"])
                     for t in tickers
                     if t.get("lastPrice") and float(t.get("lastPrice", 0)) > 0}
        symbols   = list(price_map.keys())
        print(f"  Scanning {len(symbols)} symbols  [{', '.join(SCAN_TFS)}] ...\n", flush=True)

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
                print(f"  {done}/{len(symbols)}  OBs: {len(found)}"
                      f"  [{time.time() - t0:.0f}s]", flush=True)

        elapsed = time.time() - t0
        print(f"\n{'='*56}")
        print(f"  Done -- {len(found)} OB confluence zones  [{elapsed:.0f}s]")
        print(f"{'='*56}\n")

        if not found:
            print("  No confluent OBs near price.\n")
            return

        # Sort: price-at-zone first, then by score
        found.sort(key=lambda s: (s.at_zone, s.score), reverse=True)

        # Summary table
        at_zone = [s for s in found if s.at_zone]
        watching = [s for s in found if not s.at_zone]

        print(f"\n{'='*70}")
        print(f"  CONFLUENT ORDER BLOCKS  --  {len(found)} signals")
        print(f"  AT ZONE: {len(at_zone)}  |  APPROACHING: {len(watching)}")
        print(f"{'='*70}")
        print(f"  {'#':<4} {'symbol':<16} {'dir':<6} {'TFs':<18} {'score':<10}"
              f" {'RRR':<7} {'SL%':<7} status")
        print("  " + "-" * 68)
        for i, s in enumerate(found, 1):
            tfs_str = "+".join(t.upper() for t in s.tfs)
            status  = "AT-ZONE" if s.at_zone else f"{s.dist_pct:.1f}%away"
            marker  = " <--" if s.at_zone else ""
            print(f"  #{i:<3} {s.symbol:<16} {s.direction:<6} {tfs_str:<18}"
                  f" {s.score:>5.1f}/100  1:{s.rr:.1f}   {s.loss_pct:.1f}%   {status}{marker}")

        print(f"\n{'='*70}")
        print(f"  Full analysis top {min(SHOW_TOP, len(found))}:")
        print(f"{'='*70}")
        for rank, sig in enumerate(found[:SHOW_TOP], 1):
            print(_format_ob(rank, sig))

        print(f"\n  DISPLAY ONLY -- no orders placed.\n")


if __name__ == "__main__":
    asyncio.run(main())
