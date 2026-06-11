#!/usr/bin/env python3
"""
EMA Pullback Scalp Scanner v2  --  standalone
4H trend  +  1H EMA21 zone  +  15M approaching alert  +  5M confirm

  APPROACHING : price 1-4 candles (15-60 min) from 1H EMA21
                → set limit order at EMA21, wait for fill
  CONFIRMED   : price at 1H EMA21 + 5M candle confirm
                → enter now

  4H: EMA9 > EMA21 > EMA50  (strong trend filter)
  1H: EMA21 = key pullback zone
  15M: detects approach timing + RSI direction
  5M: entry candle pattern + volume  (only when at zone)

DISPLAY ONLY -- no orders placed.
Run:  python ema_scalp.py
"""

import asyncio
import math
import os
import ssl
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import aiohttp

API_KEY    = os.getenv("BITUNIX_API_KEY",    "68f0a1765f124bacb847afa8db78e480")
SECRET_KEY = os.getenv("BITUNIX_SECRET_KEY", "159808597389a1cd1fc429f9f469209b")
BASE_URL   = "https://fapi.bitunix.com"
_SEM: Optional[asyncio.Semaphore] = None

# ── Config ─────────────────────────────────────────────────────────────────────
EMA_FAST     = 9
EMA_MID      = 21
EMA_SLOW     = 50

ZONE_TOL     = 0.005    # 0.5%  → "at zone" when price within 0.5% of 1H EMA21
APPROACH_MAX = 4        # max 4 × 15M candles = 60 min warning window
VOL_MA       = 20
VOL_MULT     = 1.3      # current vol must be >= 1.3x average (5M confirm only)
MIN_RR       = 1.5
MAX_SL_PCT   = 0.020    # 2% max SL (1H zone is wider than 5M wick)
SL_BUFFER    = 0.002    # 0.2% beyond wick
BATCH_SIZE   = 20
SHOW_TOP     = 10

APPROACHING = "APPROACHING"
CONFIRMED   = "CONFIRMED"


# ── Client ─────────────────────────────────────────────────────────────────────

def _sem() -> asyncio.Semaphore:
    global _SEM
    if _SEM is None:
        _SEM = asyncio.Semaphore(8)
    return _SEM


class BitunixClient:
    def __init__(self, key: str, secret: str, sess: aiohttp.ClientSession):
        self.key = key; self.secret = secret; self.sess = sess

    async def _get(self, path: str, params: dict = None) -> dict:
        async with _sem():
            async with self.sess.get(
                BASE_URL + path, params=params,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                return await r.json(content_type=None)

    async def tickers(self) -> List[dict]:
        return (await self._get("/api/v1/futures/market/tickers")).get("data") or []

    async def klines(self, sym: str, iv: str, n: int = 100) -> List[dict]:
        return (await self._get("/api/v1/futures/market/kline",
                {"symbol": sym, "interval": iv, "limit": n})).get("data") or []


# ── Core math ──────────────────────────────────────────────────────────────────

def _fmt(p: float) -> str:
    if p >= 1000: return f"{p:,.2f}"
    if p >= 1:    return f"{p:.4f}"
    return f"{p:.6f}"


def _bar(s: float) -> str:
    n = round(s / 10)
    return "#" * n + "." * (10 - n)


def _parse(raw: list) -> list:
    out = []
    for k in raw:
        try:
            out.append({
                "open":  float(k["open"]),
                "high":  float(k["high"]),
                "low":   float(k["low"]),
                "close": float(k["close"]),
                "vol":   float(k.get("vol", k.get("volume", k.get("baseVol", 0)))),
                "time":  float(k.get("time", 0)),
            })
        except Exception:
            continue
    out.sort(key=lambda x: x["time"])
    return out


def _ema_vals(closes: List[float], period: int) -> List[Optional[float]]:
    res: List[Optional[float]] = [None] * len(closes)
    if len(closes) < period:
        return res
    res[period - 1] = sum(closes[:period]) / period
    k = 2.0 / (period + 1)
    for i in range(period, len(closes)):
        res[i] = closes[i] * k + res[i - 1] * (1 - k)
    return res


def _last(s: List[Optional[float]]) -> Optional[float]:
    return next((v for v in reversed(s) if v is not None), None)


def _prev_last(s: List[Optional[float]]) -> Tuple[Optional[float], Optional[float]]:
    v = [x for x in s if x is not None]
    if len(v) < 2: return None, (v[-1] if v else None)
    return v[-2], v[-1]


def _atr14(klines: list) -> Optional[float]:
    if len(klines) < 15: return None
    trs = [max(klines[i]["high"] - klines[i]["low"],
               abs(klines[i]["high"] - klines[i-1]["close"]),
               abs(klines[i]["low"]  - klines[i-1]["close"]))
           for i in range(1, len(klines))]
    return sum(trs[-14:]) / 14 if len(trs) >= 14 else None


def _rsi_last(klines: list) -> float:
    closes = [k["close"] for k in klines]
    if len(closes) < 16: return 50.0
    gs, ls = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gs.append(max(d, 0.0)); ls.append(max(-d, 0.0))
    ag = sum(gs[:14]) / 14; al = sum(ls[:14]) / 14
    for i in range(14, len(gs)):
        ag = (ag * 13 + gs[i]) / 14
        al = (al * 13 + ls[i]) / 14
    return 100.0 - 100.0 / (1.0 + ag / al) if al > 0 else 100.0


def _rsi_last2(klines: list) -> Tuple[float, float]:
    closes = [k["close"] for k in klines]
    if len(closes) < 17: return 50.0, 50.0
    gs, ls = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gs.append(max(d, 0.0)); ls.append(max(-d, 0.0))
    ag = sum(gs[:14]) / 14; al = sum(ls[:14]) / 14
    vals: List[float] = []
    cut = len(gs) - 2
    for i in range(14, len(gs)):
        ag = (ag * 13 + gs[i]) / 14
        al = (al * 13 + ls[i]) / 14
        if i >= cut:
            vals.append(100.0 - 100.0 / (1.0 + ag / al) if al > 0 else 100.0)
    if len(vals) < 2:
        return 50.0, (vals[-1] if vals else 50.0)
    return vals[-2], vals[-1]


def _vol_ratio(klines: list) -> float:
    vols = [k["vol"] for k in klines]
    if len(vols) < VOL_MA + 1: return VOL_MULT
    ma = sum(vols[-(VOL_MA + 1):-1]) / VOL_MA
    if ma <= 0: return VOL_MULT
    return vols[-1] / ma


def _swing_highs(kl: list, n: int = 3) -> List[int]:
    return [i for i in range(n, len(kl) - n)
            if kl[i]["high"] == max(kl[j]["high"] for j in range(i - n, i + n + 1))]


def _swing_lows(kl: list, n: int = 3) -> List[int]:
    return [i for i in range(n, len(kl) - n)
            if kl[i]["low"] == min(kl[j]["low"] for j in range(i - n, i + n + 1))]


# ── Candle patterns ────────────────────────────────────────────────────────────

def _is_hammer(k: dict) -> bool:
    o, h, l, c = k["open"], k["high"], k["low"], k["close"]
    rng = h - l
    if rng == 0: return False
    body = abs(c - o)
    if body == 0: return False
    return (min(o, c) - l >= 2.0 * body and
            h - max(o, c) <= body * 1.5 and
            (c - l) / rng >= 0.5)


def _is_shoot_star(k: dict) -> bool:
    o, h, l, c = k["open"], k["high"], k["low"], k["close"]
    rng = h - l
    if rng == 0: return False
    body = abs(c - o)
    if body == 0: return False
    return (h - max(o, c) >= 2.0 * body and
            min(o, c) - l <= body * 1.5 and
            (h - c) / rng >= 0.5)


def _is_bull_engulf(kp: dict, kc: dict) -> bool:
    return (kp["close"] < kp["open"] and kc["close"] > kc["open"] and
            kc["open"] <= kp["close"] and kc["close"] >= kp["open"])


def _is_bear_engulf(kp: dict, kc: dict) -> bool:
    return (kp["close"] > kp["open"] and kc["close"] < kc["open"] and
            kc["open"] >= kp["close"] and kc["close"] <= kp["open"])


# ── BTC ICT bias ───────────────────────────────────────────────────────────────

def _ms(kl: list, lb: int = 50) -> str:
    k = kl[-lb:] if len(kl) > lb else kl
    sh = _swing_highs(k, 3); sl = _swing_lows(k, 3)
    if len(sh) >= 2 and len(sl) >= 2:
        if k[sh[-1]]["high"] > k[sh[-2]]["high"] and k[sl[-1]]["low"] > k[sl[-2]]["low"]:
            return "bullish"
        if k[sh[-1]]["high"] < k[sh[-2]]["high"] and k[sl[-1]]["low"] < k[sl[-2]]["low"]:
            return "bearish"
    return "neutral"


def btc_ict_bias(tf_raw: dict) -> Tuple[str, str]:
    sc = {"bullish": 0, "bearish": 0, "neutral": 0}
    det: List[str] = []
    for tf, w in [("4h", 4), ("1h", 2), ("1d", 2)]:
        raw = tf_raw.get(tf)
        if not raw: continue
        kl = _parse(raw)
        ms = _ms(kl)
        det.append(f"{tf.upper()}:{ms[0].upper()}")
        sc[ms] = sc.get(ms, 0) + w
        sh = _swing_highs(kl, 3); sl2 = _swing_lows(kl, 3)
        lc = kl[-1]["close"] if kl else 0
        if len(sh) >= 2 and lc > kl[sh[-2]]["high"]:
            sc["bullish"] += 2; det.append(f"{tf.upper()}:BOS+")
        if len(sl2) >= 2 and lc < kl[sl2[-2]]["low"]:
            sc["bearish"] += 2; det.append(f"{tf.upper()}:BOS-")
    tot = sc["bullish"] + sc["bearish"]
    if tot == 0: return "neutral", " | ".join(det)
    bp = sc["bullish"] / tot * 100; dp = sc["bearish"] / tot * 100
    if bp >= 60: return "bullish", " | ".join(det) + f" [{bp:.0f}%+]"
    if dp >= 60: return "bearish", " | ".join(det) + f" [{dp:.0f}%-]"
    return "neutral", " | ".join(det)


# ── Step 1: 4H trend ───────────────────────────────────────────────────────────

def _check_4h(raw: list, direction: str
              ) -> Tuple[bool, float, float, float, str]:
    """EMA9 > EMA21 > EMA50 on 4H + slope in direction."""
    kl = _parse(raw)
    if len(kl) < EMA_SLOW + 5:
        return False, 0.0, 0.0, 0.0, "insufficient 4H data"
    closes = [k["close"] for k in kl]
    e9p, e9  = _prev_last(_ema_vals(closes, EMA_FAST))
    _,   e21 = _prev_last(_ema_vals(closes, EMA_MID))
    _,   e50 = _prev_last(_ema_vals(closes, EMA_SLOW))
    if None in (e9, e9p, e21, e50):
        return False, 0.0, 0.0, 0.0, "EMA calc failed"
    if direction == "bullish":
        ok = e9 > e21 > e50 and e9 > e9p
    else:
        ok = e9 < e21 < e50 and e9 < e9p
    tag = "[OK]" if ok else "[NO]"
    return ok, e9, e21, e50, f"4H EMA9={_fmt(e9)}/EMA21={_fmt(e21)}/EMA50={_fmt(e50)} {tag}"


# ── Step 2: 1H EMA21 zone ─────────────────────────────────────────────────────

def _get_1h_zone(raw: list, direction: str
                 ) -> Tuple[bool, float, str]:
    """Get 1H EMA21 as key pullback zone. EMA9 must still be aligned."""
    kl = _parse(raw)
    if len(kl) < EMA_MID + 5:
        return False, 0.0, "insufficient 1H data"
    closes = [k["close"] for k in kl]
    e9  = _last(_ema_vals(closes, EMA_FAST))
    e21 = _last(_ema_vals(closes, EMA_MID))
    if e9 is None or e21 is None:
        return False, 0.0, "EMA21 1H calc failed"
    # EMA9 must still respect direction on 1H
    if direction == "bullish" and e9 < e21 * 0.997:
        return False, e21, f"1H EMA9({_fmt(e9)}) < EMA21 -- 1H broken"
    if direction == "bearish" and e9 > e21 * 1.003:
        return False, e21, f"1H EMA9({_fmt(e9)}) > EMA21 -- 1H broken"
    return True, e21, f"1H EMA21={_fmt(e21)}  EMA9={_fmt(e9)}"


# ── Step 3: 15M approach / at-zone detection ──────────────────────────────────

def _check_15m(raw: list, direction: str, ema21_1h: float
               ) -> Tuple[Optional[str], int, int, float, str]:
    """
    Detects whether price is approaching or at 1H EMA21.
    Returns (status, candles_away, time_min, rsi, detail)
      status = APPROACHING | CONFIRMED | None
    """
    kl = _parse(raw)
    if len(kl) < 20 or ema21_1h <= 0:
        return None, 0, 0, 50.0, "insufficient 15M data"

    cur     = kl[-1]["close"]
    atr     = _atr14(kl)
    if atr is None or atr == 0:
        return None, 0, 0, 50.0, "ATR failed"

    dist    = abs(cur - ema21_1h)
    dist_pct = dist / ema21_1h

    # Already at zone?
    if dist_pct <= ZONE_TOL:
        rsi = _rsi_last(kl[-50:] if len(kl) >= 50 else kl)
        return CONFIRMED, 0, 0, rsi, (
            f"AT ZONE  EMA21={_fmt(ema21_1h)}  dist={dist_pct*100:.2f}%  RSI={rsi:.1f}")

    # Price must be heading toward zone
    recent = [k["close"] for k in kl[-4:]]
    if len(recent) < 3:
        return None, 0, 0, 50.0, "not enough candles"
    slope = recent[-1] - recent[-3]   # 2-candle momentum

    if direction == "bullish":
        heading = cur > ema21_1h and slope < 0   # above EMA21, falling toward it
    else:
        heading = cur < ema21_1h and slope > 0   # below EMA21, rising toward it

    if not heading:
        return None, 0, 0, 50.0, "price not heading toward EMA21"

    candles  = max(1, round(dist / atr))
    time_min = candles * 15

    if candles > APPROACH_MAX:
        return None, candles, time_min, 50.0, f"too far: {candles}c away ({time_min}min)"

    rsi = _rsi_last(kl[-50:] if len(kl) >= 50 else kl)

    # RSI must be moving in right direction (not already at extreme)
    if direction == "bullish" and rsi > 72:
        return None, candles, time_min, rsi, f"RSI={rsi:.1f} too high for LONG approach"
    if direction == "bearish" and rsi < 28:
        return None, candles, time_min, rsi, f"RSI={rsi:.1f} too low for SHORT approach"

    motion = "falling" if direction == "bullish" else "rising"
    return APPROACHING, candles, time_min, rsi, (
        f"~{candles}c ({time_min}min) to EMA21={_fmt(ema21_1h)}  "
        f"RSI={rsi:.1f} {motion}")


# ── Step 4: 5M confirmation (only when CONFIRMED) ─────────────────────────────

def _check_5m(raw: list, direction: str, ema21_1h: float
              ) -> Tuple[bool, float, float, float, str, str]:
    """Bull/bear candle at 1H EMA21 with volume. Returns (ok,entry,sl,vr,pat,det)."""
    kl = _parse(raw)
    if len(kl) < 30:
        return False, 0.0, 0.0, 1.0, "", "insufficient 5M data"
    kc, kp = kl[-1], kl[-2]
    vr = _vol_ratio(kl)
    if vr < VOL_MULT:
        return False, 0.0, 0.0, vr, "", f"vol {vr:.1f}x < {VOL_MULT}x"
    rsi_p, rsi_c = _rsi_last2(kl)

    if direction == "bullish":
        if rsi_c < rsi_p - 6:
            return False, 0.0, 0.0, vr, "", f"RSI5m falling ({rsi_p:.0f}->{rsi_c:.0f})"
        if kc["low"] > ema21_1h * 1.015:
            return False, 0.0, 0.0, vr, "", f"5M not at EMA21 zone ({_fmt(ema21_1h)})"
        if   _is_bull_engulf(kp, kc):   pat = "Bull Engulfing"
        elif _is_hammer(kc):            pat = "Hammer"
        elif kc["close"] > kc["open"]:  pat = "Bull Candle"
        else: return False, 0.0, 0.0, vr, "", "no bull pattern"
        entry = kc["close"]
        sl    = kc["low"] * (1 - SL_BUFFER)
    else:
        if rsi_c > rsi_p + 6:
            return False, 0.0, 0.0, vr, "", f"RSI5m rising ({rsi_p:.0f}->{rsi_c:.0f})"
        if kc["high"] < ema21_1h * 0.985:
            return False, 0.0, 0.0, vr, "", f"5M not at EMA21 zone ({_fmt(ema21_1h)})"
        if   _is_bear_engulf(kp, kc):    pat = "Bear Engulfing"
        elif _is_shoot_star(kc):         pat = "Shooting Star"
        elif kc["close"] < kc["open"]:   pat = "Bear Candle"
        else: return False, 0.0, 0.0, vr, "", "no bear pattern"
        entry = kc["close"]
        sl    = kc["high"] * (1 + SL_BUFFER)

    return True, entry, sl, vr, pat, f"5M {pat}  RSI={rsi_c:.1f}  vol={vr:.1f}x"


# ── TP on 1H swings ────────────────────────────────────────────────────────────

def _find_tp(raw_1h: list, entry: float, sl: float,
             direction: str) -> Tuple[float, str]:
    kl   = _parse(raw_1h)
    risk = abs(entry - sl) or entry * 0.01
    md   = risk * MIN_RR

    if direction == "bullish":
        cands: List[Tuple[float, str]] = []
        for i in _swing_highs(kl, 2):
            if kl[i]["high"] > entry + md:
                cands.append((kl[i]["high"], "SH 1H"))
        highs = [k["high"] for k in kl[-60:]]; seen: List[float] = []
        for p in highs:
            if any(abs(p - s) / s < 0.003 for s in seen) and p > entry + md:
                cands.append((p, "EQH 1H"))
            seen.append(p)
        if cands: return min(cands, key=lambda x: x[0])
    else:
        cands = []
        for i in _swing_lows(kl, 2):
            if kl[i]["low"] < entry - md:
                cands.append((kl[i]["low"], "SL 1H"))
        lows = [k["low"] for k in kl[-60:]]; seen_l: List[float] = []
        for p in lows:
            if any(abs(p - s) / s < 0.003 for s in seen_l) and p < entry - md:
                cands.append((p, "EQL 1H"))
            seen_l.append(p)
        if cands: return max(cands, key=lambda x: x[0])

    tp = entry + md if direction == "bullish" else entry - md
    return tp, f"{MIN_RR}:1 fallback"


# ── Signal dataclass ───────────────────────────────────────────────────────────

@dataclass
class EMASignal:
    symbol:    str
    direction: str
    status:    str       # APPROACHING | CONFIRMED
    entry:     float     # APPROACHING: EMA21 limit level | CONFIRMED: 5M close
    sl:        float
    tp:        float
    rr:        float
    leverage:  int
    loss_pct:  float
    score:     float
    e9_4h:     float
    e21_4h:    float
    e50_4h:    float
    ema21_1h:  float
    candles:   int       # 0 = confirmed
    time_min:  int
    rsi_15m:   float
    vol_ratio: float
    pattern:   str
    det_4h:    str
    det_1h:    str
    det_15m:   str
    det_5m:    str
    tp_rsn:    str
    btc:       str


def _score(sig: EMASignal) -> float:
    s = 0.0
    # 4H trend gap strength (30 pts)
    gap = abs(sig.e9_4h - sig.e50_4h) / sig.e50_4h * 100 if sig.e50_4h else 0
    s += min(18.0 + gap, 30.0)
    # Approach timing / at-zone (20 pts)
    if sig.status == CONFIRMED:      s += 20.0
    elif sig.candles <= 2:           s += 15.0
    else:                            s += 8.0
    # RSI quality (20 pts): ideal ~45 LONG / ~55 SHORT
    ideal = 45.0 if sig.direction == "LONG" else 55.0
    s += max(0.0, 20.0 - abs(sig.rsi_15m - ideal) * 0.7)
    # Volume (15 pts — only meaningful for CONFIRMED)
    if sig.status == CONFIRMED:
        s += min(sig.vol_ratio / 3.0, 1.0) * 15.0
    else:
        s += 7.0
    # Pattern (15 pts — only for CONFIRMED)
    if sig.status == CONFIRMED:
        if "Engulfing" in sig.pattern:  s += 15.0
        elif "Hammer" in sig.pattern or "Star" in sig.pattern: s += 12.0
        else:                            s += 7.0
    else:
        s += 7.0
    return min(s, 100.0)


# ── Main scan coroutine ────────────────────────────────────────────────────────

async def _scan_one(client: BitunixClient, sym: str, price: float,
                    bias: str, direction: str, ict_dir: str
                    ) -> Optional[EMASignal]:

    # Always need 4H, 1H, 15M
    r4h, r1h, r15m = await asyncio.gather(
        client.klines(sym, "4h", 120),
        client.klines(sym, "1h", 100),
        client.klines(sym, "15m", 80),
    )

    ok4, e9_4, e21_4, e50_4, det_4h = _check_4h(r4h, ict_dir)
    if not ok4: return None

    ok1, ema21_1h, det_1h = _get_1h_zone(r1h, ict_dir)
    if not ok1: return None

    status, candles, time_min, rsi_15m, det_15m = _check_15m(r15m, ict_dir, ema21_1h)
    if status is None: return None

    # Build entry/SL depending on status
    if status == APPROACHING:
        # Limit order at EMA21; estimate SL from 1H ATR
        kl1h = _parse(r1h)
        atr1h = _atr14(kl1h) or price * 0.008
        entry = ema21_1h
        sl    = (ema21_1h - atr1h * 1.2) if ict_dir == "bullish" else (ema21_1h + atr1h * 1.2)
        vr    = 1.0
        pat   = ""
        det_5m = f"Set LIMIT at {_fmt(ema21_1h)} -- wait for price to arrive"

    else:  # CONFIRMED — need 5M
        r5m = await client.klines(sym, "5m", 100)
        ok5, entry, sl, vr, pat, det_5m = _check_5m(r5m, ict_dir, ema21_1h)
        if not ok5: return None

    loss_pct = abs(entry - sl) / entry * 100
    if not (0 < loss_pct <= MAX_SL_PCT * 100): return None

    tp, tp_rsn = _find_tp(r1h, entry, sl, ict_dir)
    rr = abs(tp - entry) / abs(sl - entry) if sl != entry else 0
    if rr < MIN_RR: return None

    lev = max(1, min(10, math.floor(15 / loss_pct)))

    sig = EMASignal(
        symbol=sym,     direction=direction,  status=status,
        entry=entry,    sl=sl,                tp=tp,
        rr=rr,          leverage=lev,         loss_pct=loss_pct,
        score=0.0,      e9_4h=e9_4,           e21_4h=e21_4,
        e50_4h=e50_4,   ema21_1h=ema21_1h,    candles=candles,
        time_min=time_min, rsi_15m=rsi_15m,   vol_ratio=vr,
        pattern=pat,    det_4h=det_4h,         det_1h=det_1h,
        det_15m=det_15m, det_5m=det_5m,        tp_rsn=tp_rsn,
        btc=bias,
    )
    sig.score = _score(sig)
    return sig


# ── Display ────────────────────────────────────────────────────────────────────

def _grade(s: float) -> str:
    if s >= 82: return "A+"
    if s >= 68: return "A "
    if s >= 54: return "B "
    return "C "


def _format(rank: int, sig: EMASignal) -> str:
    sl_s = "-" if sig.direction == "LONG" else "+"
    tp_p = abs(sig.tp - sig.entry) / sig.entry * 100
    tp_s = "+" if sig.direction == "LONG" else "-"
    gr   = _grade(sig.score)
    icon = "LONG " if sig.direction == "LONG" else "SHORT"

    if sig.status == APPROACHING:
        banner     = f"  >>>  APPROACHING  --  ~{sig.time_min}min to EMA21  <<<"
        entry_line = f"  Limit Order : {_fmt(sig.entry)}  [set now at 1H EMA21]"
    else:
        banner     = f"  >>>  AT ZONE -- 5M confirmed -- enter NOW  <<<"
        entry_line = f"  Entry       : {_fmt(sig.entry)}  [{sig.pattern}]"

    return (
        f"\n+{'='*64}+\n"
        f"|  #{rank:<2}  {icon}  {sig.symbol:<18}  [{sig.status}]  Grade:{gr} |\n"
        f"|  Score: {sig.score:>5.1f}/100  {_bar(sig.score)}                         |\n"
        f"+{'='*64}+\n"
        f"{banner}\n"
        f"  {'─'*60}\n"
        f"  BTC bias   : {sig.btc.upper()}\n"
        f"  4H Trend   : {sig.det_4h}\n"
        f"  1H Zone    : {sig.det_1h}\n"
        f"  15M Status : {sig.det_15m}\n"
        f"  5M         : {sig.det_5m}\n"
        f"  {'─'*60}\n"
        f"{entry_line}\n"
        f"  Stop Loss  : {_fmt(sig.sl)}  ({sl_s}{sig.loss_pct:.2f}%)\n"
        f"  TP         : {_fmt(sig.tp)}  ({tp_s}{tp_p:.2f}%)  <- {sig.tp_rsn}\n"
        f"  RRR        : 1:{sig.rr:.1f}  |  Leverage: {sig.leverage}x\n"
        f"  {'─'*60}\n"
        f"  4H EMAs    : 9={_fmt(sig.e9_4h)} / 21={_fmt(sig.e21_4h)} / 50={_fmt(sig.e50_4h)}\n"
        f"  1H EMA21   : {_fmt(sig.ema21_1h)}  RSI 15M: {sig.rsi_15m:.1f}"
        f"{'  Vol: '+str(round(sig.vol_ratio,1))+'x' if sig.status==CONFIRMED else ''}\n"
        f"+{'='*64}+"
    )


# ── Entry point ────────────────────────────────────────────────────────────────

async def main() -> None:
    print("""
+==============================================================+
|  EMA Pullback Scalp v2  --  4H trend + 1H zone + 15M alert |
|  APPROACHING : ~15-60 min warning -> set limit at EMA21     |
|  CONFIRMED   : at zone + 5M candle -> enter now             |
|  DISPLAY ONLY -- no orders placed                           |
+==============================================================+
""")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    conn = aiohttp.TCPConnector(ssl=ctx)

    async with aiohttp.ClientSession(connector=conn) as sess:
        client = BitunixClient(API_KEY, SECRET_KEY, sess)

        print("  BTC bias ...", flush=True)
        btc_raw = {tf: await client.klines("BTCUSDT", tf, 100)
                   for tf in ("4h", "1h", "1d")}
        bias, bias_det = btc_ict_bias(btc_raw)
        btag = "BULL" if bias=="bullish" else ("BEAR" if bias=="bearish" else "NEUT")
        print(f"  BTC -> {btag}  |  {bias_det}\n")

        if bias == "neutral":
            dirs = [("LONG", "bullish"), ("SHORT", "bearish")]
        else:
            dirs = [("LONG" if bias=="bullish" else "SHORT", bias)]

        ticks     = await client.tickers()
        price_map = {t["symbol"]: float(t["lastPrice"])
                     for t in ticks
                     if t.get("lastPrice") and float(t.get("lastPrice", 0)) > 0}
        symbols   = list(price_map.keys())

        print(f"  {len(symbols)} symbols"
              f"  |  4H EMA {EMA_FAST}/{EMA_MID}/{EMA_SLOW}"
              f"  |  1H EMA21 zone"
              f"  |  approach window: {APPROACH_MAX*15}min\n", flush=True)

        t0    = time.time()
        found: List[EMASignal] = []

        for direction, ict_dir in dirs:
            for i in range(0, len(symbols), BATCH_SIZE):
                batch   = symbols[i: i + BATCH_SIZE]
                tasks   = [_scan_one(client, s, price_map[s], bias, direction, ict_dir)
                           for s in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for r in results:
                    if isinstance(r, EMASignal):
                        found.append(r)
                done = i + len(batch)
                print(f"  {done}/{len(symbols)}  found: {len(found)}"
                      f"  [{time.time()-t0:.0f}s]", flush=True)

        elapsed     = time.time() - t0
        approaching = [s for s in found if s.status == APPROACHING]
        confirmed   = [s for s in found if s.status == CONFIRMED]

        print(f"\n{'='*60}")
        print(f"  Done -- {len(found)} signals  [{elapsed:.0f}s]")
        print(f"  APPROACHING: {len(approaching)}  |  CONFIRMED: {len(confirmed)}")
        print(f"{'='*60}\n")

        if not found:
            print("  No setups. Try again in 5-15 minutes.\n")
            return

        # CONFIRMED first (urgent), then APPROACHING by score
        found.sort(key=lambda s: (s.status == CONFIRMED, s.score), reverse=True)

        print(f"  {'#':<4} {'symbol':<16} {'dir':<6} {'status':<14}"
              f" {'grade':<5} {'score':<10} {'~min':<8} {'RRR'}")
        print("  " + "-" * 72)
        for idx, s in enumerate(found, 1):
            tm = f"~{s.time_min}m" if s.status == APPROACHING else "NOW"
            print(f"  #{idx:<3} {s.symbol:<16} {s.direction:<6} {s.status:<14}"
                  f" {_grade(s.score):<5} {s.score:>5.1f}/100  {tm:<8} 1:{s.rr:.1f}")

        print(f"\n  Full detail -- top {min(SHOW_TOP, len(found))}:\n")
        for rank, sig in enumerate(found[:SHOW_TOP], 1):
            print(_format(rank, sig))

        print(f"\n  DISPLAY ONLY -- no orders placed.\n")


if __name__ == "__main__":
    asyncio.run(main())
