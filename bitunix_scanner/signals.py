"""Signal building, leverage calculation, and pretty printing."""

import math
from dataclasses import dataclass
from typing import List, Optional

from .ict import ConfluentZone, TF_WEIGHT, find_ict_tp

TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]
MAX_LEVERAGE = 10

# ── Scalping parameters ───────────────────────────────────────────────────
# SL: above/below the entry-OB's exact wick (ICT sniper SL)
# TP: ICT target (FVG, swing low/high, equal levels) with min 1.5:1 R:R
#     fallback to 2:1 R:R if no ICT target found
SL_BUFFER_PCT = 0.0005   # 0.05% beyond OB wick
MIN_RR        = 1.5      # minimum accepted R:R


@dataclass
class Signal:
    symbol: str
    direction: str          # 'LONG' | 'SHORT'
    entry: float
    sl: float
    tp: float
    leverage: int
    loss_pct: float
    rr: float
    zone: ConfluentZone
    btc_bias: str
    btc_detail: str
    aligned: bool           # zone direction matches BTC bias
    tp_reason: str = ""     # ICT target type used for TP


def _floor_leverage(lev: float) -> int:
    return max(1, min(MAX_LEVERAGE, math.floor(lev)))


def _entry_ob_wick(zone: ConfluentZone) -> tuple:
    """
    ICT sniper SL: use the wick of the OB that sits at the entry edge.

    SHORT (entry = zone.price_low):
        → entry OB = OB whose ob_low is closest to zone.price_low
        → SL = that OB's wick_high (full candle top)

    LONG (entry = zone.price_high):
        → entry OB = OB whose ob_high is closest to zone.price_high
        → SL = that OB's wick_low (full candle bottom)
    """
    if zone.zone_type == "bearish":
        ob = min(zone.obs, key=lambda o: abs(o.ob_low - zone.price_low))
        return ob.wick_high, ob.wick_low
    else:
        ob = min(zone.obs, key=lambda o: abs(o.ob_high - zone.price_high))
        return ob.wick_high, ob.wick_low


def build_signal(symbol: str, zone: ConfluentZone,
                 current_price: float,
                 btc_bias: str, btc_detail: str,
                 klines_1h: list = None,
                 klines_4h: list = None) -> Optional[Signal]:
    """
    ICT sniper scalping signal.

    Entry    : edge of OB zone nearest to current price
    SL       : exact wick of the entry OB + 0.05% buffer
    TP       : nearest ICT target (FVG → swing low/high → equal levels)
               with min 1.5:1 R:R; fallback to 2:1 R:R
    Leverage : floor(15 / SL%) capped at MAX_LEVERAGE (10×)
    """
    wick_high, wick_low = _entry_ob_wick(zone)

    if zone.zone_type == "bullish":
        direction = "LONG"
        entry    = zone.price_high
        sl       = wick_low * (1 - SL_BUFFER_PCT)
        loss_pct = (entry - sl) / entry * 100
    else:
        direction = "SHORT"
        entry    = zone.price_low
        sl       = wick_high * (1 + SL_BUFFER_PCT)
        loss_pct = (sl - entry) / entry * 100

    if loss_pct <= 0:
        loss_pct = 0.1

    # ── ICT TP detection ──────────────────────────────────────────────────
    ict_dir = "bearish" if direction == "SHORT" else "bullish"
    if klines_1h and klines_4h:
        tp, tp_reason = find_ict_tp(
            klines_1h, klines_4h,
            entry, ict_dir, sl,
            min_rr=MIN_RR,
        )
    else:
        risk = abs(entry - sl)
        tp = (entry - risk * 2.0) if direction == "SHORT" else (entry + risk * 2.0)
        tp_reason = "2:1 R:R (no klines)"

    leverage = _floor_leverage(15 / loss_pct)
    rr       = abs(tp - entry) / abs(sl - entry)
    aligned  = (btc_bias == zone.zone_type) or (btc_bias == "neutral")

    return Signal(
        symbol    = symbol,
        direction = direction,
        entry     = entry,
        sl        = sl,
        tp        = tp,
        leverage  = leverage,
        loss_pct  = loss_pct,
        rr        = rr,
        zone      = zone,
        btc_bias  = btc_bias,
        btc_detail= btc_detail,
        aligned   = aligned,
        tp_reason = tp_reason,
    )


def _fmt(price: float) -> str:
    """Format price with appropriate decimal places."""
    if price >= 1000:
        return f"{price:,.2f}"
    if price >= 1:
        return f"{price:.4f}"
    return f"{price:.6f}"


def _bar(score: int, max_score: int = 21) -> str:
    filled = round(score / max_score * 10)
    return "█" * filled + "░" * (10 - filled)


def format_signal(sig: Signal) -> str:
    tfs = " | ".join(sig.zone.timeframes)
    align_mark = "✓ ALIGNED" if sig.aligned else "✗ DIVERGE"
    arrow = "▲ LONG" if sig.direction == "LONG" else "▼ SHORT"
    dir_color = "🟢" if sig.direction == "LONG" else "🔴"
    sl_pct = f"-{sig.loss_pct:.2f}%" if sig.direction == "LONG" else f"+{sig.loss_pct:.2f}%"
    tp_dist = (sig.tp - sig.entry) / sig.entry * 100
    tp_pct = f"+{tp_dist:.2f}%" if sig.direction == "LONG" else f"{tp_dist:.2f}%"

    lines = [
        f"{'━'*48}",
        f"  {dir_color} {arrow}  ─  {sig.symbol}",
        f"{'━'*48}",
        f"  📍 Entry      : {_fmt(sig.entry)}",
        f"  🛑 Stop Loss  : {_fmt(sig.sl)}  ({sl_pct})  ← OB wick",
        f"  🎯 Take Profit: {_fmt(sig.tp)}  ({tp_pct})",
        f"  📌 TP target  : {sig.tp_reason}",
        f"  ⚡ Leverage   : {sig.leverage}x  "
        f"(15 ÷ {sig.loss_pct:.2f}% = {15/sig.loss_pct:.1f} → {sig.leverage}x)",
        f"  📊 Risk:Reward: 1 : {sig.rr:.1f}",
        f"  ─────────────────────────────────────",
        f"  🔗 TF Confluence : {sig.zone.tf_count}/6 TF  [{tfs}]",
        f"  💯 OB Score     : {sig.zone.score}/21  {_bar(sig.zone.score)}",
        f"  ₿  BTC Bias     : {sig.btc_bias.upper()}  ({sig.btc_detail})",
        f"  🔄 BTC Alignment: {align_mark}",
        f"{'━'*48}",
    ]
    return "\n".join(lines)


def format_summary(signals: List[Signal]) -> str:
    if not signals:
        return "  ── No signals found in this scan ──"
    longs = [s for s in signals if s.direction == "LONG"]
    shorts = [s for s in signals if s.direction == "SHORT"]
    lines = [
        f"\n{'═'*48}",
        f"  SCAN COMPLETE  ─  {len(signals)} signal(s) found",
        f"  🟢 LONG: {len(longs)}   🔴 SHORT: {len(shorts)}",
        f"{'═'*48}",
    ]
    for sig in signals:
        lines.append(format_signal(sig))
        lines.append("")
    return "\n".join(lines)
