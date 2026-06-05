#!/usr/bin/env python3
"""
Run this once to fix wyckoff_pro.py:
  python patch.py
Then:
  python wyckoff_pro.py
"""
import os

CONTENT = r'''#!/usr/bin/env python3
"""
Wyckoff Pro -- Standalone (no external dependencies except aiohttp)
5-method backtest + per-method signal.

Run:  python wyckoff_pro.py
Install aiohttp first:  pip install aiohttp
"""

import asyncio, hashlib, json, math, os, ssl, sys, time, uuid
from dataclasses import dataclass, field
from statistics import mean
from typing import Dict, List, Optional, Tuple

import aiohttp

API_KEY    = os.getenv("BITUNIX_API_KEY",    "68f0a1765f124bacb847afa8db78e480")
SECRET_KEY = os.getenv("BITUNIX_SECRET_KEY", "159808597389a1cd1fc429f9f469209b")
BASE_URL   = "https://fapi.bitunix.com"

SCAN_TFS    = ["1d", "4h"]
KLINE_LIMIT = 500
BT_FORWARD  = 60
MIN_BT_SIGS = 5
BATCH_SIZE  = 20
SHOW_TOP    = 5
SL_BUFFER   = 0.005


# ══════════════════════════════════════════════════════════════════════════════
#  BITUNIX CLIENT (inline)
# ══════════════════════════════════════════════════════════════════════════════

_SEMAPHORE = None

def _get_sem():
    global _SEMAPHORE
    if _SEMAPHORE is None:
        _SEMAPHORE = asyncio.Semaphore(8)
    return _SEMAPHORE

def _sha256(s): return hashlib.sha256(s.encode()).hexdigest()

def _headers(api_key, secret_key, qs="", body=""):
    nonce = uuid.uuid4().hex
    ts    = str(int(time.time() * 1000))
    dig   = _sha256(nonce + ts + api_key + qs + body)
    sign  = _sha256(dig + secret_key)
    return {"api-key": api_key, "nonce": nonce, "timestamp": ts,
            "sign": sign, "Content-Type": "application/json"}

class BitunixClient:
    def __init__(self, api_key, secret_key, session):
        self.ak = api_key; self.sk = secret_key; self.s = session

    async def _pub(self, path, params=None):
        async with _get_sem():
            async with self.s.get(BASE_URL + path, params=params,
                                   timeout=aiohttp.ClientTimeout(total=15)) as r:
                return await r.json(content_type=None)

    async def get_tickers(self):
        d = await self._pub("/api/v1/futures/market/tickers")
        return d.get("data") or []

    async def get_klines(self, symbol, interval, limit=200):
        d = await self._pub("/api/v1/futures/market/kline",
                            {"symbol": symbol, "interval": interval, "limit": limit})
        return d.get("data") or []


# ══════════════════════════════════════════════════════════════════════════════
#  ICT / WYCKOFF HELPERS (inline)
# ══════════════════════════════════════════════════════════════════════════════

def _fmt(p):
    if p >= 1000: return f"{p:,.2f}"
    if p >= 1:    return f"{p:.4f}"
    return f"{p:.6f}"

def _parse(raw):
    out = []
    for k in raw:
        try:
            out.append({"open": float(k["open"]), "high": float(k["high"]),
                        "low":  float(k["low"]),  "close": float(k["close"]),
                        "time": float(k.get("time", 0))})
        except: pass
    out.sort(key=lambda x: x["time"])
    return out

def _atr(klines, period=14):
    n   = len(klines)
    trs = [0.0] * n
    for i in range(1, n):
        h, l, pc = klines[i]["high"], klines[i]["low"], klines[i-1]["close"]
        trs[i] = max(h - l, abs(h - pc), abs(l - pc))
    atr = [None] * n
    for i in range(period, n):
        atr[i] = sum(trs[i-period+1:i+1]) / period
    return atr

def _sh(klines, n=3):
    idxs = []
    for i in range(n, len(klines) - n):
        w = [klines[j]["high"] for j in range(i-n, i+n+1)]
        if klines[i]["high"] == max(w): idxs.append(i)
    return idxs

def _sl(klines, n=3):
    idxs = []
    for i in range(n, len(klines) - n):
        w = [klines[j]["low"] for j in range(i-n, i+n+1)]
        if klines[i]["low"] == min(w): idxs.append(i)
    return idxs

def _ms(klines, lookback=50):
    k = klines[-lookback:] if len(klines) >= lookback else klines
    if len(k) < 10: return "neutral"
    sh, sl = _sh(k, 3), _sl(k, 3)
    if len(sh) >= 2 and len(sl) >= 2:
        hh = k[sh[-1]]["high"] > k[sh[-2]]["high"]
        hl = k[sl[-1]]["low"]  > k[sl[-2]]["low"]
        lh = k[sh[-1]]["high"] < k[sh[-2]]["high"]
        ll = k[sl[-1]]["low"]  < k[sl[-2]]["low"]
        if hh and hl: return "bullish"
        if lh and ll: return "bearish"
    return "neutral"

def _btc_bias(tf_kl):
    scores = {"bullish": 0, "bearish": 0}
    raw4h  = tf_kl.get("4h", [])
    raw1h  = tf_kl.get("1h", [])
    raw1d  = tf_kl.get("1d", [])
    if raw4h:
        ms = _ms(_parse(raw4h), 60)
        if ms == "bullish": scores["bullish"] += 4
        elif ms == "bearish": scores["bearish"] += 4
        kl = _parse(raw4h)
        if kl:
            last = kl[-1]["close"]
            recent = kl[-60:] if len(kl)>=60 else kl
            sh4 = _sh(recent, 3); sl4 = _sl(recent, 3)
            if len(sh4)>=2 and last > recent[sh4[-2]]["high"]: scores["bullish"] += 3
            if len(sl4)>=2 and last < recent[sl4[-2]]["low"]:  scores["bearish"] += 3
    if raw1h:
        ms = _ms(_parse(raw1h), 40)
        if ms == "bullish": scores["bullish"] += 2
        elif ms == "bearish": scores["bearish"] += 2
    if raw1d:
        ms = _ms(_parse(raw1d), 30)
        if ms == "bullish": scores["bullish"] += 2
        elif ms == "bearish": scores["bearish"] += 2
    total = scores["bullish"] + scores["bearish"]
    if total == 0: return "neutral"
    bp = scores["bullish"] / total * 100
    if bp >= 60: return "bullish"
    if (100-bp) >= 60: return "bearish"
    return "neutral"

def _wyckoff_spring(raw, direction,
                    lookback=500, equal_tol=0.005, min_pierce=0.002,
                    wick_ratio=2.0, max_age=6, min_gap=4):
    klines = _parse(raw)
    if len(klines) < 30: return False, {}
    recent = klines[-lookback:] if len(klines) >= lookback else klines
    n = len(recent)

    if direction == "bullish":
        sl_i = _sl(recent[:max(n-3,15)], 3)
        if len(sl_i) < 2: return False, {}
        for i in range(len(sl_i)-1, 0, -1):
            for j in range(i-1, -1, -1):
                if sl_i[i] - sl_i[j] < min_gap: continue
                la, lb = recent[sl_i[i]]["low"], recent[sl_i[j]]["low"]
                if abs(la-lb)/la > equal_tol: continue
                level = min(la, lb)
                for k in range(sl_i[i]+1, n):
                    c = recent[k]
                    if c["low"] >= level*(1-min_pierce): continue
                    if c["close"] < level*1.001: continue
                    body = abs(c["close"]-c["open"])
                    lw = min(c["open"],c["close"]) - c["low"]
                    if body == 0 or lw < body*wick_ratio: continue
                    if k < n - max_age: continue
                    return True, {"level":level,"swept":c["low"],
                                  "pierce":(level-c["low"])/level*100,
                                  "age":n-1-k,"candle":c,
                                  "eq_lo1":la,"eq_lo2":lb}
    else:
        sh_i = _sh(recent[:max(n-3,15)], 3)
        if len(sh_i) < 2: return False, {}
        for i in range(len(sh_i)-1, 0, -1):
            for j in range(i-1, -1, -1):
                if sh_i[i] - sh_i[j] < min_gap: continue
                ha, hb = recent[sh_i[i]]["high"], recent[sh_i[j]]["high"]
                if abs(ha-hb)/ha > equal_tol: continue
                level = max(ha, hb)
                for k in range(sh_i[i]+1, n):
                    c = recent[k]
                    if c["high"] <= level*(1+min_pierce): continue
                    if c["close"] > level*0.999: continue
                    body = abs(c["close"]-c["open"])
                    uw = c["high"] - max(c["open"],c["close"])
                    if body == 0 or uw < body*wick_ratio: continue
                    if k < n - max_age: continue
                    return True, {"level":level,"swept":c["high"],
                                  "pierce":(c["high"]-level)/level*100,
                                  "age":n-1-k,"candle":c}
    return False, {}


# ══════════════════════════════════════════════════════════════════════════════
#  BACKTEST ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def _backtest(klines, signals, direction):
    wins = total = 0
    for bar_idx, entry, sl, tp in signals:
        if sl<=0 or tp<=0 or entry<=0: continue
        if direction=="bullish" and (sl>=entry or tp<=entry): continue
        if direction=="bearish" and (sl<=entry or tp>=entry): continue
        resolved = False
        for j in range(bar_idx+1, min(bar_idx+BT_FORWARD+1, len(klines))):
            c = klines[j]
            if direction == "bullish":
                if c["high"] >= tp:  wins += 1; resolved = True; break
                if c["low"]  <= sl:  resolved = True; break
            else:
                if c["low"]  <= tp:  wins += 1; resolved = True; break
                if c["high"] >= sl:  resolved = True; break
        if resolved: total += 1
    return wins, total


# ══════════════════════════════════════════════════════════════════════════════
#  5 METHODS
# ══════════════════════════════════════════════════════════════════════════════

def _sig_rtm(klines, direction):
    sigs = []; atr_v = _atr(klines); n = len(klines)
    for i in range(10, n-1):
        a = atr_v[i]
        if not a: continue
        bs = i-5
        if bs < 2: continue
        bc = klines[bs:i]
        bh = max(c["high"] for c in bc); bl = min(c["low"] for c in bc)
        if bh-bl > a*1.2: continue
        c = klines[i]
        if direction == "bullish":
            if c["close"] <= bh: continue
            if abs(c["close"]-c["open"]) < a*0.3: continue
            prior = klines[max(0,bs-20):bs]
            if not prior: continue
            origin = min(p["low"] for p in prior)
            sl = origin*(1-SL_BUFFER)
            sh_i = _sh(klines[:i], 3)
            cands = [klines[j]["high"] for j in sh_i if klines[j]["high"] > c["close"]*1.005]
            tp = min(cands) if cands else c["close"]*1.04
            sigs.append((i, c["close"], sl, tp))
        else:
            if c["close"] >= bl: continue
            if abs(c["close"]-c["open"]) < a*0.3: continue
            prior = klines[max(0,bs-20):bs]
            if not prior: continue
            origin = max(p["high"] for p in prior)
            sl = origin*(1+SL_BUFFER)
            sl_i = _sl(klines[:i], 3)
            cands = [klines[j]["low"] for j in sl_i if klines[j]["low"] < c["close"]*0.995]
            tp = max(cands) if cands else c["close"]*0.96
            sigs.append((i, c["close"], sl, tp))
    return sigs


def _sig_brooks(klines, direction):
    sigs = []; atr_v = _atr(klines); n = len(klines)
    for i in range(6, n-1):
        a = atr_v[i]
        if not a: continue
        bar = klines[i]
        for w in (4, 5, 6, 7, 8):
            ts = i - w
            if ts < 1: continue
            tc = klines[ts:i]
            th = max(x["high"] for x in tc); tl = min(x["low"] for x in tc)
            rng = th - tl
            if rng > a * 4.0 or rng < a * 0.1: continue
            if direction == "bullish":
                if bar["close"] <= th: continue
                sigs.append((i, bar["close"], tl*(1-SL_BUFFER*0.5), bar["close"]+rng*1.5))
            else:
                if bar["close"] >= tl: continue
                sigs.append((i, bar["close"], th*(1+SL_BUFFER*0.5), bar["close"]-rng*1.5))
            break
    return sigs


def _sig_adv_pa(klines, direction):
    sigs = []; atr_v = _atr(klines); n = len(klines)
    sh_i = _sh(klines, 3); sl_i = _sl(klines, 3)
    for i in range(10, n-1):
        a = atr_v[i]
        if not a: continue
        c = klines[i]
        body = abs(c["close"]-c["open"]); rng = c["high"]-c["low"]
        if rng == 0: continue
        if direction == "bullish":
            lw = min(c["open"],c["close"]) - c["low"]
            if lw < body*1.5 or lw < a*0.3: continue
            if c["close"] < c["low"]+rng*0.5: continue
            near = any(abs(klines[j]["low"]-c["low"])/c["low"]<0.025
                       for j in sl_i if j < i-2)
            if not near: continue
            sl = c["low"]*(1-SL_BUFFER)
            cands = [klines[j]["high"] for j in sh_i if j<i and klines[j]["high"]>c["close"]*1.005]
            tp = min(cands) if cands else c["close"]*1.04
            sigs.append((i, c["close"], sl, tp))
        else:
            uw = c["high"] - max(c["open"],c["close"])
            if uw < body*1.5 or uw < a*0.3: continue
            if c["close"] > c["low"]+rng*0.45: continue
            near = any(abs(klines[j]["high"]-c["high"])/c["high"]<0.025
                       for j in sh_i if j < i-2)
            if not near: continue
            sl = c["high"]*(1+SL_BUFFER)
            cands = [klines[j]["low"] for j in sl_i if j<i and klines[j]["low"]<c["close"]*0.995]
            tp = max(cands) if cands else c["close"]*0.96
            sigs.append((i, c["close"], sl, tp))
    return sigs


def _sig_ict(klines, direction):
    sigs = []; atr_v = _atr(klines); n = len(klines)
    sh_i = _sh(klines, 3); sl_i = _sl(klines, 3)
    for i in range(6, n-1):
        a = atr_v[i]
        if not a: continue
        c = klines[i]
        if direction == "bullish":
            for oi in (i-1, i-2):
                if oi < 1: continue
                ob = klines[oi]
                if ob["close"] >= ob["open"]: continue
                if c["close"] < ob["high"]*1.005: continue
                if c["close"]-ob["close"] < a*0.8: continue
                ob_lo = min(ob["open"],ob["close"]); ob_hi = max(ob["open"],ob["close"])
                entry = (ob_lo+ob_hi)/2; sl = ob_lo*(1-SL_BUFFER)
                cands = [klines[j]["high"] for j in sh_i if j<i and klines[j]["high"]>entry*1.005]
                tp = min(cands) if cands else entry*1.04
                if entry>0 and sl>0 and tp>entry: sigs.append((i,entry,sl,tp))
                break
        else:
            for oi in (i-1, i-2):
                if oi < 1: continue
                ob = klines[oi]
                if ob["close"] <= ob["open"]: continue
                if c["close"] > ob["low"]*0.995: continue
                if ob["close"]-c["close"] < a*0.8: continue
                ob_lo = min(ob["open"],ob["close"]); ob_hi = max(ob["open"],ob["close"])
                entry = (ob_lo+ob_hi)/2; sl = ob_hi*(1+SL_BUFFER)
                cands = [klines[j]["low"] for j in sl_i if j<i and klines[j]["low"]<entry*0.995]
                tp = max(cands) if cands else entry*0.96
                if entry>0 and sl>0 and tp<entry: sigs.append((i,entry,sl,tp))
                break
    return sigs


def _sig_smc(klines, direction):
    sigs = []; atr_v = _atr(klines); n = len(klines)
    sh_i = _sh(klines, 3); sl_i = _sl(klines, 3)
    for i in range(10, n-1):
        a = atr_v[i]
        if not a: continue
        c = klines[i]
        if direction == "bullish":
            rl = [klines[j]["low"] for j in sl_i if j<i-2 and j>=i-30]
            if len(rl) < 2: continue
            eq_lo = min(rl)
            if c["low"] >= eq_lo or c["close"] < eq_lo: continue
            ob_idx = next((k for k in range(i-1,max(i-8,0),-1)
                           if klines[k]["close"]<klines[k]["open"]), None)
            if ob_idx is None: continue
            ob = klines[ob_idx]
            entry = max(ob["open"],ob["close"])
            sl = c["low"]*(1-SL_BUFFER)
            cands = [klines[j]["high"] for j in sh_i if j<i and klines[j]["high"]>entry*1.008]
            tp = min(cands) if cands else entry*1.05
            if entry>0 and sl>0 and tp>entry: sigs.append((i,entry,sl,tp))
        else:
            rh = [klines[j]["high"] for j in sh_i if j<i-2 and j>=i-30]
            if len(rh) < 2: continue
            eq_hi = max(rh)
            if c["high"] <= eq_hi or c["close"] > eq_hi: continue
            ob_idx = next((k for k in range(i-1,max(i-8,0),-1)
                           if klines[k]["close"]>klines[k]["open"]), None)
            if ob_idx is None: continue
            ob = klines[ob_idx]
            entry = min(ob["open"],ob["close"])
            sl = c["high"]*(1+SL_BUFFER)
            cands = [klines[j]["low"] for j in sl_i if j<i and klines[j]["low"]<entry*0.992]
            tp = max(cands) if cands else entry*0.95
            if entry>0 and sl>0 and tp<entry: sigs.append((i,entry,sl,tp))
    return sigs


METHODS = {
    "RTM":    _sig_rtm,
    "Brooks": _sig_brooks,
    "Adv PA": _sig_adv_pa,
    "ICT":    _sig_ict,
    "SMC":    _sig_smc,
}


# ══════════════════════════════════════════════════════════════════════════════
#  DATACLASSES + DISPLAY
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class MResult:
    name: str; wins: int; total: int; wr: float
    entry: float; sl: float; tp: float; rr: float

@dataclass
class Candidate:
    symbol: str; direction: str; tf: str
    level: float; swept: float; pierce: float; age: int
    methods: List[MResult] = field(default_factory=list)
    def best_wr(self): return max((m.wr for m in self.methods if m.total>=MIN_BT_SIGS), default=0)
    def avg_wr(self):
        r = [m.wr for m in self.methods if m.total>=MIN_BT_SIGS]
        return mean(r) if r else 0

def _bar(s):
    f = round(s/10); return "#"*f + "."*(10-f)

def _rank(wr):
    if wr>=0.72: return "ELITE"
    if wr>=0.60: return "STRONG"
    if wr>=0.50: return "VALID"
    return "WEAK"

def _run_method(name, klines, direction, price):
    sigs = METHODS[name](klines, direction)
    hist = [(i,e,s,t) for i,e,s,t in sigs if i < len(klines)-3]
    wins, total = _backtest(klines, hist, direction)
    wr = wins/total if total>0 else 0.0
    live = [(i,e,s,t) for i,e,s,t in sigs if i >= len(klines)-5]
    if live:
        _, entry, sl, tp = live[-1]
    elif hist:
        _, he, hs, ht = hist[-1]
        rsl = abs(he-hs)/he if he>0 else 0.02
        rtp = abs(ht-he)/he if he>0 else 0.04
        if direction=="bullish":
            entry=price; sl=price*(1-rsl); tp=price*(1+rtp)
        else:
            entry=price; sl=price*(1+rsl); tp=price*(1-rtp)
    else:
        entry=price
        sl=price*0.97 if direction=="bullish" else price*1.03
        tp=price*1.04 if direction=="bullish" else price*0.96
    risk = abs(entry-sl)
    rr   = abs(tp-entry)/risk if risk>0 else 0
    return MResult(name=name,wins=wins,total=total,wr=wr,
                   entry=entry,sl=sl,tp=tp,rr=rr)

def _print_candidate(rank, c):
    icon = "LONG " if c.direction=="LONG" else "SHORT"
    avg  = c.avg_wr()*100; best = c.best_wr()*100
    print(f"\n{'='*64}")
    print(f"  #{rank}  {icon}  {c.symbol:<14} [{c.tf.upper()}]  {_rank(c.best_wr())}")
    print(f"  avg win: {avg:.1f}%  best: {best:.1f}%  {_bar(avg)}")
    print(f"  Wyckoff: level={_fmt(c.level)}  swept={_fmt(c.swept)}"
          f"  pierce={c.pierce:.2f}%  age={c.age}c")
    print(f"  {'-'*60}")
    print(f"  {'METHOD':<8}  {'WIN%':>6}  {'SIGNALS':>9}  "
          f"{'ENTRY':<12}  {'SL':<12}  {'TP':<12}  RR")
    print(f"  {'-'*60}")
    for m in sorted(c.methods, key=lambda x: x.wr, reverse=True):
        if m.total < MIN_BT_SIGS:
            print(f"  {m.name:<8}  n/a    ({m.total} signals)")
            continue
        star = " <--" if m.wr == c.best_wr() else ""
        print(f"  {m.name:<8}  {m.wr*100:>5.1f}%  "
              f"({m.wins:>3}/{m.total:<3})  "
              f"{_fmt(m.entry):<12}  {_fmt(m.sl):<12}  {_fmt(m.tp):<12}  "
              f"1:{m.rr:.1f}{star}")
    print(f"  {'-'*60}")
    print(f"  FINAL SIGNALS PER METHOD:")
    print(f"  {'-'*60}")
    for m in c.methods:
        wr_tag = f"{m.wr*100:.0f}% wr" if m.total>=MIN_BT_SIGS else "n/a"
        print(f"  {m.name:<8} {icon} {c.symbol:<14}"
              f"  Entry {_fmt(m.entry):<12}"
              f"  SL {_fmt(m.sl):<12}"
              f"  TP {_fmt(m.tp):<12}"
              f"  [{wr_tag}]")
    print(f"{'='*64}")


# ══════════════════════════════════════════════════════════════════════════════
#  SCANNER
# ══════════════════════════════════════════════════════════════════════════════

async def _scan_sym(client, symbol, price, direction, ict_dir):
    best = None
    for tf in SCAN_TFS:
        raw = await client.get_klines(symbol, tf, KLINE_LIMIT)
        if not raw or len(raw) < 50: continue
        found, detail = _wyckoff_spring(raw, ict_dir)
        if not found: continue
        klines = _parse(raw)
        if not klines: continue
        cand = Candidate(symbol=symbol, direction=direction, tf=tf,
                         level=detail["level"], swept=detail["swept"],
                         pierce=detail.get("pierce",0), age=detail.get("age",0))
        for name in METHODS:
            cand.methods.append(_run_method(name, klines, ict_dir, price))
        if best is None or tf == "1d":
            best = cand
    return best


async def main():
    print("""
+============================================================+
|   Wyckoff Pro  --  5-Method Backtest + Per-Method Signal   |
|   RTM | Brooks | Adv PA | ICT | SMC                        |
|   Daily + 4H  --  display only, no orders                  |
+============================================================+
""")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode    = ssl.CERT_NONE
    conn = aiohttp.TCPConnector(ssl=ssl_ctx)

    async with aiohttp.ClientSession(connector=conn) as session:
        client = BitunixClient(API_KEY, SECRET_KEY, session)

        print("  BTC analysis ...", flush=True)
        btc_kl = {tf: await client.get_klines("BTCUSDT", tf, 100)
                  for tf in ("4h","1h","1d")}
        bias = _btc_bias(btc_kl)
        b_tag = "BULL" if bias=="bullish" else ("BEAR" if bias=="bearish" else "NEUT")
        print(f"  BTC -> {b_tag}\n")

        if bias == "neutral":
            dirs = [("LONG","bullish"),("SHORT","bearish")]
            print("  BTC neutral -- scanning both directions\n")
        else:
            d = "LONG" if bias=="bullish" else "SHORT"
            dirs = [(d, "bullish" if d=="LONG" else "bearish")]

        tickers   = await client.get_tickers()
        price_map = {t["symbol"]: float(t["lastPrice"])
                     for t in tickers
                     if t.get("lastPrice") and float(t.get("lastPrice",0))>0}
        symbols = list(price_map.keys())
        print(f"  Scanning {len(symbols)} symbols ...\n", flush=True)

        t0 = time.time()
        found: List[Candidate] = []

        for direction, ict_dir in dirs:
            for i in range(0, len(symbols), BATCH_SIZE):
                batch = symbols[i:i+BATCH_SIZE]
                tasks = [_scan_sym(client, s, price_map[s], direction, ict_dir)
                         for s in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for r in results:
                    if isinstance(r, Candidate): found.append(r)
                print(f"  {i+len(batch)}/{len(symbols)}"
                      f"  candidates: {len(found)}"
                      f"  [{time.time()-t0:.0f}s]", flush=True)

        elapsed = time.time()-t0
        print(f"\n{'='*64}")
        print(f"  Done -- {len(found)} candidates  [{elapsed:.0f}s]")
        print(f"{'='*64}\n")

        if not found:
            print("  No spring/upthrust found.\n")
            return

        found.sort(key=lambda x: x.best_wr(), reverse=True)

        print(f"  {'#':<4} {'SYMBOL':<16} {'DIR':<6} {'TF':<5}"
              f" {'AVG%':<8} {'BEST%':<8} RANK")
        print("  "+"-"*54)
        for i, c in enumerate(found, 1):
            print(f"  #{i:<3} {c.symbol:<16} {c.direction:<6} {c.tf:<5}"
                  f" {c.avg_wr()*100:>5.1f}%   {c.best_wr()*100:>5.1f}%   {_rank(c.best_wr())}")

        print(f"\n  Full analysis -- top {min(SHOW_TOP,len(found))}:")
        for rank, c in enumerate(found[:SHOW_TOP], 1):
            _print_candidate(rank, c)


if __name__ == "__main__":
    asyncio.run(main())
'''

target = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wyckoff_pro.py")
with open(target, "w", encoding="utf-8") as f:
    f.write(CONTENT)

print(f"[OK] wyckoff_pro.py fixed -> {target}")
print("[OK] Standalone -- no bitunix_scanner imports")
print("[OK] Brooks + Adv PA signal generation fixed")
print("")
print("Now run:  python wyckoff_pro.py")
