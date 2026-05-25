"""ICT concepts: Order Block detection, market structure analysis."""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

TF_WEIGHT = {"1m": 1, "5m": 2, "15m": 3, "1h": 4, "4h": 5, "1d": 6}


@dataclass
class OrderBlock:
    ob_type: str        # 'bullish' | 'bearish'
    ob_high: float      # body top
    ob_low: float       # body bottom
    wick_high: float    # full candle high
    wick_low: float     # full candle low
    timeframe: str
    bar_index: int
    timestamp: int

    @property
    def mid(self) -> float:
        return (self.ob_high + self.ob_low) / 2

    @property
    def size(self) -> float:
        return self.ob_high - self.ob_low

    def weight(self) -> int:
        return TF_WEIGHT.get(self.timeframe, 1)


@dataclass
class ConfluentZone:
    zone_type: str          # 'bullish' | 'bearish'
    price_high: float
    price_low: float
    timeframes: List[str]
    score: int              # sum of TF weights
    obs: List[OrderBlock] = field(default_factory=list)

    @property
    def mid(self) -> float:
        return (self.price_high + self.price_low) / 2

    @property
    def tf_count(self) -> int:
        return len(set(self.timeframes))


def _klines_to_df(raw: list) -> pd.DataFrame:
    if not raw:
        return pd.DataFrame()
    df = pd.DataFrame(raw)
    for col in ("open", "high", "low", "close", "quoteVol", "baseVol"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["time"] = pd.to_numeric(df["time"], errors="coerce")
    df.sort_values("time", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _swing_highs(df: pd.DataFrame, n: int = 3) -> List[int]:
    idxs = []
    for i in range(n, len(df) - n):
        window = df["high"].iloc[i - n: i + n + 1]
        if df["high"].iloc[i] == window.max():
            idxs.append(i)
    return idxs


def _swing_lows(df: pd.DataFrame, n: int = 3) -> List[int]:
    idxs = []
    for i in range(n, len(df) - n):
        window = df["low"].iloc[i - n: i + n + 1]
        if df["low"].iloc[i] == window.min():
            idxs.append(i)
    return idxs


def detect_order_blocks(raw: list, timeframe: str,
                        max_obs: int = 6,
                        proximity_pct: float = 0.04) -> List[OrderBlock]:
    """
    Detect unmitigated ICT Order Blocks near current price.

    Bullish OB: last bearish candle before a bullish Break-of-Structure (BOS).
    Bearish OB: last bullish candle before a bearish BOS.

    Only returns OBs within `proximity_pct` (4%) of current price
    so they are actionable.
    """
    df = _klines_to_df(raw)
    if len(df) < 30:
        return []

    atr = _atr(df)
    sh = _swing_highs(df, n=3)
    sl = _swing_lows(df, n=3)
    current_price = df["close"].iloc[-1]
    obs: List[OrderBlock] = []

    for i in range(5, len(df) - 5):
        c = df.iloc[i]
        avg_atr = atr.iloc[i]
        if pd.isna(avg_atr) or avg_atr == 0:
            continue

        lookahead = df.iloc[i + 1: i + 6]
        if lookahead.empty:
            continue

        # ── Bullish OB ────────────────────────────────────────────────────
        if c["close"] < c["open"]:
            # displacement: next candles break above a recent swing high
            prev_sh = [j for j in sh if j < i]
            if prev_sh:
                last_sh_price = df["high"].iloc[prev_sh[-1]]
                move_up = lookahead["high"].max() - c["close"]
                if (lookahead["high"].max() > last_sh_price
                        and move_up >= avg_atr * 1.2):
                    ob_high = max(c["open"], c["close"])
                    ob_low = min(c["open"], c["close"])
                    # Unmitigated: no close below ob_low after displacement
                    post = df.iloc[i + 1:]
                    if post["close"].min() > ob_low * 0.998:
                        obs.append(OrderBlock(
                            ob_type="bullish",
                            ob_high=ob_high,
                            ob_low=ob_low,
                            wick_high=c["high"],
                            wick_low=c["low"],
                            timeframe=timeframe,
                            bar_index=i,
                            timestamp=int(c["time"]),
                        ))

        # ── Bearish OB ────────────────────────────────────────────────────
        elif c["close"] > c["open"]:
            prev_sl = [j for j in sl if j < i]
            if prev_sl:
                last_sl_price = df["low"].iloc[prev_sl[-1]]
                move_dn = c["close"] - lookahead["low"].min()
                if (lookahead["low"].min() < last_sl_price
                        and move_dn >= avg_atr * 1.2):
                    ob_high = max(c["open"], c["close"])
                    ob_low = min(c["open"], c["close"])
                    post = df.iloc[i + 1:]
                    if post["close"].max() < ob_high * 1.002:
                        obs.append(OrderBlock(
                            ob_type="bearish",
                            ob_high=ob_high,
                            ob_low=ob_low,
                            wick_high=c["high"],
                            wick_low=c["low"],
                            timeframe=timeframe,
                            bar_index=i,
                            timestamp=int(c["time"]),
                        ))

    # Keep most recent, filter by proximity to current price
    by_type: dict = {"bullish": [], "bearish": []}
    for ob in obs:
        by_type[ob.ob_type].append(ob)

    result = []
    for ob_type, items in by_type.items():
        recent = sorted(items, key=lambda x: x.bar_index, reverse=True)
        for ob in recent[:max_obs]:
            dist = abs(current_price - ob.mid) / current_price
            if dist <= proximity_pct:
                result.append(ob)

    return result


def find_confluence(tf_obs: dict,
                    overlap_tol: float = 0.008,
                    min_tfs: int = 3) -> List[ConfluentZone]:
    """
    Group OBs from different timeframes that overlap in price.
    Returns zones backed by at least `min_tfs` distinct timeframes,
    sorted by score descending.
    """
    all_obs: List[OrderBlock] = []
    for obs in tf_obs.values():
        all_obs.extend(obs)

    if not all_obs:
        return []

    zones: List[ConfluentZone] = []
    used = set()

    for i, ob1 in enumerate(all_obs):
        if i in used:
            continue
        group = [ob1]
        used.add(i)
        for j, ob2 in enumerate(all_obs):
            if j in used or ob1.ob_type != ob2.ob_type:
                continue
            # Overlap check: zones intersect considering tolerance
            tol1 = ob1.mid * overlap_tol
            tol2 = ob2.mid * overlap_tol
            tol = max(tol1, tol2)
            if ob1.ob_low - tol <= ob2.ob_high and ob2.ob_low - tol <= ob1.ob_high:
                group.append(ob2)
                used.add(j)

        tfs = list({ob.timeframe for ob in group})
        if len(tfs) < min_tfs:
            continue

        score = sum(TF_WEIGHT.get(tf, 1) for tf in tfs)
        zones.append(ConfluentZone(
            zone_type=ob1.ob_type,
            price_high=max(ob.ob_high for ob in group),
            price_low=min(ob.ob_low for ob in group),
            timeframes=sorted(tfs, key=lambda t: TF_WEIGHT.get(t, 0)),
            score=score,
            obs=group,
        ))

    return sorted(zones, key=lambda z: z.score, reverse=True)


def market_structure(raw: list, lookback: int = 50) -> str:
    """
    Simple swing-based market structure: 'bullish', 'bearish', or 'neutral'.
    """
    df = _klines_to_df(raw)
    if len(df) < lookback:
        return "neutral"
    df = df.tail(lookback).reset_index(drop=True)
    sh = _swing_highs(df, n=3)
    sl = _swing_lows(df, n=3)
    if len(sh) >= 2 and len(sl) >= 2:
        hh = df["high"].iloc[sh[-1]] > df["high"].iloc[sh[-2]]
        hl = df["low"].iloc[sl[-1]] > df["low"].iloc[sl[-2]]
        lh = df["high"].iloc[sh[-1]] < df["high"].iloc[sh[-2]]
        ll = df["low"].iloc[sl[-1]] < df["low"].iloc[sl[-2]]
        if hh and hl:
            return "bullish"
        if lh and ll:
            return "bearish"
    return "neutral"


def detect_fvg(raw: list, direction: str) -> List[Tuple[float, float]]:
    """
    Detect Fair Value Gaps (imbalances) in `direction` ('bullish'|'bearish').

    Bearish FVG (price dropped fast, gap sits below A):
        A.low > C.high  → zone = (C.high, A.low)   ← TP target for SHORT trades
    Bullish FVG (price rose fast, gap sits above A):
        A.high < C.low  → zone = (A.high, C.low)   ← TP target for LONG trades

    Returns list of (fvg_low, fvg_high) tuples, newest first.
    """
    df = _klines_to_df(raw)
    fvgs: List[Tuple[float, float]] = []
    for i in range(2, len(df)):
        a = df.iloc[i - 2]
        c = df.iloc[i]
        if direction == "bearish" and a["low"] > c["high"]:
            fvgs.append((float(c["high"]), float(a["low"])))
        elif direction == "bullish" and a["high"] < c["low"]:
            fvgs.append((float(a["high"]), float(c["low"])))
    return list(reversed(fvgs))


def find_liquidity_pools(raw: list, direction: str,
                         entry: float, equal_tol: float = 0.003
                         ) -> List[Tuple[float, str]]:
    """
    Find ICT liquidity pools in the trade direction:

    SHORT → targets BELOW entry:
        • Swing lows (sell-side liquidity)
        • Equal lows (engineered liquidity — within equal_tol %)

    LONG  → targets ABOVE entry:
        • Swing highs (buy-side liquidity)
        • Equal highs

    Returns list of (price, label) sorted nearest-to-entry first.
    """
    df = _klines_to_df(raw)
    candidates: List[Tuple[float, str]] = []

    if direction == "bearish":   # SHORT — look below
        for idx in _swing_lows(df, n=3):
            p = float(df["low"].iloc[idx])
            if p < entry * 0.9995:
                candidates.append((p, "Swing Low"))
        # Equal lows: last 40 bars
        recent = [float(df["low"].iloc[i]) for i in range(max(0, len(df)-40), len(df))
                  if float(df["low"].iloc[i]) < entry * 0.9995]
        seen: List[float] = []
        for p in recent:
            if any(abs(p - s) / s <= equal_tol for s in seen):
                candidates.append((p, "Equal Lows"))
            seen.append(p)
    else:                        # LONG — look above
        for idx in _swing_highs(df, n=3):
            p = float(df["high"].iloc[idx])
            if p > entry * 1.0005:
                candidates.append((p, "Swing High"))
        recent = [float(df["high"].iloc[i]) for i in range(max(0, len(df)-40), len(df))
                  if float(df["high"].iloc[i]) > entry * 1.0005]
        seen = []
        for p in recent:
            if any(abs(p - s) / s <= equal_tol for s in seen):
                candidates.append((p, "Equal Highs"))
            seen.append(p)

    # Sort: nearest to entry first
    if direction == "bearish":
        candidates.sort(key=lambda x: x[0], reverse=True)   # highest below entry first
    else:
        candidates.sort(key=lambda x: x[0])                 # lowest above entry first
    return candidates


def find_ict_tp(klines_1h: list, klines_4h: list,
                entry: float, direction: str, sl: float,
                min_rr: float = 1.5) -> Tuple[float, str]:
    """
    ICT take-profit detection.

    Priority:
      1. Nearest bearish/bullish FVG in trade direction (1h then 4h)
      2. Nearest swing low/high or equal lows/highs (1h)
      3. Fallback: 2:1 R:R

    All candidates filtered by min_rr; nearest valid target wins.
    """
    risk = abs(entry - sl)
    if risk == 0:
        return (entry * 0.98 if direction == "bearish" else entry * 1.02), "2:1 R:R"

    fvg_dir = "bearish" if direction == "bearish" else "bullish"
    candidates: List[Tuple[float, str]] = []

    # ── 1. FVG targets ────────────────────────────────────────────────────
    for tf_label, raw in (("1h", klines_1h), ("4h", klines_4h)):
        for flo, fhi in detect_fvg(raw, fvg_dir)[:6]:
            mid = (flo + fhi) / 2
            if direction == "bearish" and mid < entry * 0.9995:
                candidates.append((mid, f"FVG {tf_label} [{flo:.6g}–{fhi:.6g}]"))
            elif direction == "bullish" and mid > entry * 1.0005:
                candidates.append((mid, f"FVG {tf_label} [{flo:.6g}–{fhi:.6g}]"))

    # ── 2. Liquidity pools ────────────────────────────────────────────────
    for price, label in find_liquidity_pools(klines_1h, fvg_dir, entry)[:6]:
        candidates.append((price, f"{label} 1h"))

    # ── 3. Filter by min R:R ──────────────────────────────────────────────
    valid: List[Tuple[float, str]] = []
    for tp, reason in candidates:
        rr = abs(tp - entry) / risk
        if direction == "bearish" and tp < entry and rr >= min_rr:
            valid.append((tp, reason))
        elif direction == "bullish" and tp > entry and rr >= min_rr:
            valid.append((tp, reason))

    if not valid:
        fallback = (entry - risk * 2.0) if direction == "bearish" else (entry + risk * 2.0)
        return fallback, "2:1 R:R (no ICT target)"

    # Return nearest valid target (best achievable, closest to entry)
    if direction == "bearish":
        return max(valid, key=lambda x: x[0])   # highest price below entry
    else:
        return min(valid, key=lambda x: x[0])   # lowest price above entry


def find_impulse_for_ote(raw: list, direction: str,
                         lookback: int = 50) -> Tuple[float, float]:
    """
    Find the most recent impulse swing (low, high) for OTE Fibonacci.
    Returns (swing_low, swing_high).
    """
    df = _klines_to_df(raw)
    if len(df) < 10:
        lo = float(df["low"].min()) if len(df) else 0.0
        hi = float(df["high"].max()) if len(df) else 0.0
        return lo, hi

    recent = df.tail(lookback).reset_index(drop=True)
    sh = _swing_highs(recent, n=2)
    sl = _swing_lows(recent, n=2)

    if direction == "bullish":
        for si in reversed(sl):
            later_sh = [j for j in sh if j > si]
            if later_sh:
                return float(recent["low"].iloc[si]), float(recent["high"].iloc[later_sh[0]])
    else:
        for si in reversed(sh):
            later_sl = [j for j in sl if j > si]
            if later_sl:
                return float(recent["low"].iloc[later_sl[0]]), float(recent["high"].iloc[si])

    return float(recent["low"].min()), float(recent["high"].max())


def find_ote_zone(swing_low: float, swing_high: float,
                  direction: str) -> Tuple[float, float]:
    """
    OTE (Optimal Trade Entry) = 61.8%–79% Fibonacci retracement.

    Bullish (retracing down after impulse up):
        OTE low  = high - range * 0.79
        OTE high = high - range * 0.618
    Bearish (retracing up after impulse down):
        OTE low  = low + range * 0.618
        OTE high = low + range * 0.79
    """
    diff = swing_high - swing_low
    if direction == "bullish":
        return swing_high - diff * 0.79, swing_high - diff * 0.618
    else:
        return swing_low + diff * 0.618, swing_low + diff * 0.79


def detect_liquidity_sweep(raw: list, direction: str) -> Tuple[bool, str]:
    """
    Detect a liquidity sweep: a wick beyond a swing level that closes back inside.

    Bullish (LONG): SSL sweep — wick below a swing low, close above it.
    Bearish (SHORT): BSL sweep — wick above a swing high, close below it.
    """
    df = _klines_to_df(raw)
    if len(df) < 15:
        return False, ""

    recent = df.tail(30).reset_index(drop=True)
    n = len(recent)

    if direction == "bullish":
        sl_idxs = _swing_lows(recent.iloc[: n - 2].reset_index(drop=True), n=2)
        for si in reversed(sl_idxs[-4:]):
            level = float(recent["low"].iloc[si])
            for j in range(si + 1, n):
                c = recent.iloc[j]
                if float(c["low"]) < level and float(c["close"]) > level:
                    return True, f"SSL swept {level:.6g}"
    else:
        sh_idxs = _swing_highs(recent.iloc[: n - 2].reset_index(drop=True), n=2)
        for si in reversed(sh_idxs[-4:]):
            level = float(recent["high"].iloc[si])
            for j in range(si + 1, n):
                c = recent.iloc[j]
                if float(c["high"]) > level and float(c["close"]) < level:
                    return True, f"BSL swept {level:.6g}"

    return False, ""


def detect_mss_bos_ltf(raw_5m: list, raw_15m: list,
                        direction: str) -> Tuple[bool, str]:
    """
    Detect Market Structure Shift (MSS) or Break of Structure (BOS) on LTF.
    Checks 15m first, then 5m.
    """
    for tf_label, raw in (("15m", raw_15m), ("5m", raw_5m)):
        df = _klines_to_df(raw)
        if len(df) < 20:
            continue
        recent = df.tail(40).reset_index(drop=True)
        sh = _swing_highs(recent, n=2)
        sl = _swing_lows(recent, n=2)
        last_close = float(recent["close"].iloc[-1])

        if direction == "bullish" and len(sh) >= 2:
            prev_sh_price = float(recent["high"].iloc[sh[-2]])
            if last_close > prev_sh_price:
                tag = "BOS" if float(recent["high"].iloc[sh[-1]]) > prev_sh_price else "MSS"
                return True, f"{tag} {tf_label}"
        elif direction == "bearish" and len(sl) >= 2:
            prev_sl_price = float(recent["low"].iloc[sl[-2]])
            if last_close < prev_sl_price:
                tag = "BOS" if float(recent["low"].iloc[sl[-1]]) < prev_sl_price else "MSS"
                return True, f"{tag} {tf_label}"

    return False, ""


def find_tiered_tp(klines_1h: list, klines_4h: list,
                   entry: float, direction: str, sl: float,
                   min_rr: float = 2.0) -> Tuple[float, float, str, str]:
    """
    TP1: nearest liquidity pool on 1h (min 2:1 R:R).
    TP2: HTF FVG on 4h or 1h (min 3:1 R:R).
    Returns (tp1, tp2, tp1_reason, tp2_reason).
    """
    risk = abs(entry - sl)
    if risk == 0:
        risk = entry * 0.01

    fvg_dir = direction
    tp1: Optional[float] = None
    tp1_reason = ""
    tp2: Optional[float] = None
    tp2_reason = ""

    # TP1: nearest liquidity pool on 1h (min 2:1)
    for price, label in find_liquidity_pools(klines_1h, fvg_dir, entry)[:10]:
        rr = abs(price - entry) / risk
        if rr < min_rr:
            continue
        if direction == "bearish" and price < entry:
            if tp1 is None or price > tp1:
                tp1, tp1_reason = price, f"{label} 1h [1:{rr:.1f}]"
        elif direction == "bullish" and price > entry:
            if tp1 is None or price < tp1:
                tp1, tp1_reason = price, f"{label} 1h [1:{rr:.1f}]"

    # TP2: FVG on 4h then 1h (min 3:1)
    for tf_label, raw in (("4h", klines_4h), ("1h", klines_1h)):
        for flo, fhi in detect_fvg(raw, fvg_dir)[:8]:
            mid = (flo + fhi) / 2
            rr = abs(mid - entry) / risk
            if rr < min_rr * 1.5:
                continue
            if direction == "bearish" and mid < entry:
                if tp2 is None or mid < tp2:
                    tp2, tp2_reason = mid, f"FVG {tf_label} [1:{rr:.1f}]"
            elif direction == "bullish" and mid > entry:
                if tp2 is None or mid > tp2:
                    tp2, tp2_reason = mid, f"FVG {tf_label} [1:{rr:.1f}]"

    if tp1 is None:
        tp1 = entry - risk * min_rr if direction == "bearish" else entry + risk * min_rr
        tp1_reason = "2:1 fallback"

    if tp2 is None:
        tp2 = entry - risk * min_rr * 2 if direction == "bearish" else entry + risk * min_rr * 2
        tp2_reason = "4:1 fallback"

    # Ensure TP2 is farther than TP1
    if direction == "bearish" and tp2 > tp1:
        tp2 = entry - risk * min_rr * 2
        tp2_reason = "4:1 adjusted"
    elif direction == "bullish" and tp2 < tp1:
        tp2 = entry + risk * min_rr * 2
        tp2_reason = "4:1 adjusted"

    return tp1, tp2, tp1_reason, tp2_reason


def detect_breaker_block(raw: list, timeframe: str,
                          max_bb: int = 4) -> List[OrderBlock]:
    """
    Breaker Block: a former OB that price traded through (mitigated),
    now acting as opposite-direction support/resistance.

    Former bullish OB → breaker bearish (now resistance).
    Former bearish OB → breaker bullish (now support).
    Returns OrderBlock objects with ob_type = 'bearish_breaker' or 'bullish_breaker'.
    """
    df = _klines_to_df(raw)
    if len(df) < 40:
        return []

    atr   = _atr(df)
    sh    = _swing_highs(df, n=3)
    sl    = _swing_lows(df, n=3)
    cur   = float(df["close"].iloc[-1])
    result: List[OrderBlock] = []

    for i in range(5, len(df) - 10):
        c      = df.iloc[i]
        avg_atr = atr.iloc[i]
        if pd.isna(avg_atr) or avg_atr == 0:
            continue

        lookahead = df.iloc[i + 1: i + 6]
        if lookahead.empty:
            continue

        ob_high = max(float(c["open"]), float(c["close"]))
        ob_low  = min(float(c["open"]), float(c["close"]))

        # Was this a bullish OB (bearish candle before upward BOS) now mitigated?
        if float(c["close"]) < float(c["open"]):
            prev_sh = [j for j in sh if j < i]
            if prev_sh:
                last_sh_price = float(df["high"].iloc[prev_sh[-1]])
                move_up = lookahead["high"].max() - float(c["close"])
                if lookahead["high"].max() > last_sh_price and move_up >= avg_atr * 1.2:
                    # Now check if price later traded back through the OB (mitigation)
                    post = df.iloc[i + 1:]
                    if post["close"].min() <= ob_low * 1.002:
                        # Mitigated → becomes bearish breaker
                        dist = abs(cur - (ob_high + ob_low) / 2) / cur
                        if dist <= 0.04:
                            result.append(OrderBlock(
                                ob_type="bearish_breaker",
                                ob_high=ob_high, ob_low=ob_low,
                                wick_high=float(c["high"]), wick_low=float(c["low"]),
                                timeframe=timeframe, bar_index=i,
                                timestamp=int(c["time"]),
                            ))

        # Was this a bearish OB (bullish candle before downward BOS) now mitigated?
        elif float(c["close"]) > float(c["open"]):
            prev_sl = [j for j in sl if j < i]
            if prev_sl:
                last_sl_price = float(df["low"].iloc[prev_sl[-1]])
                move_dn = float(c["close"]) - lookahead["low"].min()
                if lookahead["low"].min() < last_sl_price and move_dn >= avg_atr * 1.2:
                    post = df.iloc[i + 1:]
                    if post["close"].max() >= ob_high * 0.998:
                        # Mitigated → becomes bullish breaker
                        dist = abs(cur - (ob_high + ob_low) / 2) / cur
                        if dist <= 0.04:
                            result.append(OrderBlock(
                                ob_type="bullish_breaker",
                                ob_high=ob_high, ob_low=ob_low,
                                wick_high=float(c["high"]), wick_low=float(c["low"]),
                                timeframe=timeframe, bar_index=i,
                                timestamp=int(c["time"]),
                            ))

    recent = sorted(result, key=lambda x: x.bar_index, reverse=True)
    return recent[:max_bb]


def detect_mitigation_block(raw: list, timeframe: str,
                              direction: str) -> Optional[OrderBlock]:
    """
    Mitigation Block: the most recent unmitigated OB that price is
    currently returning to (within 0.5% of its zone).

    direction: 'bullish' (price returning to bullish OB from above)
               'bearish' (price returning to bearish OB from below)
    """
    obs = detect_order_blocks(raw, timeframe, max_obs=8, proximity_pct=0.05)
    df  = _klines_to_df(raw)
    if df.empty:
        return None
    cur = float(df["close"].iloc[-1])

    for ob in sorted(obs, key=lambda x: x.bar_index, reverse=True):
        if ob.ob_type != direction:
            continue
        mid  = (ob.ob_high + ob.ob_low) / 2
        dist = abs(cur - mid) / cur
        if dist <= 0.005:
            return ob
    return None


def detect_candle_confirmation(raw: list, direction: str) -> Tuple[bool, str]:
    """
    Check for an ICT-grade candlestick confirmation on the last CLOSED candle.

    LONG  (bullish): Bullish Engulfing | Hammer | Bullish Pin Bar
    SHORT (bearish): Bearish Engulfing | Shooting Star | Bearish Pin Bar
    Returns (confirmed, pattern_name).
    """
    df = _klines_to_df(raw)
    if len(df) < 3:
        return False, ""

    # Use the last two closed candles
    prev = df.iloc[-3]
    last = df.iloc[-2]

    o1, h1, l1, c1 = float(prev["open"]), float(prev["high"]), float(prev["low"]), float(prev["close"])
    o2, h2, l2, c2 = float(last["open"]), float(last["high"]), float(last["low"]), float(last["close"])

    body2 = abs(c2 - o2)
    body1 = abs(c1 - o1)
    uw2   = h2 - max(o2, c2)  # upper wick
    lw2   = min(o2, c2) - l2  # lower wick
    rng2  = h2 - l2

    if rng2 == 0:
        return False, ""

    if direction == "bullish":
        # 1. Bullish Engulfing
        if (c2 > o2 and body2 > 0
                and o2 <= min(o1, c1)
                and c2 >= max(o1, c1)
                and body2 >= body1 * 0.75):
            return True, "Bullish Engulfing"

        # 2. Hammer (lower wick ≥ 2× body, close in upper 40% of range)
        if (body2 > 0
                and lw2 >= body2 * 2.0
                and c2 >= l2 + rng2 * 0.6):
            return True, "Hammer"

        # 3. Bullish Pin Bar (lower wick ≥ 60% of total range)
        if lw2 >= rng2 * 0.6 and c2 > o2:
            return True, "Bullish Pin Bar"

    else:  # bearish
        # 1. Bearish Engulfing
        if (c2 < o2 and body2 > 0
                and o2 >= max(o1, c1)
                and c2 <= min(o1, c1)
                and body2 >= body1 * 0.75):
            return True, "Bearish Engulfing"

        # 2. Shooting Star (upper wick ≥ 2× body, close in lower 40% of range)
        if (body2 > 0
                and uw2 >= body2 * 2.0
                and c2 <= l2 + rng2 * 0.4):
            return True, "Shooting Star"

        # 3. Bearish Pin Bar (upper wick ≥ 60% of total range)
        if uw2 >= rng2 * 0.6 and c2 < o2:
            return True, "Bearish Pin Bar"

    return False, ""


def btc_ict_bias(tf_klines: dict) -> Tuple[str, str]:
    """
    Determine BTC bias using ICT multi-TF market structure.
    Returns (bias, description) where bias is 'bullish'|'bearish'|'neutral'.
    """
    scores = {"bullish": 0, "bearish": 0}
    details = []

    priority = [("1d", 3), ("4h", 2), ("1h", 1)]
    for tf, weight in priority:
        if tf not in tf_klines or not tf_klines[tf]:
            continue
        ms = market_structure(tf_klines[tf])
        details.append(f"{tf}:{ms[0].upper()}")
        if ms in ("bullish", "bearish"):
            scores[ms] += weight

    if scores["bullish"] > scores["bearish"]:
        return "bullish", " | ".join(details)
    if scores["bearish"] > scores["bullish"]:
        return "bearish", " | ".join(details)
    return "neutral", " | ".join(details)
