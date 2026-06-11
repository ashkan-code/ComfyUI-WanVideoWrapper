#!/usr/bin/env python3
"""
EMA Pullback Scalp Scanner  --  standalone
High win-rate (80%+) trend continuation scalp:

  Flow:
    1. BTC ICT bias (4H + 1H + Daily)  ->  direction
    2. 1H : EMA9 > EMA21 > EMA50 aligned + slope in direction
    3. 15M: price pulled back to EMA21 in last 4 candles, bounced
    4. 5M : bull/bear candle + volume spike + RSI momentum
    5. Score 0-100, display top 10

  Entry  : close of 5M confirmation candle
  SL     : below/above 5M wick  + 0.2%
  TP     : nearest 15M swing giving RR >= 1.5
  DISPLAY ONLY -- no orders placed.
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
EMA_FAST      = 9
EMA_MID       = 21
EMA_SLOW      = 50
RSI_PERIOD    = 14
VOL_MA        = 20
VOL_MULT      = 1.3      # current vol must be >= 1.3x average
PULLBACK_TOL  = 0.006    # 0.6% tolerance for EMA21 touch detection
PROXIMITY_MAX = 0.020    # price must be within 2% of EMA21 (not stale)
MIN_RR        = 1.5
MAX_SL_PCT    = 0.015    # 1.5% max SL for tight scalp
SL_BUFFER     = 0.002    # 0.2% beyond wick
BATCH_SIZE    = 20
SHOW_TOP      = 10


# ── Bitunix client ─────────────────────────────────────────────────────────────

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
    """Full EMA series seeded with SMA."""
    res: List[Optional[float]] = [None] * len(closes)
    if len(closes) < period:
        return res
    res[period - 1] = sum(closes[:period]) / period
    k = 2.0 / (period + 1)
    for i in range(period, len(closes)):
        res[i] = closes[i] * k + res[i - 1] * (1 - k)
    return res


def _last(series: List[Optional[float]]) -> Optional[float]:
    return next((v for v in reversed(series) if v is not None), None)


def _prev_last(series: List[Optional[float]]) -> Tuple[Optional[float], Optional[float]]:
    vals = [v for v in series if v is not None]
    if len(vals) < 2:
        return None, vals[-1] if vals else None
    return vals[-2], vals[-1]


def _rsi_last(klines: list) -> float:
    """Wilder RSI of last bar."""
    closes = [k["close"] for k in klines]
    if len(closes) < RSI_PERIOD + 2:
        return 50.0
    gs, ls = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gs.append(max(d, 0.0)); ls.append(max(-d, 0.0))
    ag = sum(gs[:RSI_PERIOD]) / RSI_PERIOD
    al = sum(ls[:RSI_PERIOD]) / RSI_PERIOD
    for i in range(RSI_PERIOD, len(gs)):
        ag = (ag * (RSI_PERIOD - 1) + gs[i]) / RSI_PERIOD
        al = (al * (RSI_PERIOD - 1) + ls[i]) / RSI_PERIOD
    return 100.0 - 100.0 / (1.0 + ag / al) if al > 0 else 100.0


def _rsi_last2(klines: list) -> Tuple[float, float]:
    """Returns (rsi_prev, rsi_curr) for momentum direction."""
    closes = [k["close"] for k in klines]
    if len(closes) < RSI_PERIOD + 3:
        return 50.0, 50.0
    gs, ls = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gs.append(max(d, 0.0)); ls.append(max(-d, 0.0))
    ag = sum(gs[:RSI_PERIOD]) / RSI_PERIOD
    al = sum(ls[:RSI_PERIOD]) / RSI_PERIOD
    vals: List[float] = []
    cut = len(gs) - 2
    for i in range(RSI_PERIOD, len(gs)):
        ag = (ag * (RSI_PERIOD - 1) + gs[i]) / RSI_PERIOD
        al = (al * (RSI_PERIOD - 1) + ls[i]) / RSI_PERIOD
        if i >= cut:
            vals.append(100.0 - 100.0 / (1.0 + ag / al) if al > 0 else 100.0)
    if len(vals) < 2:
        v = vals[-1] if vals else 50.0
        return 50.0, v
    return vals[-2], vals[-1]


def _vol_ratio(klines: list) -> float:
    """Current vol / MA(VOL_MA). Returns VOL_MULT if no volume data (bypass)."""
    vols = [k["vol"] for k in klines]
    if len(vols) < VOL_MA + 1:
        return VOL_MULT
    ma = sum(vols[-(VOL_MA + 1):-1]) / VOL_MA
    if ma <= 0:
        return VOL_MULT  # no volume data on this exchange endpoint -> bypass
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
    lower = min(o, c) - l
    upper = h - max(o, c)
    return lower >= 2.0 * body and upper <= body * 1.5 and (c - l) / rng >= 0.5


def _is_shoot_star(k: dict) -> bool:
    o, h, l, c = k["open"], k["high"], k["low"], k["close"]
    rng = h - l
    if rng == 0: return False
    body = abs(c - o)
    if body == 0: return False
    upper = h - max(o, c)
    lower = min(o, c) - l
    return upper >= 2.0 * body and lower <= body * 1.5 and (h - c) / rng >= 0.5


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
        if len(sh) >= 2 and lc > kl[sh[-2]]["high"]: sc["bullish"] += 2; det.append(f"{tf.upper()}:BOS+")
        if len(sl2) >= 2 and lc < kl[sl2[-2]]["low"]: sc["bearish"] += 2; det.append(f"{tf.upper()}:BOS-")
    tot = sc["bullish"] + sc["bearish"]
    if tot == 0: return "neutral", " | ".join(det)
    bp = sc["bullish"] / tot * 100
    dp = sc["bearish"] / tot * 100
    if bp >= 60: return "bullish", " | ".join(det) + f" [{bp:.0f}%+]"
    if dp >= 60: return "bearish", " | ".join(det) + f" [{dp:.0f}%-]"
    return "neutral", " | ".join(det)


# ── Strategy: 1H trend check ───────────────────────────────────────────────────

def _check_1h(raw: list, direction: str
              ) -> Tuple[bool, float, float, float, str]:
    """EMA9 > EMA21 > EMA50 aligned, EMA9 sloping in direction.
    Returns (ok, e9, e21, e50, detail)."""
    kl = _parse(raw)
    if len(kl) < EMA_SLOW + 5:
        return False, 0.0, 0.0, 0.0, "insufficient 1H data"
    closes = [k["close"] for k in kl]
    e9s  = _ema_vals(closes, EMA_FAST)
    e21s = _ema_vals(closes, EMA_MID)
    e50s = _ema_vals(closes, EMA_SLOW)
    e9p, e9   = _prev_last(e9s)
    _,   e21  = _prev_last(e21s)
    _,   e50  = _prev_last(e50s)
    if None in (e9, e9p, e21, e50):
        return False, 0.0, 0.0, 0.0, "EMA calc failed"
    if direction == "bullish":
        aligned  = e9 > e21 > e50
        slope_ok = e9 > e9p
    else:
        aligned  = e9 < e21 < e50
        slope_ok = e9 < e9p
    ok  = aligned and slope_ok
    tag = "[OK]" if ok else "[NO]"
    det = f"1H EMA9={_fmt(e9)} / EMA21={_fmt(e21)} / EMA50={_fmt(e50)} {tag}"
    return ok, e9, e21, e50, det


# ── Strategy: 15M pullback check ──────────────────────────────────────────────

def _check_15m(raw: list, direction: str
               ) -> Tuple[bool, float, float, str]:
    """Price pulled back to EMA21 in last 4 candles and bounced.
    Returns (ok, ema21, rsi, detail)."""
    kl = _parse(raw)
    if len(kl) < EMA_MID + 10:
        return False, 0.0, 50.0, "insufficient 15M data"
    closes = [k["close"] for k in kl]
    e9s  = _ema_vals(closes, EMA_FAST)
    e21s = _ema_vals(closes, EMA_MID)
    e9  = _last(e9s)
    e21 = _last(e21s)
    if e9 is None or e21 is None or e21 == 0:
        return False, 0.0, 50.0, "EMA21 calc failed"

    # Short-term EMA alignment must hold on 15M
    if direction == "bullish" and e9 < e21:
        return False, e21, 50.0, f"15M EMA9 < EMA21 -- trend broken"
    if direction == "bearish" and e9 > e21:
        return False, e21, 50.0, f"15M EMA9 > EMA21 -- trend broken"

    # Current price must be within 2% of EMA21 (setup not stale)
    cur = kl[-1]["close"]
    prox = abs(cur - e21) / e21
    if prox > PROXIMITY_MAX:
        return False, e21, 50.0, f"Price {prox*100:.1f}% from EMA21 -- stale"

    # Pullback touch: last 4 candles
    tol = e21 * PULLBACK_TOL
    touched = None
    for i in range(-1, -5, -1):
        if abs(i) > len(kl): break
        k = kl[i]
        if direction == "bullish":
            # Low pierced EMA21 zone AND closed above (bounce)
            if k["low"] <= e21 + tol and k["close"] > e21 * 0.998:
                touched = abs(i); break
        else:
            # High pierced EMA21 zone AND closed below (rejection)
            if k["high"] >= e21 - tol and k["close"] < e21 * 1.002:
                touched = abs(i); break
    if touched is None:
        return False, e21, 50.0, f"No EMA21({_fmt(e21)}) touch in last 4 candles"

    # RSI 15M: must be in pullback cooling-off range
    rsi = _rsi_last(kl[-50:] if len(kl) >= 50 else kl)
    if direction == "bullish" and not (28 <= rsi <= 65):
        return False, e21, rsi, f"RSI15={rsi:.1f} outside pullback range 28-65"
    if direction == "bearish" and not (35 <= rsi <= 72):
        return False, e21, rsi, f"RSI15={rsi:.1f} outside pullback range 35-72"

    det = (f"15M EMA21={_fmt(e21)} touched {touched}c ago"
           f"  RSI={rsi:.1f}  dist={prox*100:.2f}%")
    return True, e21, rsi, det


# ── Strategy: 5M confirmation ─────────────────────────────────────────────────

def _check_5m(raw: list, direction: str, ema21_15m: float
              ) -> Tuple[bool, float, float, float, str, str]:
    """Bullish/bearish candle at EMA21 with volume and RSI momentum.
    Returns (ok, entry, sl, vol_ratio, pattern, detail)."""
    kl = _parse(raw)
    if len(kl) < 30:
        return False, 0.0, 0.0, 1.0, "", "insufficient 5M data"

    kc, kp = kl[-1], kl[-2]
    vr = _vol_ratio(kl)
    if vr < VOL_MULT:
        return False, 0.0, 0.0, vr, "", f"vol {vr:.1f}x < {VOL_MULT}x"

    rsi_p, rsi_c = _rsi_last2(kl)

    if direction == "bullish":
        # RSI must not be in freefall (allow flat or rising)
        if rsi_c < rsi_p - 6:
            return False, 0.0, 0.0, vr, "", f"RSI5m falling ({rsi_p:.0f}->{rsi_c:.0f})"
        # Candle must be at or just above EMA21 (15M)
        near = kc["low"] <= ema21_15m * 1.015
        if not near:
            return False, 0.0, 0.0, vr, "", f"5M not near EMA21({_fmt(ema21_15m)})"

        if _is_bull_engulf(kp, kc):   pat = "Bull Engulfing"
        elif _is_hammer(kc):          pat = "Hammer"
        elif kc["close"] > kc["open"]: pat = "Bull Candle"
        else:
            return False, 0.0, 0.0, vr, "", "no bullish 5M pattern"

        entry = kc["close"]
        sl    = kc["low"] * (1 - SL_BUFFER)

    else:  # bearish
        if rsi_c > rsi_p + 6:
            return False, 0.0, 0.0, vr, "", f"RSI5m rising ({rsi_p:.0f}->{rsi_c:.0f})"
        near = kc["high"] >= ema21_15m * 0.985
        if not near:
            return False, 0.0, 0.0, vr, "", f"5M not near EMA21({_fmt(ema21_15m)})"

        if _is_bear_engulf(kp, kc):    pat = "Bear Engulfing"
        elif _is_shoot_star(kc):       pat = "Shooting Star"
        elif kc["close"] < kc["open"]: pat = "Bear Candle"
        else:
            return False, 0.0, 0.0, vr, "", "no bearish 5M pattern"

        entry = kc["close"]
        sl    = kc["high"] * (1 + SL_BUFFER)

    det = f"5M {pat}  RSI={rsi_c:.1f}({rsi_p:.0f}->{rsi_c:.0f})  vol={vr:.1f}x"
    return True, entry, sl, vr, pat, det


# ── TP finder ─────────────────────────────────────────────────────────────────

def _find_tp(raw_15m: list, entry: float, sl: float,
             direction: str) -> Tuple[float, str]:
    kl   = _parse(raw_15m)
    risk = abs(entry - sl) or entry * 0.005
    md   = risk * MIN_RR

    if direction == "bullish":
        cands: List[Tuple[float, str]] = []
        for i in _swing_highs(kl, 2):
            p = kl[i]["high"]
            if p > entry + md: cands.append((p, "SH 15M"))
        highs = [k["high"] for k in kl[-80:]]
        seen: List[float] = []
        for p in highs:
            if any(abs(p - s) / s < 0.003 for s in seen) and p > entry + md:
                cands.append((p, "EQH 15M"))
            seen.append(p)
        if cands: return min(cands, key=lambda x: x[0])
    else:
        cands = []
        for i in _swing_lows(kl, 2):
            p = kl[i]["low"]
            if p < entry - md: cands.append((p, "SL 15M"))
        lows = [k["low"] for k in kl[-80:]]
        seen_l: List[float] = []
        for p in lows:
            if any(abs(p - s) / s < 0.003 for s in seen_l) and p < entry - md:
                cands.append((p, "EQL 15M"))
            seen_l.append(p)
        if cands: return max(cands, key=lambda x: x[0])

    tp = entry + md if direction == "bullish" else entry - md
    return tp, f"{MIN_RR}:1 fallback"


# ── Signal + scoring ───────────────────────────────────────────────────────────

@dataclass
class EMASignal:
    symbol:    str
    direction: str
    entry:     float
    sl:        float
    tp:        float
    rr:        float
    leverage:  int
    loss_pct:  float
    score:     float
    e9_1h:     float
    e21_1h:    float
    e50_1h:    float
    e21_15m:   float
    rsi_15m:   float
    vol_ratio: float
    pattern:   str
    t_det:     str
    pb_det:    str
    c_det:     str
    tp_rsn:    str
    btc:       str


def _score(sig: EMASignal) -> float:
    s = 0.0
    # Trend strength: EMA9-EMA50 gap as % of price (25 pts)
    gap = abs(sig.e9_1h - sig.e50_1h) / sig.e50_1h * 100 if sig.e50_1h else 0
    s += min(15.0 + gap * 2.0, 25.0)
    # Pullback RSI quality: ideal ~45 LONG / ~55 SHORT (20 pts)
    ideal = 45.0 if sig.direction == "LONG" else 55.0
    s += max(0.0, 20.0 - abs(sig.rsi_15m - ideal) * 0.7)
    # Volume (20 pts)
    s += min(sig.vol_ratio / 3.0, 1.0) * 20.0
    # Candle pattern quality (20 pts)
    if "Engulfing" in sig.pattern:  s += 20.0
    elif "Hammer" in sig.pattern or "Star" in sig.pattern: s += 15.0
    else: s += 8.0
    # RR quality (15 pts)
    s += min(sig.rr / (MIN_RR * 2.0), 1.0) * 15.0
    return min(s, 100.0)


async def _scan_one(client: BitunixClient, sym: str, price: float,
                    bias: str, direction: str, ict_dir: str
                    ) -> Optional[EMASignal]:
    r1h, r15m, r5m = await asyncio.gather(
        client.klines(sym, "1h",  100),
        client.klines(sym, "15m",  80),
        client.klines(sym, "5m",  100),
    )

    ok1, e9, e21_1h, e50, t_det = _check_1h(r1h, ict_dir)
    if not ok1: return None

    ok2, e21_15m, rsi_15m, pb_det = _check_15m(r15m, ict_dir)
    if not ok2: return None

    ok3, entry, sl, vr, pat, c_det = _check_5m(r5m, ict_dir, e21_15m)
    if not ok3: return None

    loss_pct = abs(entry - sl) / entry * 100
    if not (0 < loss_pct <= MAX_SL_PCT * 100): return None

    tp, tp_rsn = _find_tp(r15m, entry, sl, ict_dir)
    rr = abs(tp - entry) / abs(sl - entry) if sl != entry else 0
    if rr < MIN_RR: return None

    lev = max(1, min(10, math.floor(15 / loss_pct)))
    sig = EMASignal(
        symbol=sym, direction=direction,
        entry=entry, sl=sl, tp=tp, rr=rr,
        leverage=lev, loss_pct=loss_pct, score=0.0,
        e9_1h=e9, e21_1h=e21_1h, e50_1h=e50,
        e21_15m=e21_15m, rsi_15m=rsi_15m,
        vol_ratio=vr, pattern=pat,
        t_det=t_det, pb_det=pb_det, c_det=c_det,
        tp_rsn=tp_rsn, btc=bias,
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
    return (
        f"\n+{'='*62}+\n"
        f"|  #{rank:<2}  {'LONG ' if sig.direction=='LONG' else 'SHORT'}"
        f"  {sig.symbol:<20}  Grade: {gr}         |\n"
        f"|  Score: {sig.score:>5.1f}/100  {_bar(sig.score)}                       |\n"
        f"+{'='*62}+\n"
        f"  BTC bias  : {sig.btc.upper()}\n"
        f"  1H Trend  : {sig.t_det}\n"
        f"  Pullback  : {sig.pb_det}\n"
        f"  5M Signal : {sig.c_det}\n"
        f"  {'─'*58}\n"
        f"  Entry     : {_fmt(sig.entry)}  [{sig.pattern}]\n"
        f"  Stop Loss : {_fmt(sig.sl)}  ({sl_s}{sig.loss_pct:.2f}%)  <- 5M wick\n"
        f"  TP        : {_fmt(sig.tp)}  ({tp_s}{tp_p:.2f}%)  <- {sig.tp_rsn}\n"
        f"  RRR       : 1:{sig.rr:.1f}  |  Leverage: {sig.leverage}x\n"
        f"  {'─'*58}\n"
        f"  EMA 1H    : 9={_fmt(sig.e9_1h)} / 21={_fmt(sig.e21_1h)} / 50={_fmt(sig.e50_1h)}\n"
        f"  EMA21 15M : {_fmt(sig.e21_15m)}  RSI 15M: {sig.rsi_15m:.1f}"
        f"  Vol: {sig.vol_ratio:.1f}x\n"
        f"+{'='*62}+"
    )


# ── Entry point ────────────────────────────────────────────────────────────────

async def main() -> None:
    print("""
+============================================================+
|  EMA Pullback Scalp Scanner  (target win rate 80%+)       |
|  1H: EMA9>21>50 trend  |  15M: pullback to EMA21         |
|  5M: candle + volume + RSI  |  Min RR: 1.5               |
|  DISPLAY ONLY -- no orders placed                         |
+============================================================+
""")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE
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
            print("  BTC neutral -- scanning both directions\n")
        else:
            dirs = [("LONG" if bias == "bullish" else "SHORT", bias)]

        ticks     = await client.tickers()
        price_map = {t["symbol"]: float(t["lastPrice"])
                     for t in ticks
                     if t.get("lastPrice") and float(t.get("lastPrice", 0)) > 0}
        symbols   = list(price_map.keys())
        print(f"  {len(symbols)} symbols  |  EMA {EMA_FAST}/{EMA_MID}/{EMA_SLOW}"
              f"  |  vol >={VOL_MULT}x  |  SL <={MAX_SL_PCT*100:.1f}%"
              f"  |  RR >={MIN_RR}\n", flush=True)

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

        elapsed = time.time() - t0
        print(f"\n{'='*58}")
        print(f"  EMA Scalp scan done  --  {len(found)} signals  [{elapsed:.0f}s]")
        print(f"{'='*58}\n")

        if not found:
            print("  No setups. Market not at EMA21 pullback. Try again in 5-15 min.\n")
            return

        found.sort(key=lambda s: s.score, reverse=True)

        print(f"  {'#':<4} {'symbol':<16} {'dir':<6} {'grade':<6}"
              f" {'score':<10} {'RSI15':<8} {'vol':<8} {'RRR'}")
        print("  " + "-" * 68)
        for idx, s in enumerate(found, 1):
            print(f"  #{idx:<3} {s.symbol:<16} {s.direction:<6} {_grade(s.score):<6}"
                  f" {s.score:>5.1f}/100  {s.rsi_15m:>5.1f}   {s.vol_ratio:.1f}x"
                  f"    1:{s.rr:.1f}")

        print(f"\n  Full detail -- top {min(SHOW_TOP, len(found))}:\n")
        for rank, sig in enumerate(found[:SHOW_TOP], 1):
            print(_format(rank, sig))

        print(f"\n  DISPLAY ONLY -- no orders placed.\n")


if __name__ == "__main__":
    asyncio.run(main())
