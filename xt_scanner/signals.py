"""
Signal engine — computes CVD, OBI, and Liquidity Sweep for each symbol
and combines them into a single 0–100 score.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import config
import xt_websocket as ws


@dataclass
class SignalResult:
    symbol: str
    price: float
    cvd: float                   # raw cumulative volume delta
    cvd_signal: float            # normalised 0–1 component
    obi_ratio: float             # bid_vol / ask_vol
    obi_signal: float            # normalised 0–1 component
    sweep_signal: float          # 0–1 component
    score: float                 # weighted 0–100
    direction: str               # "LONG" | "SHORT" | "NEUTRAL"
    ts: float = field(default_factory=time.time)


# Running history used by the sweep detector:
# { symbol: deque of (high, low, close) tuples }
_candle_history: Dict[str, List[tuple]] = {}
_CANDLE_WINDOW = 20             # look-back candles for sweep detection


# ──────────────────────────────────────────────
# CVD
# ──────────────────────────────────────────────

def _compute_cvd(symbol: str) -> tuple[float, float]:
    """
    Returns (cvd_raw, cvd_signal).
    cvd_signal is 0.5 when balanced, >0.5 bullish, <0.5 bearish.
    """
    trades = ws.trade_data.get(symbol)
    if not trades:
        return 0.0, 0.5

    now = time.time()
    cutoff = now - config.TRADE_WINDOW_SEC

    buy_vol = sell_vol = 0.0
    for t in trades:
        if t["ts"] < cutoff:
            continue
        if t["side"] == "buy":
            buy_vol += t["qty"]
        else:
            sell_vol += t["qty"]

    total = buy_vol + sell_vol
    if total == 0:
        return 0.0, 0.5

    cvd_raw = buy_vol - sell_vol
    # normalise to [0, 1]: 0.5 = perfectly balanced
    cvd_signal = buy_vol / total
    return cvd_raw, cvd_signal


# ──────────────────────────────────────────────
# OBI
# ──────────────────────────────────────────────

def _compute_obi(symbol: str) -> tuple[float, float]:
    """
    Returns (obi_ratio, obi_signal 0-1).
    ratio > OBI_LONG_THRESHOLD → signal near 1
    ratio < OBI_SHORT_THRESHOLD → signal near 0
    """
    book = ws.orderbook_data.get(symbol, {})
    bids = book.get("bids", [])
    asks = book.get("asks", [])

    top = config.ORDER_BOOK_TOP
    bid_vol = sum(qty for _, qty in bids[:top])
    ask_vol = sum(qty for _, qty in asks[:top])

    if ask_vol == 0:
        return 0.0, 0.5

    ratio = bid_vol / ask_vol

    # map ratio to 0-1 signal using sigmoid-like clamp
    if ratio >= config.OBI_LONG_THRESHOLD:
        signal = 1.0
    elif ratio <= config.OBI_SHORT_THRESHOLD:
        signal = 0.0
    else:
        # linear interpolation between thresholds
        span = config.OBI_LONG_THRESHOLD - config.OBI_SHORT_THRESHOLD
        signal = (ratio - config.OBI_SHORT_THRESHOLD) / span

    return ratio, signal


# ──────────────────────────────────────────────
# Liquidity Sweep
# ──────────────────────────────────────────────

def _update_candle_history(symbol: str, price: float) -> None:
    """Accumulate price into a running high/low/close candle bucket."""
    hist = _candle_history.setdefault(symbol, [])
    if not hist:
        hist.append({"high": price, "low": price, "close": price})
    else:
        current = hist[-1]
        current["high"] = max(current["high"], price)
        current["low"] = min(current["low"], price)
        current["close"] = price


def rotate_candle(symbol: str) -> None:
    """Call every signal interval to start a new candle bucket."""
    hist = _candle_history.setdefault(symbol, [])
    if hist:
        last = hist[-1]
        new_candle = {"high": last["close"], "low": last["close"], "close": last["close"]}
        hist.append(new_candle)
        if len(hist) > _CANDLE_WINDOW + 1:
            hist.pop(0)


def _compute_sweep(symbol: str, price: float) -> float:
    """
    Returns 0-1 sweep signal:
      ~1.0 = bullish sweep (price broke below recent low then recovered)
      ~0.0 = bearish sweep (price broke above recent high then reversed)
      0.5  = no sweep
    """
    _update_candle_history(symbol, price)
    hist = _candle_history.get(symbol, [])
    if len(hist) < 3:
        return 0.5

    # look-back window excluding the current (incomplete) candle
    lookback = hist[:-1][-_CANDLE_WINDOW:]
    if not lookback:
        return 0.5

    recent_high = max(c["high"] for c in lookback)
    recent_low = min(c["low"] for c in lookback)
    current = hist[-1]

    bullish_sweep = current["low"] < recent_low and current["close"] > recent_low
    bearish_sweep = current["high"] > recent_high and current["close"] < recent_high

    if bullish_sweep and not bearish_sweep:
        return 1.0
    if bearish_sweep and not bullish_sweep:
        return 0.0
    return 0.5


# ──────────────────────────────────────────────
# Combined score
# ──────────────────────────────────────────────

def _direction(score: float) -> str:
    if score >= 60:
        return "LONG"
    if score <= 40:
        return "SHORT"
    return "NEUTRAL"


def compute_signal(symbol: str) -> Optional[SignalResult]:
    price = ws.last_price.get(symbol)
    if price is None:
        return None

    cvd_raw, cvd_sig = _compute_cvd(symbol)
    obi_ratio, obi_sig = _compute_obi(symbol)
    sweep_sig = _compute_sweep(symbol, price)

    weighted = (
        config.WEIGHT_CVD * cvd_sig
        + config.WEIGHT_OBI * obi_sig
        + config.WEIGHT_SWEEP * sweep_sig
    )
    score = round(weighted * 100, 1)
    direction = _direction(score)

    return SignalResult(
        symbol=symbol,
        price=price,
        cvd=round(cvd_raw, 4),
        cvd_signal=round(cvd_sig, 3),
        obi_ratio=round(obi_ratio, 3),
        obi_signal=round(obi_sig, 3),
        sweep_signal=round(sweep_sig, 3),
        score=score,
        direction=direction,
    )


def compute_all_signals(symbols: List[str]) -> List[SignalResult]:
    results = []
    for sym in symbols:
        rotate_candle(sym)
        result = compute_signal(sym)
        if result is not None:
            results.append(result)
    results.sort(key=lambda r: r.score, reverse=True)
    return results
