"""Dataclasses for volume analysis output."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VolumeBin:
    price_low: float
    price_high: float
    price_mid: float
    volume: float
    pct: float

    def to_dict(self) -> dict:
        return {
            "price_low":  round(self.price_low,  8),
            "price_high": round(self.price_high, 8),
            "price_mid":  round(self.price_mid,  8),
            "volume":     round(self.volume, 4),
            "pct":        round(self.pct, 2),
        }


@dataclass
class VolumeProfileResult:
    poc_price: float           # Point of Control
    vah: float                 # Value Area High
    val: float                 # Value Area Low
    total_volume: float
    value_area_pct: float      # fraction of volume in VA (target ≈ 0.70)
    bins: list[VolumeBin] = field(default_factory=list)

    def to_dict(self, top_bins: int = 10) -> dict:
        sorted_bins = sorted(self.bins, key=lambda b: b.volume, reverse=True)
        return {
            "poc_price":       round(self.poc_price, 8),
            "vah":             round(self.vah, 8),
            "val":             round(self.val, 8),
            "total_volume":    round(self.total_volume, 4),
            "value_area_pct":  round(self.value_area_pct * 100, 2),
            "top_bins":        [b.to_dict() for b in sorted_bins[:top_bins]],
        }


@dataclass
class VWAPResult:
    current_vwap: float
    current_upper_1: float
    current_lower_1: float
    current_upper_2: float
    current_lower_2: float
    current_price: float
    position: str        # "ABOVE_BAND2" | "ABOVE_BAND1" | "ABOVE_VWAP" | "BELOW_VWAP" | "BELOW_BAND1" | "BELOW_BAND2"
    std_multiplier: float

    def to_dict(self) -> dict:
        return {
            "current_price":   round(self.current_price,   8),
            "vwap":            round(self.current_vwap,    8),
            "upper_band_1":    round(self.current_upper_1, 8),
            "lower_band_1":    round(self.current_lower_1, 8),
            "upper_band_2":    round(self.current_upper_2, 8),
            "lower_band_2":    round(self.current_lower_2, 8),
            "position":        self.position,
            "std_multiplier":  self.std_multiplier,
        }


@dataclass
class DivergenceSignal:
    open_time: int
    divergence_type: str    # "BEARISH" | "BULLISH_EXHAUSTION"
    price_change_pct: float
    volume_ratio: float     # recent_avg_vol / longer_avg_vol

    def to_dict(self) -> dict:
        return {
            "open_time":        self.open_time,
            "divergence_type":  self.divergence_type,
            "price_change_pct": round(self.price_change_pct, 2),
            "volume_ratio":     round(self.volume_ratio, 3),
        }
