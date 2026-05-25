"""Advanced ICT signal: OTE + OB + FVG + Liquidity Sweep + tiered TP."""

import math
from dataclasses import dataclass, field
from typing import List, Optional

from .ict import (
    ConfluentZone, TF_WEIGHT,
    find_tiered_tp,
    find_impulse_for_ote, find_ote_zone,
    detect_liquidity_sweep, detect_mss_bos_ltf,
)

MAX_LEVERAGE  = 10
SL_BUFFER_PCT = 0.002   # 0.2% beyond OB wick — tighter sniper SL
MAX_SL_PCT    = 0.015   # skip if SL > 1.5% from entry
MIN_RR        = 2.0     # minimum R:R (1:2)


@dataclass
class Signal:
    symbol:          str
    direction:       str      # 'LONG' | 'SHORT'
    entry:           float
    sl:              float
    tp1:             float    # TP1 — close 50% (nearest liq pool)
    tp2:             float    # TP2 — close 50% (HTF FVG/OB)
    leverage:        int
    loss_pct:        float    # SL distance %
    rr1:             float    # R:R to TP1
    rr2:             float    # R:R to TP2
    zone:            ConfluentZone
    btc_bias:        str
    btc_detail:      str
    aligned:         bool
    tp1_reason:      str = ""
    tp2_reason:      str = ""
    mss_ok:          bool = False
    mss_detail:      str = ""
    fvg_ok:          bool = False
    liq_swept:       bool = False
    liq_detail:      str = ""
    ote_ok:          bool = False
    confluence_count: int = 0
    quality_score:   float = 0.0


def _floor_leverage(lev: float) -> int:
    return max(1, min(MAX_LEVERAGE, math.floor(lev)))


def _entry_ob_wick(zone: ConfluentZone):
    if zone.zone_type == "bearish":
        ob = min(zone.obs, key=lambda o: abs(o.ob_low - zone.price_low))
    else:
        ob = min(zone.obs, key=lambda o: abs(o.ob_high - zone.price_high))
    return ob.wick_high, ob.wick_low


def _quality_score(sig: "Signal") -> float:
    """0–100 quality score for ranking the single best setup."""
    score = 0.0

    # OB zone quality (30 pts)
    score += (sig.zone.score / 21) * 30

    # Confluence count (25 pts): ob + fvg + liq sweep
    score += sig.confluence_count * (25 / 3)

    # MSS/BOS confirmed (15 pts)
    if sig.mss_ok:
        score += 15

    # OTE zone (15 pts)
    if sig.ote_ok:
        score += 15

    # R:R quality (15 pts): reward proportional to RR capped at 5:1
    score += min(sig.rr1 / 5.0, 1.0) * 15

    return min(score, 100.0)


def build_signal(symbol: str, zone: ConfluentZone,
                 current_price: float,
                 btc_bias: str, btc_detail: str,
                 klines_5m: list = None,
                 klines_15m: list = None,
                 klines_1h: list = None,
                 klines_4h: list = None) -> Optional[Signal]:
    """
    Build an advanced ICT signal with tiered TP and full confluence check.
    Returns None if SL > 1.5% or confluence_count < 2.
    """
    wick_high, wick_low = _entry_ob_wick(zone)

    if zone.zone_type == "bullish":
        direction = "LONG"
        # Sniper: enter at bottom of OB (price retraces DOWN to OB)
        entry    = zone.price_low
        sl       = wick_low * (1 - SL_BUFFER_PCT)
        loss_pct = (entry - sl) / entry * 100
    else:
        direction = "SHORT"
        # Sniper: enter at top of OB (price retraces UP to OB)
        entry    = zone.price_high
        sl       = wick_high * (1 + SL_BUFFER_PCT)
        loss_pct = (sl - entry) / entry * 100

    if loss_pct <= 0:
        loss_pct = 0.1

    # Reject if SL > 1.5% from entry
    if loss_pct > MAX_SL_PCT * 100:
        return None

    ict_dir = "bearish" if direction == "SHORT" else "bullish"

    # ── Confluence checks ─────────────────────────────────────────────────
    ob_ok = zone.score >= 6  # at least 2 TFs overlapping

    from .ict import detect_fvg
    fvg_ok = False
    if klines_1h:
        fvg_ok = len(detect_fvg(klines_1h, ict_dir)) > 0

    liq_swept, liq_detail = False, ""
    ref_raw = klines_15m or klines_5m or []
    if ref_raw:
        liq_swept, liq_detail = detect_liquidity_sweep(ref_raw, ict_dir)

    confluence_count = sum([ob_ok, fvg_ok, liq_swept])
    if confluence_count < 2:
        return None

    # ── MSS / BOS ─────────────────────────────────────────────────────────
    mss_ok, mss_detail = False, ""
    if klines_5m or klines_15m:
        mss_ok, mss_detail = detect_mss_bos_ltf(
            klines_5m or [], klines_15m or [], ict_dir
        )

    # ── OTE zone check ────────────────────────────────────────────────────
    ote_ok = False
    ref_ote = klines_15m or klines_1h or []
    if ref_ote:
        sw_low, sw_high = find_impulse_for_ote(ref_ote, ict_dir)
        ote_low, ote_high = find_ote_zone(sw_low, sw_high, ict_dir)
        ote_ok = ote_low <= current_price <= ote_high

    # ── Tiered TP ─────────────────────────────────────────────────────────
    if klines_1h and klines_4h:
        tp1, tp2, tp1_reason, tp2_reason = find_tiered_tp(
            klines_1h, klines_4h, entry, ict_dir, sl, min_rr=MIN_RR
        )
    else:
        risk = abs(entry - sl)
        tp1 = entry - risk * MIN_RR if direction == "SHORT" else entry + risk * MIN_RR
        tp2 = entry - risk * MIN_RR * 2 if direction == "SHORT" else entry + risk * MIN_RR * 2
        tp1_reason, tp2_reason = "2:1 fallback", "4:1 fallback"

    leverage = _floor_leverage(15 / loss_pct)
    rr1 = abs(tp1 - entry) / abs(sl - entry)
    rr2 = abs(tp2 - entry) / abs(sl - entry)

    if rr1 < MIN_RR:
        return None

    aligned = (btc_bias == zone.zone_type) or (btc_bias == "neutral")
    if not aligned:
        return None

    sig = Signal(
        symbol          = symbol,
        direction       = direction,
        entry           = entry,
        sl              = sl,
        tp1             = tp1,
        tp2             = tp2,
        leverage        = leverage,
        loss_pct        = loss_pct,
        rr1             = rr1,
        rr2             = rr2,
        zone            = zone,
        btc_bias        = btc_bias,
        btc_detail      = btc_detail,
        aligned         = aligned,
        tp1_reason      = tp1_reason,
        tp2_reason      = tp2_reason,
        mss_ok          = mss_ok,
        mss_detail      = mss_detail,
        fvg_ok          = fvg_ok,
        liq_swept       = liq_swept,
        liq_detail      = liq_detail,
        ote_ok          = ote_ok,
        confluence_count= confluence_count,
    )
    sig.quality_score = _quality_score(sig)
    return sig


def _fmt(price: float) -> str:
    if price >= 1000: return f"{price:,.2f}"
    if price >= 1:    return f"{price:.4f}"
    return f"{price:.6f}"


def _bar(score: float, max_score: float = 100.0) -> str:
    filled = round(score / max_score * 10)
    return "█" * filled + "░" * (10 - filled)


def format_signal(sig: Signal) -> str:
    tfs = " | ".join(sig.zone.timeframes)
    arrow = "▲ LONG" if sig.direction == "LONG" else "▼ SHORT"
    icon  = "🟢" if sig.direction == "LONG" else "🔴"
    sl_pct = f"-{sig.loss_pct:.3f}%" if sig.direction == "LONG" else f"+{sig.loss_pct:.3f}%"

    tp1_dist = (sig.tp1 - sig.entry) / sig.entry * 100
    tp2_dist = (sig.tp2 - sig.entry) / sig.entry * 100
    tp1_pct = f"{tp1_dist:+.2f}%"
    tp2_pct = f"{tp2_dist:+.2f}%"

    checks = (
        f"{'✅' if sig.mss_ok   else '❌'} BOS/MSS  "
        f"{'✅' if sig.fvg_ok   else '❌'} FVG  "
        f"{'✅' if sig.liq_swept else '❌'} Liq Sweep  "
        f"{'✅' if sig.ote_ok   else '⬜'} OTE"
    )

    lines = [
        f"{'━'*52}",
        f"  {icon} {arrow}  ─  {sig.symbol}",
        f"{'━'*52}",
        f"  Coin      : {sig.symbol}",
        f"  Direction : {sig.direction}",
        f"  HTF Bias  : 4H/1H {sig.btc_bias.upper()}  [{sig.btc_detail}]",
        f"  Entry     : {_fmt(sig.entry)}",
        f"  Stop Loss : {_fmt(sig.sl)}  ({sl_pct})  ← OB wick",
        f"  TP1 (50%) : {_fmt(sig.tp1)}  ({tp1_pct})  ← {sig.tp1_reason}",
        f"  TP2 (50%) : {_fmt(sig.tp2)}  ({tp2_pct})  ← {sig.tp2_reason}",
        f"  RRR       : 1:{sig.rr1:.1f} → 1:{sig.rr2:.1f}",
        f"  Leverage  : {sig.leverage}x",
        f"  ─────────────────────────────────────────",
        f"  ICT Checks: {checks}",
        f"  {'  MSS/BOS  : ' + sig.mss_detail if sig.mss_ok else '  MSS/BOS  : —'}",
        f"  {'  Liq Sweep: ' + sig.liq_detail if sig.liq_swept else '  Liq Sweep: —'}",
        f"  TF Conflu : {sig.zone.tf_count}/6 [{tfs}]",
        f"  OB Score  : {sig.zone.score}/21  {_bar(sig.zone.score, 21)}",
        f"  Quality   : {sig.quality_score:.0f}/100  {_bar(sig.quality_score)}",
        f"  Confluence: {sig.confluence_count}/3 (OB + FVG + Liq Sweep)",
        f"{'━'*52}",
    ]
    return "\n".join(lines)


def format_summary(signals: List[Signal]) -> str:
    if not signals:
        return "  ── No signals found in this scan ──"
    longs  = [s for s in signals if s.direction == "LONG"]
    shorts = [s for s in signals if s.direction == "SHORT"]
    lines = [
        f"\n{'═'*52}",
        f"  SCAN COMPLETE  ─  {len(signals)} valid setup(s)",
        f"  🟢 LONG: {len(longs)}   🔴 SHORT: {len(shorts)}",
        f"{'═'*52}",
    ]
    for sig in signals:
        lines.append(format_signal(sig))
        lines.append("")
    return "\n".join(lines)
