"""ICT concepts: Order Block detection, market structure analysis. Pure Python — no numpy/pandas."""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

TF_WEIGHT = {"1m": 1, "5m": 2, "15m": 3, "1h": 4, "4h": 5, "1d": 6}


@dataclass
class OrderBlock:
    ob_type: str
    ob_high: float
    ob_low: float
    wick_high: float
    wick_low: float
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
    zone_type: str
    price_high: float
    price_low: float
    timeframes: List[str]
    score: int
    obs: List[OrderBlock] = field(default_factory=list)

    @property
    def mid(self) -> float:
        return (self.price_high + self.price_low) / 2

    @property
    def tf_count(self) -> int:
        return len(set(self.timeframes))


# ── Pure Python helpers ───────────────────────────────────────────────────────

def _parse_klines(raw: list) -> list:
    """Convert raw kline list to sorted list of dicts with float values."""
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


def _klines_to_df(raw: list) -> list:
    """Alias for compatibility — returns parsed list."""
    return _parse_klines(raw)


def _atr_vals(klines: list, period: int = 14) -> list:
    """Return list of ATR values (same length as klines, None for early bars)."""
    n = len(klines)
    trs = [0.0] * n
    for i in range(1, n):
        h = klines[i]["high"]
        l = klines[i]["low"]
        pc = klines[i-1]["close"]
        trs[i] = max(h - l, abs(h - pc), abs(l - pc))
    atr = [None] * n
    for i in range(period, n):
        atr[i] = sum(trs[i - period + 1: i + 1]) / period
    return atr


def _atr(klines: list, period: int = 14) -> list:
    return _atr_vals(klines, period)


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


# ── Core ICT functions ────────────────────────────────────────────────────────

def detect_order_blocks(raw: list, timeframe: str,
                        max_obs: int = 6,
                        proximity_pct: float = 0.04) -> List[OrderBlock]:
    klines = _parse_klines(raw)
    if len(klines) < 30:
        return []

    atr = _atr_vals(klines)
    sh  = _swing_highs(klines, n=3)
    sl  = _swing_lows(klines, n=3)
    current_price = klines[-1]["close"]
    obs: List[OrderBlock] = []

    for i in range(5, len(klines) - 5):
        c = klines[i]
        avg_atr = atr[i]
        if avg_atr is None or avg_atr == 0:
            continue

        lookahead = klines[i + 1: i + 6]
        if not lookahead:
            continue

        la_highs = [k["high"] for k in lookahead]
        la_lows  = [k["low"]  for k in lookahead]
        la_high  = max(la_highs)
        la_low   = min(la_lows)

        if c["close"] < c["open"]:
            prev_sh = [j for j in sh if j < i]
            if prev_sh:
                last_sh_price = klines[prev_sh[-1]]["high"]
                move_up = la_high - c["close"]
                if la_high > last_sh_price and move_up >= avg_atr * 1.2:
                    ob_high = max(c["open"], c["close"])
                    ob_low  = min(c["open"], c["close"])
                    post = klines[i + 1:]
                    if post and min(k["close"] for k in post) > ob_low * 0.998:
                        obs.append(OrderBlock(
                            ob_type="bullish", ob_high=ob_high, ob_low=ob_low,
                            wick_high=c["high"], wick_low=c["low"],
                            timeframe=timeframe, bar_index=i, timestamp=int(c["time"]),
                        ))

        elif c["close"] > c["open"]:
            prev_sl = [j for j in sl if j < i]
            if prev_sl:
                last_sl_price = klines[prev_sl[-1]]["low"]
                move_dn = c["close"] - la_low
                if la_low < last_sl_price and move_dn >= avg_atr * 1.2:
                    ob_high = max(c["open"], c["close"])
                    ob_low  = min(c["open"], c["close"])
                    post = klines[i + 1:]
                    if post and max(k["close"] for k in post) < ob_high * 1.002:
                        obs.append(OrderBlock(
                            ob_type="bearish", ob_high=ob_high, ob_low=ob_low,
                            wick_high=c["high"], wick_low=c["low"],
                            timeframe=timeframe, bar_index=i, timestamp=int(c["time"]),
                        ))

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
            tol = max(ob1.mid, ob2.mid) * overlap_tol
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
    klines = _parse_klines(raw)
    if len(klines) < lookback:
        klines = klines
    else:
        klines = klines[-lookback:]

    if len(klines) < 10:
        return "neutral"

    sh = _swing_highs(klines, n=3)
    sl = _swing_lows(klines, n=3)

    if len(sh) >= 2 and len(sl) >= 2:
        hh = klines[sh[-1]]["high"] > klines[sh[-2]]["high"]
        hl = klines[sl[-1]]["low"]  > klines[sl[-2]]["low"]
        lh = klines[sh[-1]]["high"] < klines[sh[-2]]["high"]
        ll = klines[sl[-1]]["low"]  < klines[sl[-2]]["low"]
        if hh and hl:
            return "bullish"
        if lh and ll:
            return "bearish"
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
                         entry: float, equal_tol: float = 0.003
                         ) -> List[Tuple[float, str]]:
    klines = _parse_klines(raw)
    candidates: List[Tuple[float, str]] = []

    if direction == "bearish":
        for idx in _swing_lows(klines, n=3):
            p = klines[idx]["low"]
            if p < entry * 0.9995:
                candidates.append((p, "Swing Low"))
        recent_lows = [klines[i]["low"] for i in range(max(0, len(klines)-40), len(klines))
                       if klines[i]["low"] < entry * 0.9995]
        seen: List[float] = []
        for p in recent_lows:
            if any(abs(p - s) / s <= equal_tol for s in seen):
                candidates.append((p, "Equal Lows"))
            seen.append(p)
        candidates.sort(key=lambda x: x[0], reverse=True)
    else:
        for idx in _swing_highs(klines, n=3):
            p = klines[idx]["high"]
            if p > entry * 1.0005:
                candidates.append((p, "Swing High"))
        recent_highs = [klines[i]["high"] for i in range(max(0, len(klines)-40), len(klines))
                        if klines[i]["high"] > entry * 1.0005]
        seen = []
        for p in recent_highs:
            if any(abs(p - s) / s <= equal_tol for s in seen):
                candidates.append((p, "Equal Highs"))
            seen.append(p)
        candidates.sort(key=lambda x: x[0])

    return candidates


def find_ict_tp(klines_1h: list, klines_4h: list,
                entry: float, direction: str, sl: float,
                min_rr: float = 1.5) -> Tuple[float, str]:
    risk = abs(entry - sl)
    if risk == 0:
        return (entry * 0.98 if direction == "bearish" else entry * 1.02), "2:1 R:R"

    fvg_dir = direction
    candidates: List[Tuple[float, str]] = []

    for tf_label, raw in (("1h", klines_1h), ("4h", klines_4h)):
        for flo, fhi in detect_fvg(raw, fvg_dir)[:6]:
            mid = (flo + fhi) / 2
            if direction == "bearish" and mid < entry * 0.9995:
                candidates.append((mid, f"FVG {tf_label}"))
            elif direction == "bullish" and mid > entry * 1.0005:
                candidates.append((mid, f"FVG {tf_label}"))

    for price, label in find_liquidity_pools(klines_1h, fvg_dir, entry)[:6]:
        candidates.append((price, f"{label} 1h"))

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

    if direction == "bearish":
        return max(valid, key=lambda x: x[0])
    else:
        return min(valid, key=lambda x: x[0])


def find_impulse_for_ote(raw: list, direction: str,
                         lookback: int = 50) -> Tuple[float, float]:
    klines = _parse_klines(raw)
    if len(klines) < 10:
        lo = min(k["low"]  for k in klines) if klines else 0.0
        hi = max(k["high"] for k in klines) if klines else 0.0
        return lo, hi

    recent = klines[-lookback:]
    sh = _swing_highs(recent, n=2)
    sl = _swing_lows(recent, n=2)

    if direction == "bullish":
        for si in reversed(sl):
            later_sh = [j for j in sh if j > si]
            if later_sh:
                return recent[si]["low"], recent[later_sh[0]]["high"]
    else:
        for si in reversed(sh):
            later_sl = [j for j in sl if j > si]
            if later_sl:
                return recent[later_sl[0]]["low"], recent[si]["high"]

    lo = min(k["low"]  for k in recent)
    hi = max(k["high"] for k in recent)
    return lo, hi


def find_ote_zone(swing_low: float, swing_high: float,
                  direction: str) -> Tuple[float, float]:
    diff = swing_high - swing_low
    if direction == "bullish":
        return swing_high - diff * 0.79, swing_high - diff * 0.618
    else:
        return swing_low + diff * 0.618, swing_low + diff * 0.79


def detect_liquidity_sweep(raw: list, direction: str) -> Tuple[bool, str]:
    klines = _parse_klines(raw)
    if len(klines) < 15:
        return False, ""

    recent = klines[-30:]
    n = len(recent)

    if direction == "bullish":
        sl_idxs = _swing_lows(recent[:n-2], n=2)
        for si in reversed(sl_idxs[-4:]):
            level = recent[si]["low"]
            for j in range(si + 1, n):
                c = recent[j]
                if c["low"] < level and c["close"] > level:
                    return True, f"SSL swept {level:.6g}"
    else:
        sh_idxs = _swing_highs(recent[:n-2], n=2)
        for si in reversed(sh_idxs[-4:]):
            level = recent[si]["high"]
            for j in range(si + 1, n):
                c = recent[j]
                if c["high"] > level and c["close"] < level:
                    return True, f"BSL swept {level:.6g}"

    return False, ""


def detect_wyckoff_spring(raw: list, direction: str,
                           lookback: int = 80,
                           equal_tol: float = 0.001,   # 0.1% — کف‌های مساوی واقعی
                           min_pierce: float = 0.002,  # حداقل 0.2% زیر سطح رفته
                           wick_ratio: float = 2.5,    # سایه ≥ 2.5× بدنه
                           max_age: int = 4,            # فقط 4 کندل اخیر
                           min_gap: int = 5) -> Tuple[bool, dict]:  # حداقل 5 کندل بین دو کف
    """
    Wyckoff Spring (LONG) / Upthrust (SHORT) — الماس‌های واقعی.

    معیارهای سخت‌گیرانه:
      Equal Lows/Highs : فاصله ≤ 0.1% (نه 0.3%) + حداقل 5 کندل بین‌شون
      Pierce depth     : حداقل 0.2% زیر/بالای سطح رفته (stop hunt واقعی)
      Recovery         : close حداقل 0.1% برگشته به داخل سطح
      Wick ratio       : سایه ≥ 2.5× بدنه (rejection قوی)
      Recency          : فقط 4 کندل اخیر (تازه)
    """
    klines = _parse_klines(raw)
    if len(klines) < 30:
        return False, {}

    recent = klines[-lookback:] if len(klines) >= lookback else klines
    n = len(recent)

    if direction == "bullish":
        sl_idxs = _swing_lows(recent[: max(n - 3, 15)], n=3)
        if len(sl_idxs) < 2:
            return False, {}

        for i in range(len(sl_idxs) - 1, 0, -1):
            for j in range(i - 1, -1, -1):
                # حداقل min_gap کندل بین دو کف
                if sl_idxs[i] - sl_idxs[j] < min_gap:
                    continue
                lo_a = recent[sl_idxs[i]]["low"]
                lo_b = recent[sl_idxs[j]]["low"]
                # Equal lows — فاصله ≤ 0.1%
                if abs(lo_a - lo_b) / lo_a > equal_tol:
                    continue

                level      = min(lo_a, lo_b)
                second_idx = sl_idxs[i]

                for k in range(second_idx + 1, n):
                    c = recent[k]
                    # Pierce: حداقل 0.2% زیر سطح
                    if c["low"] >= level * (1 - min_pierce):
                        continue
                    # Recovery: close حداقل 0.1% بالای سطح
                    if c["close"] < level * 1.001:
                        continue
                    # Wick ratio ≥ 2.5
                    body = abs(c["close"] - c["open"])
                    lw   = min(c["open"], c["close"]) - c["low"]
                    if body == 0 or lw < body * wick_ratio:
                        continue
                    # فقط 4 کندل اخیر
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

    else:  # bearish — Upthrust
        sh_idxs = _swing_highs(recent[: max(n - 3, 15)], n=3)
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
    """
    Wyckoff Spring (LONG) / Upthrust SHORT detection.

    Spring — LONG:
      ۱. Equal Lows: حداقل ۲ کف swing در فاصله ≤0.3% از هم (نقدینگی جمع شده)
      ۲. Spring candle: low زیر سطح Equal Lows رفته (stop hunt)
      ۳. همون کندل یا کندل بعدی close بالای سطح برگشته
      ۴. سایه پایین ≥ ۱.۵× بدنه (hammer shape)
      ۵. تازه‌ست: آخرین max_age کندل اتفاق افتاده

    Upthrust — SHORT:
      آینه: Equal Highs + wick بالا + close پایین‌تر از سطح
    """
    klines = _parse_klines(raw)
    if len(klines) < 20:
        return False, {}

    recent = klines[-lookback:] if len(klines) >= lookback else klines
    n = len(recent)

    if direction == "bullish":
        sl_idxs = _swing_lows(recent[: max(n - 3, 10)], n=2)
        if len(sl_idxs) < 2:
            return False, {}

        for i in range(len(sl_idxs) - 1, 0, -1):
            for j in range(i - 1, -1, -1):
                lo_a = recent[sl_idxs[i]]["low"]
                lo_b = recent[sl_idxs[j]]["low"]
                if abs(lo_a - lo_b) / lo_a > equal_tol:
                    continue

                level = min(lo_a, lo_b)
                second_idx = sl_idxs[i]

                for k in range(second_idx + 1, n):
                    c = recent[k]
                    pierced = c["low"] < level * 0.9995
                    recovered = c["close"] > level
                    if not (pierced and recovered):
                        continue
                    body = abs(c["close"] - c["open"])
                    lw   = min(c["open"], c["close"]) - c["low"]
                    if body == 0 or lw < body * 1.5:
                        continue
                    if k < n - max_age:
                        continue
                    return True, {
                        "type":    "Spring",
                        "level":   level,
                        "swept":   c["low"],
                        "close":   c["close"],
                        "eq_lo1":  lo_a,
                        "eq_lo2":  lo_b,
                        "candle":  c,
                        "age":     n - 1 - k,
                    }

    else:  # bearish — Upthrust
        sh_idxs = _swing_highs(recent[: max(n - 3, 10)], n=2)
        if len(sh_idxs) < 2:
            return False, {}

        for i in range(len(sh_idxs) - 1, 0, -1):
            for j in range(i - 1, -1, -1):
                hi_a = recent[sh_idxs[i]]["high"]
                hi_b = recent[sh_idxs[j]]["high"]
                if abs(hi_a - hi_b) / hi_a > equal_tol:
                    continue

                level = max(hi_a, hi_b)
                second_idx = sh_idxs[i]

                for k in range(second_idx + 1, n):
                    c = recent[k]
                    pierced   = c["high"] > level * 1.0005
                    recovered = c["close"] < level
                    if not (pierced and recovered):
                        continue
                    body = abs(c["close"] - c["open"])
                    uw   = c["high"] - max(c["open"], c["close"])
                    if body == 0 or uw < body * 1.5:
                        continue
                    if k < n - max_age:
                        continue
                    return True, {
                        "type":    "Upthrust",
                        "level":   level,
                        "swept":   c["high"],
                        "close":   c["close"],
                        "eq_hi1":  hi_a,
                        "eq_hi2":  hi_b,
                        "candle":  c,
                        "age":     n - 1 - k,
                    }

    return False, {}


def detect_mss_bos_ltf(raw_5m: list, raw_15m: list,
                        direction: str) -> Tuple[bool, str]:
    for tf_label, raw in (("15m", raw_15m), ("5m", raw_5m)):
        klines = _parse_klines(raw)
        if len(klines) < 20:
            continue
        recent = klines[-40:]
        sh = _swing_highs(recent, n=2)
        sl = _swing_lows(recent, n=2)
        last_close = recent[-1]["close"]

        if direction == "bullish" and len(sh) >= 2:
            prev_sh_price = recent[sh[-2]]["high"]
            if last_close > prev_sh_price:
                tag = "BOS" if recent[sh[-1]]["high"] > prev_sh_price else "MSS"
                return True, f"{tag} {tf_label}"
        elif direction == "bearish" and len(sl) >= 2:
            prev_sl_price = recent[sl[-2]]["low"]
            if last_close < prev_sl_price:
                tag = "BOS" if recent[sl[-1]]["low"] < prev_sl_price else "MSS"
                return True, f"{tag} {tf_label}"

    return False, ""


def find_tiered_tp(klines_1h: list, klines_4h: list,
                   entry: float, direction: str, sl: float,
                   min_rr: float = 2.0) -> Tuple[float, float, str, str]:
    risk = abs(entry - sl)
    if risk == 0:
        risk = entry * 0.01

    fvg_dir = direction
    tp1: Optional[float] = None
    tp1_reason = ""
    tp2: Optional[float] = None
    tp2_reason = ""

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

    if direction == "bearish" and tp2 > tp1:
        tp2 = entry - risk * min_rr * 2
        tp2_reason = "4:1 adjusted"
    elif direction == "bullish" and tp2 < tp1:
        tp2 = entry + risk * min_rr * 2
        tp2_reason = "4:1 adjusted"

    return tp1, tp2, tp1_reason, tp2_reason


def detect_breaker_block(raw: list, timeframe: str,
                          max_bb: int = 4) -> List[OrderBlock]:
    klines = _parse_klines(raw)
    if len(klines) < 40:
        return []

    atr = _atr_vals(klines)
    sh  = _swing_highs(klines, n=3)
    sl  = _swing_lows(klines, n=3)
    cur = klines[-1]["close"]
    result: List[OrderBlock] = []

    for i in range(5, len(klines) - 10):
        c       = klines[i]
        avg_atr = atr[i]
        if avg_atr is None or avg_atr == 0:
            continue

        lookahead = klines[i + 1: i + 6]
        if not lookahead:
            continue

        la_high = max(k["high"] for k in lookahead)
        la_low  = min(k["low"]  for k in lookahead)
        ob_high = max(c["open"], c["close"])
        ob_low  = min(c["open"], c["close"])

        if c["close"] < c["open"]:
            prev_sh = [j for j in sh if j < i]
            if prev_sh:
                last_sh_price = klines[prev_sh[-1]]["high"]
                move_up = la_high - c["close"]
                if la_high > last_sh_price and move_up >= avg_atr * 1.2:
                    post = klines[i + 1:]
                    if post and min(k["close"] for k in post) <= ob_low * 1.002:
                        dist = abs(cur - (ob_high + ob_low) / 2) / cur
                        if dist <= 0.04:
                            result.append(OrderBlock(
                                ob_type="bearish_breaker",
                                ob_high=ob_high, ob_low=ob_low,
                                wick_high=c["high"], wick_low=c["low"],
                                timeframe=timeframe, bar_index=i, timestamp=int(c["time"]),
                            ))

        elif c["close"] > c["open"]:
            prev_sl = [j for j in sl if j < i]
            if prev_sl:
                last_sl_price = klines[prev_sl[-1]]["low"]
                move_dn = c["close"] - la_low
                if la_low < last_sl_price and move_dn >= avg_atr * 1.2:
                    post = klines[i + 1:]
                    if post and max(k["close"] for k in post) >= ob_high * 0.998:
                        dist = abs(cur - (ob_high + ob_low) / 2) / cur
                        if dist <= 0.04:
                            result.append(OrderBlock(
                                ob_type="bullish_breaker",
                                ob_high=ob_high, ob_low=ob_low,
                                wick_high=c["high"], wick_low=c["low"],
                                timeframe=timeframe, bar_index=i, timestamp=int(c["time"]),
                            ))

    return sorted(result, key=lambda x: x.bar_index, reverse=True)[:max_bb]


def detect_mitigation_block(raw: list, timeframe: str,
                              direction: str) -> Optional[OrderBlock]:
    obs = detect_order_blocks(raw, timeframe, max_obs=8, proximity_pct=0.05)
    klines = _parse_klines(raw)
    if not klines:
        return None
    cur = klines[-1]["close"]

    for ob in sorted(obs, key=lambda x: x.bar_index, reverse=True):
        if ob.ob_type != direction:
            continue
        mid  = (ob.ob_high + ob.ob_low) / 2
        dist = abs(cur - mid) / cur
        if dist <= 0.005:
            return ob
    return None


def detect_candle_confirmation(raw: list, direction: str) -> Tuple[bool, str]:
    klines = _parse_klines(raw)
    if len(klines) < 3:
        return False, ""

    prev = klines[-3]
    last = klines[-2]

    o1, h1, l1, c1 = prev["open"], prev["high"], prev["low"], prev["close"]
    o2, h2, l2, c2 = last["open"], last["high"], last["low"], last["close"]

    body2 = abs(c2 - o2)
    body1 = abs(c1 - o1)
    uw2   = h2 - max(o2, c2)
    lw2   = min(o2, c2) - l2
    rng2  = h2 - l2

    if rng2 == 0:
        return False, ""

    if direction == "bullish":
        if (c2 > o2 and body2 > 0
                and o2 <= min(o1, c1)
                and c2 >= max(o1, c1)
                and body2 >= body1 * 0.75):
            return True, "Bullish Engulfing"
        if body2 > 0 and lw2 >= body2 * 2.0 and c2 >= l2 + rng2 * 0.6:
            return True, "Hammer"
        if lw2 >= rng2 * 0.6 and c2 > o2:
            return True, "Bullish Pin Bar"
    else:
        if (c2 < o2 and body2 > 0
                and o2 >= max(o1, c1)
                and c2 <= min(o1, c1)
                and body2 >= body1 * 0.75):
            return True, "Bearish Engulfing"
        if body2 > 0 and uw2 >= body2 * 2.0 and c2 <= l2 + rng2 * 0.4:
            return True, "Shooting Star"
        if uw2 >= rng2 * 0.6 and c2 < o2:
            return True, "Bearish Pin Bar"

    return False, ""


def btc_ict_bias(tf_klines: dict) -> Tuple[str, str]:
    """
    Full ICT BTC bias:
      - 4H market structure (HH/HL vs LH/LL)         +4 / +4
      - 4H BOS / MSS (price broke prev swing)         +3 / +3
      - 4H FVG in direction                           +1 / +1
      - 4H liquidity sweep                            +1 / +1
      - 1H market structure                           +2 / +2
      - 1H BOS / MSS                                  +1 / +1
      - Daily structure (context filter)              +2 / +2
      - 4H premium/discount (>50% = premium → SHORT)  +1 / +1
    Needs ≥ 60% of scored points to call a direction.
    """
    scores  = {"bullish": 0, "bearish": 0}
    details = []

    # ── 4H ───────────────────────────────────────────────────────────────
    raw4h = tf_klines.get("4h", [])
    if raw4h:
        ms4h = market_structure(raw4h, lookback=60)
        details.append(f"4H:{ms4h[0].upper()}")
        if ms4h == "bullish":   scores["bullish"] += 4
        elif ms4h == "bearish": scores["bearish"] += 4

        kl4 = _parse_klines(raw4h)
        if len(kl4) >= 20:
            recent4 = kl4[-60:] if len(kl4) >= 60 else kl4
            sh4 = _swing_highs(recent4, n=3)
            sl4 = _swing_lows(recent4,  n=3)
            last_c = kl4[-1]["close"]
            # BOS bullish: closed above previous swing high
            if len(sh4) >= 2 and last_c > recent4[sh4[-2]]["high"]:
                scores["bullish"] += 3
                details.append("4H:BOS↑")
            # BOS bearish: closed below previous swing low
            if len(sl4) >= 2 and last_c < recent4[sl4[-2]]["low"]:
                scores["bearish"] += 3
                details.append("4H:BOS↓")

            # FVG bias
            if detect_fvg(raw4h, "bullish"): scores["bullish"] += 1
            if detect_fvg(raw4h, "bearish"): scores["bearish"] += 1

            # Liquidity sweep (shows intent)
            lq_b, _ = detect_liquidity_sweep(raw4h, "bullish")
            lq_s, _ = detect_liquidity_sweep(raw4h, "bearish")
            if lq_b: scores["bullish"] += 1
            if lq_s: scores["bearish"] += 1

            # Premium / Discount of 4H range
            # ICT: buy in discount (<50% of range), sell in premium (>50%)
            rng_hi = max(k["high"] for k in recent4)
            rng_lo = min(k["low"]  for k in recent4)
            equil  = (rng_hi + rng_lo) / 2
            if last_c < equil:
                scores["bullish"] += 1
                details.append("DISC")
            else:
                scores["bearish"] += 1
                details.append("PREM")

    # ── 1H ───────────────────────────────────────────────────────────────
    raw1h = tf_klines.get("1h", [])
    if raw1h:
        ms1h = market_structure(raw1h, lookback=40)
        details.append(f"1H:{ms1h[0].upper()}")
        if ms1h == "bullish":   scores["bullish"] += 2
        elif ms1h == "bearish": scores["bearish"] += 2

        kl1 = _parse_klines(raw1h)
        if len(kl1) >= 20:
            recent1 = kl1[-40:] if len(kl1) >= 40 else kl1
            sh1 = _swing_highs(recent1, n=2)
            sl1 = _swing_lows(recent1,  n=2)
            last_c = kl1[-1]["close"]
            if len(sh1) >= 2 and last_c > recent1[sh1[-2]]["high"]:
                scores["bullish"] += 1
                details.append("1H:BOS↑")
            if len(sl1) >= 2 and last_c < recent1[sl1[-2]]["low"]:
                scores["bearish"] += 1
                details.append("1H:BOS↓")

    # ── Daily (context / filter) ──────────────────────────────────────────
    raw1d = tf_klines.get("1d", [])
    if raw1d:
        ms1d = market_structure(raw1d, lookback=30)
        details.append(f"D:{ms1d[0].upper()}")
        if ms1d == "bullish":   scores["bullish"] += 2
        elif ms1d == "bearish": scores["bearish"] += 2

    # ── Decision ─────────────────────────────────────────────────────────
    total = scores["bullish"] + scores["bearish"]
    if total == 0:
        return "neutral", " | ".join(details)

    bull_pct = scores["bullish"] / total * 100
    bear_pct = scores["bearish"] / total * 100

    if bull_pct >= 60:
        return "bullish", " | ".join(details) + f"  [{bull_pct:.0f}%↑]"
    if bear_pct >= 60:
        return "bearish", " | ".join(details) + f"  [{bear_pct:.0f}%↓]"
    return "neutral", " | ".join(details) + f"  [↑{scores['bullish']} ↓{scores['bearish']}]"
