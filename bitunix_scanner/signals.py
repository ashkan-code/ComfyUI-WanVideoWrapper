"""Signal building, leverage calculation, and pretty printing."""

import math
from dataclasses import dataclass
from typing import List, Optional

from .ict import ConfluentZone, TF_WEIGHT

TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]
MAX_LEVERAGE = 10

# ── Scalping parameters ───────────────────────────────────────────────────
# SL is taken from the lowest-TF OB wick in the confluent zone (tighter)
# TP uses a 2:1 R:R for quick exits
SCALP_RR       = 2.0    # risk:reward ratio
SL_BUFFER_PCT  = 0.0005  # 0.05% buffer beyond OB wick


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


def _floor_leverage(lev: float) -> int:
    return max(1, min(MAX_LEVERAGE, math.floor(lev)))


def _tightest_wick(zone: ConfluentZone) -> tuple:
    """
    For scalping: use the lowest-TF OB wick for SL (tightest stop).
    Returns (wick_high, wick_low) of the lowest-timeframe OB in the zone.
    """
    sorted_obs = sorted(zone.obs, key=lambda ob: TF_WEIGHT.get(ob.timeframe, 99))
    lowest_tf_ob = sorted_obs[0]
    return lowest_tf_ob.wick_high, lowest_tf_ob.wick_low


def build_signal(symbol: str, zone: ConfluentZone,
                 current_price: float,
                 btc_bias: str, btc_detail: str) -> Optional[Signal]:
    """
    Scalping signal from a confluent OB zone.

    Entry    : edge of zone nearest to current price
    SL       : tightest OB wick (lowest TF) + small buffer — keeps leverage high
    TP       : SCALP_RR × risk from entry
    Leverage : floor(15 / loss_pct), capped at MAX_LEVERAGE (10×)
    """
    wick_high, wick_low = _tightest_wick(zone)

    if zone.zone_type == "bullish":
        direction = "LONG"
        entry = zone.price_high
        sl = wick_low * (1 - SL_BUFFER_PCT)
        loss_pct = (entry - sl) / entry * 100
        risk = entry - sl
        tp = entry + risk * SCALP_RR
    else:
        direction = "SHORT"
        entry = zone.price_low
        sl = wick_high * (1 + SL_BUFFER_PCT)
        loss_pct = (sl - entry) / entry * 100
        risk = sl - entry
        tp = entry - risk * SCALP_RR

    if loss_pct <= 0:
        loss_pct = 0.1
    leverage = _floor_leverage(15 / loss_pct)
    rr = abs(tp - entry) / abs(sl - entry)
    aligned = (btc_bias == zone.zone_type) or (btc_bias == "neutral")

    return Signal(
        symbol=symbol,
        direction=direction,
        entry=entry,
        sl=sl,
        tp=tp,
        leverage=leverage,
        loss_pct=loss_pct,
        rr=rr,
        zone=zone,
        btc_bias=btc_bias,
        btc_detail=btc_detail,
        aligned=aligned,
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
        f"  🛑 Stop Loss  : {_fmt(sig.sl)}  ({sl_pct})",
        f"  🎯 Take Profit: {_fmt(sig.tp)}  ({tp_pct})",
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
