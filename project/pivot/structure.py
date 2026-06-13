"""Market structure: HH / HL / LH / LL and trend direction."""

from __future__ import annotations
from dataclasses import dataclass
from pivot.engine import Pivot


@dataclass
class MarketStructure:
    trend:      str          # UPTREND | DOWNTREND | RANGE
    last_hh:    float | None
    last_hl:    float | None
    last_lh:    float | None
    last_ll:    float | None
    swing_count: int


def detect_structure(pivots: list[Pivot]) -> MarketStructure:
    """Compare last two pivot highs and last two pivot lows."""
    highs = sorted([p for p in pivots if p.type == "HIGH"], key=lambda p: p.timestamp)
    lows  = sorted([p for p in pivots if p.type == "LOW"],  key=lambda p: p.timestamp)

    if len(highs) < 2 or len(lows) < 2:
        return MarketStructure("RANGE", None, None, None, None, 0)

    hh = highs[-1].price > highs[-2].price
    hl = lows[-1].price  > lows[-2].price
    lh = highs[-1].price < highs[-2].price
    ll = lows[-1].price  < lows[-2].price

    if hh and hl:
        trend = "UPTREND"
    elif lh and ll:
        trend = "DOWNTREND"
    else:
        trend = "RANGE"

    return MarketStructure(
        trend       = trend,
        last_hh     = highs[-1].price if hh else None,
        last_hl     = lows[-1].price  if hl else None,
        last_lh     = highs[-1].price if lh else None,
        last_ll     = lows[-1].price  if ll else None,
        swing_count = min(len(highs), len(lows)),
    )
