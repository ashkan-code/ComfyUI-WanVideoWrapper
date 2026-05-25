"""ICT concepts: Order Block detection, market structure analysis."""

from dataclasses import dataclass, field
from typing import List, Tuple

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
