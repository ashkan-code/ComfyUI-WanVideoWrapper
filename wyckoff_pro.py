#!/usr/bin/env python3
"""
Wyckoff Pro Scanner -- Bitunix Futures
5-method backtest + individual final signal per method.

Flow:
  1. Wyckoff HTF scan (Daily + 4H) -- Spring / Upthrust candidates
  2. Per candidate: 5-method backtest on historical klines
  3. Each method: win rate + its own live Entry/SL/TP

Methods:
  RTM     : Base/Origin/Control  -- SL=Origin     TP=Supply zone
  Brooks  : Trading Range break  -- SL=TR far side TP=Measured move
  Adv PA  : Pin bar at key level -- SL=Wick low    TP=Next swing
  ICT     : OB + FVG retest      -- SL=OB low      TP=Liq pool
  SMC     : BOS + OB pullback    -- SL=OB low      TP=BSL

Run:  python wyckoff_pro.py
"""

import asyncio, math, os, ssl, sys, time
from dataclasses import dataclass, field
from statistics import mean
from typing import List, Optional, Tuple
sys.path.insert(0, os.path.dirname(__file__))

import aiohttp

from bitunix_scanner.client import AsyncBitunixClient
from bitunix_scanner.ict import (
    _parse_klines, _swing_highs, _swing_lows, _atr_vals,
    btc_ict_bias, detect_wyckoff_spring, market_structure,
)
from bitunix_scanner.signals import _fmt

API_KEY    = os.getenv("BITUNIX_API_KEY",    "68f0a1765f124bacb847afa8db78e480")
SECRET_KEY = os.getenv("BITUNIX_SECRET_KEY", "159808597389a1cd1fc429f9f469209b")

SCAN_TFS      = ["1d", "4h"]
KLINE_LIMIT   = 500
BT_FORWARD    = 60       # max bars forward per backtest trade
MIN_BT_SIGS   = 5        # min signals to report win rate
BATCH_SIZE    = 20
SHOW_TOP      = 5
SL_BUFFER     = 0.005    # 0.5% beyond swept point


# ── dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class MethodResult:
    name:      str
    wins:      int
    total:     int
    win_rate:  float          # 0.0 – 1.0
    entry:     float
    sl:        float
    tp:        float
    rr:        float

    def label(self) -> str:
        if self.total < MIN_BT_SIGS:
            return f"  {self.name:<8}: n/a (only {self.total} signals)"
        pct = self.win_rate * 100
        return (f"  {self.name:<8}: {pct:>5.1f}%  ({self.wins}/{self.total})  "
                f"| Entry {_fmt(self.entry)}  SL {_fmt(self.sl)}  "
                f"TP {_fmt(self.tp)}  RR 1:{self.rr:.1f}")


@dataclass
class CandidateResult:
    symbol:    str
    direction: str
    tf:        str
    level:     float
    swept:     float
    pierce:    float
    age:       int
    methods:   List[MethodResult] = field(default_factory=list)

    def best_win_rate(self) -> float:
        r = [m.win_rate for m in self.methods if m.total >= MIN_BT_SIGS]
        return max(r) if r else 0.0

    def avg_win_rate(self) -> float:
        r = [m.win_rate for m in self.methods if m.total >= MIN_BT_SIGS]
        return mean(r) if r else 0.0


# ── helpers ───────────────────────────────────────────────────────────────────

def _bar(s: float) -> str:
    f = round(s / 10)
    return "#" * f + "." * (10 - f)


def _rank(wr: float) -> str:
    if wr >= 0.72: return "ELITE"
    if wr >= 0.60: return "STRONG"
    if wr >= 0.50: return "VALID"
    return "WEAK"


def _atr(klines: list, period: int = 14) -> list:
    return _atr_vals(klines, period)


def _backtest(klines: list,
              signals: List[Tuple[int, float, float, float]],
              direction: str) -> Tuple[int, int]:
    """
    Simulate historical trades.
    signals: [(bar_idx, entry, sl, tp), ...]
    Returns (wins, total).
    """
    wins = 0
    total = 0
    for bar_idx, entry, sl, tp in signals:
        if sl <= 0 or tp <= 0 or entry <= 0:
            continue
        if direction == "bullish" and (sl >= entry or tp <= entry):
            continue
        if direction == "bearish" and (sl <= entry or tp >= entry):
            continue
        resolved = False
        for j in range(bar_idx + 1, min(bar_idx + BT_FORWARD + 1, len(klines))):
            c = klines[j]
            if direction == "bullish":
                if c["high"] >= tp:
                    wins += 1
                    resolved = True
                    break
                if c["low"] <= sl:
                    resolved = True
                    break
            else:
                if c["low"] <= tp:
                    wins += 1
                    resolved = True
                    break
                if c["high"] >= sl:
                    resolved = True
                    break
        if resolved:
            total += 1
    return wins, total


# ── Method 1: RTM ─────────────────────────────────────────────────────────────
# Base (tight range) + Origin (swing extreme) + Control (breakout candle)
# Entry = control candle close  SL = origin  TP = next swing extreme

def _rtm_signals(klines: list, direction: str) -> List[Tuple[int, float, float, float]]:
    sigs = []
    atr  = _atr(klines)
    n    = len(klines)

    for i in range(10, n - 1):
        avg_atr = atr[i]
        if avg_atr is None or avg_atr == 0:
            continue

        # Find base: last 3-6 candles tight range
        base_start = i - 5
        if base_start < 2:
            continue
        base_candles = klines[base_start: i]
        base_hi = max(c["high"]  for c in base_candles)
        base_lo = min(c["low"]   for c in base_candles)
        base_rng = base_hi - base_lo
        if base_rng > avg_atr * 1.2:
            continue  # not tight enough

        c = klines[i]

        if direction == "bullish":
            # Control: closes above base high
            if c["close"] <= base_hi:
                continue
            body = abs(c["close"] - c["open"])
            if body < avg_atr * 0.3:
                continue

            # Origin: swing low before base
            prior = klines[max(0, base_start - 20): base_start]
            if not prior:
                continue
            origin = min(p["low"] for p in prior)
            sl = origin * (1 - SL_BUFFER)

            # TP: nearest swing high after i in history (forward-safe: use recent highs)
            sh = _swing_highs(klines[:i], n=3)
            if not sh:
                continue
            tp_candidates = [klines[j]["high"] for j in sh
                             if klines[j]["high"] > c["close"] * 1.005]
            if not tp_candidates:
                tp = c["close"] * 1.04
            else:
                tp = min(tp_candidates)

            sigs.append((i, c["close"], sl, tp))

        else:  # bearish
            if c["close"] >= base_lo:
                continue
            body = abs(c["close"] - c["open"])
            if body < avg_atr * 0.3:
                continue

            prior = klines[max(0, base_start - 20): base_start]
            if not prior:
                continue
            origin = max(p["high"] for p in prior)
            sl = origin * (1 + SL_BUFFER)

            sl_idxs = _swing_lows(klines[:i], n=3)
            tp_candidates = [klines[j]["low"] for j in sl_idxs
                             if klines[j]["low"] < c["close"] * 0.995]
            tp = max(tp_candidates) if tp_candidates else c["close"] * 0.96

            sigs.append((i, c["close"], sl, tp))

    return sigs


# ── Method 2: Al Brooks ───────────────────────────────────────────────────────
# Trading Range (TR) + breakout close  SL = TR far side  TP = measured move

def _brooks_signals(klines: list, direction: str) -> List[Tuple[int, float, float, float]]:
    sigs = []
    atr  = _atr(klines)
    n    = len(klines)

    for i in range(8, n - 1):
        avg_atr = atr[i]
        if avg_atr is None or avg_atr == 0:
            continue

        # Trading Range: last 4-8 candles overlapping
        tr_len = 6
        tr_start = i - tr_len
        if tr_start < 1:
            continue
        tr_candles = klines[tr_start: i]
        tr_hi = max(c["high"] for c in tr_candles)
        tr_lo = min(c["low"]  for c in tr_candles)
        tr_rng = tr_hi - tr_lo
        if tr_rng > avg_atr * 2.0 or tr_rng < avg_atr * 0.3:
            continue

        c = klines[i]

        if direction == "bullish":
            if c["close"] <= tr_hi:
                continue
            entry = c["close"]
            sl    = tr_lo * (1 - SL_BUFFER * 0.5)
            tp    = entry + tr_rng * 1.5
            sigs.append((i, entry, sl, tp))

        else:
            if c["close"] >= tr_lo:
                continue
            entry = c["close"]
            sl    = tr_hi * (1 + SL_BUFFER * 0.5)
            tp    = entry - tr_rng * 1.5
            sigs.append((i, entry, sl, tp))

    return sigs


# ── Method 3: Advanced Price Action ───────────────────────────────────────────
# Pin bar / hammer at key swing level  SL = wick  TP = next swing

def _adv_pa_signals(klines: list, direction: str) -> List[Tuple[int, float, float, float]]:
    sigs = []
    atr  = _atr(klines)
    n    = len(klines)
    sh   = _swing_highs(klines, n=3)
    sl_i = _swing_lows(klines,  n=3)

    for i in range(10, n - 1):
        avg_atr = atr[i]
        if avg_atr is None or avg_atr == 0:
            continue

        c    = klines[i]
        body = abs(c["close"] - c["open"])
        rng  = c["high"] - c["low"]
        if rng == 0:
            continue

        if direction == "bullish":
            lw = min(c["open"], c["close"]) - c["low"]
            # Pin bar: wick >= 2x body, closes in upper 40% of range
            if lw < body * 2.0 or lw < avg_atr * 0.5:
                continue
            if c["close"] < c["low"] + rng * 0.6:
                continue
            # Must be near a swing low key level
            near_key = any(
                abs(klines[j]["low"] - c["low"]) / c["low"] < 0.008
                for j in sl_i if j < i - 2
            )
            if not near_key:
                continue

            sl = c["low"] * (1 - SL_BUFFER)
            # TP = nearest swing high above
            tp_candidates = [klines[j]["high"] for j in sh
                             if j < i and klines[j]["high"] > c["close"] * 1.005]
            tp = min(tp_candidates) if tp_candidates else c["close"] * 1.04
            sigs.append((i, c["close"], sl, tp))

        else:
            uw = c["high"] - max(c["open"], c["close"])
            if uw < body * 2.0 or uw < avg_atr * 0.5:
                continue
            if c["close"] > c["low"] + rng * 0.4:
                continue
            near_key = any(
                abs(klines[j]["high"] - c["high"]) / c["high"] < 0.008
                for j in sh if j < i - 2
            )
            if not near_key:
                continue

            sl = c["high"] * (1 + SL_BUFFER)
            tp_candidates = [klines[j]["low"] for j in sl_i
                             if j < i and klines[j]["low"] < c["close"] * 0.995]
            tp = max(tp_candidates) if tp_candidates else c["close"] * 0.96
            sigs.append((i, c["close"], sl, tp))

    return sigs


# ── Method 4: ICT ─────────────────────────────────────────────────────────────
# Order Block (last opposing candle before impulse) + FVG retest
# Entry = OB mid  SL = OB far edge  TP = next liquidity pool

def _ict_signals(klines: list, direction: str) -> List[Tuple[int, float, float, float]]:
    sigs = []
    atr  = _atr(klines)
    n    = len(klines)
    sh   = _swing_highs(klines, n=3)
    sl_i = _swing_lows(klines,  n=3)

    for i in range(6, n - 1):
        avg_atr = atr[i]
        if avg_atr is None or avg_atr == 0:
            continue

        c = klines[i]

        if direction == "bullish":
            # OB: bearish candle (close < open) at index i-1 or i-2
            # followed by strong bullish move
            for ob_idx in (i - 1, i - 2):
                if ob_idx < 1:
                    continue
                ob = klines[ob_idx]
                if ob["close"] >= ob["open"]:
                    continue  # not bearish
                # Impulse: current close clearly above OB high
                if c["close"] < ob["high"] * 1.005:
                    continue
                move = c["close"] - ob["close"]
                if move < avg_atr * 0.8:
                    continue

                # FVG check: gap between ob[-2].high and c.low (3-candle)
                if ob_idx >= 1:
                    prev = klines[ob_idx - 1]
                    fvg = c["low"] > prev["high"]  # bullish FVG
                else:
                    fvg = False

                ob_lo  = min(ob["open"], ob["close"])
                ob_hi  = max(ob["open"], ob["close"])
                entry  = (ob_lo + ob_hi) / 2
                sl     = ob_lo * (1 - SL_BUFFER)

                # TP: next swing high above
                tp_cands = [klines[j]["high"] for j in sh
                            if j < i and klines[j]["high"] > entry * 1.005]
                tp = min(tp_cands) if tp_cands else entry * 1.04

                if entry > 0 and sl > 0 and tp > entry:
                    sigs.append((i, entry, sl, tp))
                break

        else:  # bearish
            for ob_idx in (i - 1, i - 2):
                if ob_idx < 1:
                    continue
                ob = klines[ob_idx]
                if ob["close"] <= ob["open"]:
                    continue  # not bullish
                if c["close"] > ob["low"] * 0.995:
                    continue
                move = ob["close"] - c["close"]
                if move < avg_atr * 0.8:
                    continue

                ob_lo  = min(ob["open"], ob["close"])
                ob_hi  = max(ob["open"], ob["close"])
                entry  = (ob_lo + ob_hi) / 2
                sl     = ob_hi * (1 + SL_BUFFER)

                tp_cands = [klines[j]["low"] for j in sl_i
                            if j < i and klines[j]["low"] < entry * 0.995]
                tp = max(tp_cands) if tp_cands else entry * 0.96

                if entry > 0 and sl > 0 and tp < entry:
                    sigs.append((i, entry, sl, tp))
                break

    return sigs


# ── Method 5: SMC ─────────────────────────────────────────────────────────────
# Liquidity sweep (stop hunt) + BOS + OB pullback
# Entry = OB  SL = below sweep  TP = next BSL

def _smc_signals(klines: list, direction: str) -> List[Tuple[int, float, float, float]]:
    sigs = []
    atr  = _atr(klines)
    n    = len(klines)
    sh   = _swing_highs(klines, n=3)
    sl_i = _swing_lows(klines,  n=3)

    for i in range(10, n - 1):
        avg_atr = atr[i]
        if avg_atr is None or avg_atr == 0:
            continue

        c = klines[i]

        if direction == "bullish":
            # Step 1: liquidity sweep — wick below recent equal lows
            recent_lows = [klines[j]["low"] for j in sl_i if j < i - 2 and j >= i - 30]
            if len(recent_lows) < 2:
                continue
            eq_low = min(recent_lows)
            if c["low"] >= eq_low:
                continue  # no sweep
            if c["close"] < eq_low:
                continue  # didn't recover

            # Step 2: BOS check — current close above previous swing high
            recent_sh = [j for j in sh if i - 20 <= j < i]
            if not recent_sh:
                continue
            prev_sh_price = max(klines[j]["high"] for j in recent_sh)
            bos = c["close"] > prev_sh_price

            # Step 3: OB — last bearish candle before this candle
            ob_idx = None
            for k in range(i - 1, max(i - 8, 0), -1):
                if klines[k]["close"] < klines[k]["open"]:
                    ob_idx = k
                    break
            if ob_idx is None:
                continue

            ob = klines[ob_idx]
            ob_lo = min(ob["open"], ob["close"])
            ob_hi = max(ob["open"], ob["close"])

            entry = ob_hi  # pullback to OB top (aggressive entry)
            sl    = c["low"] * (1 - SL_BUFFER)  # below the sweep

            # TP: next BSL (equal highs above)
            tp_cands = [klines[j]["high"] for j in sh
                        if j < i and klines[j]["high"] > entry * 1.008]
            tp = min(tp_cands) if tp_cands else entry * 1.05

            bonus = 2 if bos else 1  # BOS adds weight but not required
            if entry > 0 and sl > 0 and tp > entry:
                sigs.append((i, entry, sl, tp))

        else:  # bearish
            recent_highs = [klines[j]["high"] for j in sh if j < i - 2 and j >= i - 30]
            if len(recent_highs) < 2:
                continue
            eq_high = max(recent_highs)
            if c["high"] <= eq_high:
                continue
            if c["close"] > eq_high:
                continue

            recent_sl = [j for j in sl_i if i - 20 <= j < i]
            if not recent_sl:
                continue
            prev_sl_price = min(klines[j]["low"] for j in recent_sl)
            bos = c["close"] < prev_sl_price

            ob_idx = None
            for k in range(i - 1, max(i - 8, 0), -1):
                if klines[k]["close"] > klines[k]["open"]:
                    ob_idx = k
                    break
            if ob_idx is None:
                continue

            ob = klines[ob_idx]
            ob_lo = min(ob["open"], ob["close"])
            ob_hi = max(ob["open"], ob["close"])

            entry = ob_lo
            sl    = c["high"] * (1 + SL_BUFFER)

            tp_cands = [klines[j]["low"] for j in sl_i
                        if j < i and klines[j]["low"] < entry * 0.992]
            tp = max(tp_cands) if tp_cands else entry * 0.95

            if entry > 0 and sl > 0 and tp < entry:
                sigs.append((i, entry, sl, tp))

    return sigs


# ── Per-method runner ─────────────────────────────────────────────────────────

METHODS = {
    "RTM":    _rtm_signals,
    "Brooks": _brooks_signals,
    "Adv PA": _adv_pa_signals,
    "ICT":    _ict_signals,
    "SMC":    _smc_signals,
}


def _run_method(name: str, klines: list, direction: str,
                current_price: float) -> MethodResult:
    fn   = METHODS[name]
    sigs = fn(klines, direction)

    # backtest on historical signals (exclude last 3 bars = "live")
    hist = [(i, e, s, t) for i, e, s, t in sigs if i < len(klines) - 3]
    wins, total = _backtest(klines, hist, direction)
    wr = wins / total if total > 0 else 0.0

    # live signal: most recent signal
    live = [(i, e, s, t) for i, e, s, t in sigs if i >= len(klines) - 5]
    if live:
        _, entry, sl, tp = live[-1]
    else:
        # fallback: use current price with last historical SL/TP ratio
        if hist:
            _, he, hs, ht = hist[-1]
            ratio_sl = abs(he - hs) / he if he > 0 else 0.02
            ratio_tp = abs(ht - he) / he if he > 0 else 0.04
            if direction == "bullish":
                entry = current_price
                sl    = current_price * (1 - ratio_sl)
                tp    = current_price * (1 + ratio_tp)
            else:
                entry = current_price
                sl    = current_price * (1 + ratio_sl)
                tp    = current_price * (1 - ratio_tp)
        else:
            entry = current_price
            sl    = current_price * (0.97 if direction == "bullish" else 1.03)
            tp    = current_price * (1.04 if direction == "bullish" else 0.96)

    risk = abs(entry - sl)
    rr   = abs(tp - entry) / risk if risk > 0 else 0.0

    return MethodResult(
        name=name, wins=wins, total=total, win_rate=wr,
        entry=entry, sl=sl, tp=tp, rr=rr,
    )


# ── Wyckoff HTF scan ──────────────────────────────────────────────────────────

async def _scan_symbol(client: AsyncBitunixClient,
                       symbol: str, price: float,
                       direction: str, ict_dir: str) -> Optional[CandidateResult]:
    best: Optional[CandidateResult] = None

    for tf in SCAN_TFS:
        raw = await client.get_klines(symbol, tf, KLINE_LIMIT)
        if not raw or len(raw) < 50:
            continue

        found, detail = detect_wyckoff_spring(
            raw, ict_dir,
            lookback   = KLINE_LIMIT,
            equal_tol  = 0.005,
            min_pierce = 0.002,
            wick_ratio = 2.0,
            max_age    = 6,
            min_gap    = 4,
        )
        if not found:
            continue

        klines = _parse_klines(raw)
        if not klines:
            continue

        candidate = CandidateResult(
            symbol    = symbol,
            direction = direction,
            tf        = tf,
            level     = detail["level"],
            swept     = detail["swept"],
            pierce    = detail.get("pierce", 0),
            age       = detail.get("age", 0),
        )

        # run 5 method backtests
        for name in METHODS:
            mr = _run_method(name, klines, ict_dir, price)
            candidate.methods.append(mr)

        # keep best TF (prefer daily over 4h)
        if best is None or tf == "1d":
            best = candidate

    return best


# ── Display ───────────────────────────────────────────────────────────────────

def _fmt_candidate(rank: int, c: CandidateResult) -> str:
    icon  = "LONG " if c.direction == "LONG" else "SHORT"
    avg   = c.avg_win_rate() * 100
    best  = c.best_win_rate() * 100
    rnk   = _rank(c.best_win_rate())
    bar   = _bar(avg)

    lines = [
        "",
        "=" * 62,
        f"  #{rank}  {icon}  {c.symbol:<14}  [{c.tf.upper()}]  {rnk}",
        f"  avg win: {avg:.1f}%  best: {best:.1f}%  {bar}",
        f"  Wyckoff level: {_fmt(c.level)}  swept: {_fmt(c.swept)}"
        f"  pierce: {c.pierce:.2f}%  age: {c.age}c",
        "-" * 62,
        "  METHOD    WIN RATE          ENTRY         SL            TP         RR",
        "-" * 62,
    ]

    for m in sorted(c.methods, key=lambda x: x.win_rate, reverse=True):
        if m.total < MIN_BT_SIGS:
            lines.append(f"  {m.name:<8}  n/a ({m.total} signals)")
            continue
        pct  = m.win_rate * 100
        star = " <-- BEST" if m.win_rate == c.best_win_rate() else ""
        lines.append(
            f"  {m.name:<8}  {pct:>5.1f}% ({m.wins:>3}/{m.total:<3})"
            f"  {_fmt(m.entry):<12}  {_fmt(m.sl):<12}  {_fmt(m.tp):<12}  1:{m.rr:.1f}{star}"
        )

    lines += [
        "-" * 62,
        "  FINAL SIGNALS PER METHOD:",
        "-" * 62,
    ]

    for m in c.methods:
        dir_tag = "LONG " if c.direction == "LONG" else "SHORT"
        wr_tag  = f"{m.win_rate*100:.0f}% wr" if m.total >= MIN_BT_SIGS else "n/a"
        lines.append(
            f"  {m.name:<8} {dir_tag} {c.symbol}"
            f"  Entry {_fmt(m.entry)}"
            f"  SL {_fmt(m.sl)}"
            f"  TP {_fmt(m.tp)}"
            f"  [{wr_tag}]"
        )

    lines.append("=" * 62)
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    print("""
+============================================================+
|   Wyckoff Pro -- 5-Method Backtest + Per-Method Signal     |
|   Methods: RTM | Brooks | Adv PA | ICT | SMC               |
|   Scan: Daily + 4H -- display only, no orders              |
+============================================================+
""")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode    = ssl.CERT_NONE
    conn = aiohttp.TCPConnector(ssl=ssl_ctx)

    async with aiohttp.ClientSession(connector=conn) as session:
        client = AsyncBitunixClient(API_KEY, SECRET_KEY, session)

        # BTC bias
        print("  BTC analysis ...", flush=True)
        btc_kl = {tf: await client.get_klines("BTCUSDT", tf, 100)
                  for tf in ("4h", "1h", "1d")}
        btc_bias, btc_detail = btc_ict_bias(btc_kl)
        b_tag = "BULL" if btc_bias=="bullish" else ("BEAR" if btc_bias=="bearish" else "NEUT")
        print(f"  BTC -> {b_tag}  {btc_detail}\n")

        if btc_bias == "neutral":
            dirs = [("LONG", "bullish"), ("SHORT", "bearish")]
            print("  BTC neutral -- scanning both directions\n")
        else:
            direction = "LONG" if btc_bias == "bullish" else "SHORT"
            dirs = [(direction, "bullish" if direction == "LONG" else "bearish")]

        # symbols
        tickers   = await client.get_all_tickers()
        price_map = {t["symbol"]: float(t["lastPrice"])
                     for t in tickers
                     if t.get("lastPrice") and float(t.get("lastPrice", 0)) > 0}
        symbols   = list(price_map.keys())
        print(f"  Scanning {len(symbols)} symbols x {len(SCAN_TFS)} TFs ...\n", flush=True)

        t0    = time.time()
        found: List[CandidateResult] = []

        for direction, ict_dir in dirs:
            for i in range(0, len(symbols), BATCH_SIZE):
                batch = symbols[i: i + BATCH_SIZE]
                tasks = [
                    _scan_symbol(client, sym, price_map[sym], direction, ict_dir)
                    for sym in batch
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for r in results:
                    if isinstance(r, CandidateResult):
                        found.append(r)
                done = i + len(batch)
                print(f"  {done}/{len(symbols)}  candidates: {len(found)}"
                      f"  [{time.time()-t0:.0f}s]", flush=True)

        elapsed = time.time() - t0
        print(f"\n{'='*62}")
        print(f"  Done -- {len(found)} candidates  [{elapsed:.0f}s]")
        print(f"{'='*62}\n")

        if not found:
            print("  No Wyckoff spring/upthrust found.\n")
            return

        found.sort(key=lambda x: x.best_win_rate(), reverse=True)

        # summary table
        print(f"\n  {'#':<4} {'symbol':<16} {'dir':<6} {'tf':<5}"
              f" {'avg%':<8} {'best%':<8} {'rank'}")
        print("  " + "-"*52)
        for i, c in enumerate(found, 1):
            print(f"  #{i:<3} {c.symbol:<16} {c.direction:<6} {c.tf:<5}"
                  f" {c.avg_win_rate()*100:>5.1f}%   {c.best_win_rate()*100:>5.1f}%   {_rank(c.best_win_rate())}")

        print(f"\n{'='*62}")
        print(f"  Full analysis -- top {min(SHOW_TOP, len(found))}:")
        print(f"{'='*62}")

        for rank, c in enumerate(found[:SHOW_TOP], 1):
            print(_fmt_candidate(rank, c))


if __name__ == "__main__":
    asyncio.run(main())
