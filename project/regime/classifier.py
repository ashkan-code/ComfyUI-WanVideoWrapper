"""RegimeClassifier: combines ADX, DI+/-, and ATR ratio into a Regime label per bar."""

from __future__ import annotations

import pandas as pd

from regime.adx import compute_adx, compute_atr_ratio
from regime.models import BarRegime, Regime, RegimeResult


class RegimeClassifier:
    """Classifies each bar into one of four regimes using ADX + volatility ratio.

    Decision logic (evaluated in order):
    1. VOLATILE      — ATR ratio > vol_spike_threshold  (volatility spike)
    2. TRENDING_UP   — ADX > trend_threshold AND DI+ > DI-
    3. TRENDING_DOWN — ADX > trend_threshold AND DI- > DI+
    4. RANGING       — ADX < range_threshold
    5. UNKNOWN       — transitional zone between range_threshold and trend_threshold
    """

    def __init__(
        self,
        adx_period: int = 14,
        atr_short: int = 14,
        atr_long: int = 50,
        trend_threshold: float = 25.0,
        range_threshold: float = 20.0,
        vol_spike_threshold: float = 1.5,
    ) -> None:
        self.adx_period = adx_period
        self.atr_short = atr_short
        self.atr_long = atr_long
        self.trend_threshold = trend_threshold
        self.range_threshold = range_threshold
        self.vol_spike_threshold = vol_spike_threshold

    def classify(
        self,
        df: pd.DataFrame,
        symbol: str = "",
        interval: str = "",
        market: str = "spot",
    ) -> RegimeResult:
        """Classify every bar and return a RegimeResult.

        Args:
            df: OHLCV DataFrame with columns: open_time, high, low, close, volume.

        Returns:
            RegimeResult with current (last bar) regime, history, and distribution.

        Raises:
            ValueError: DataFrame too short to compute ADX.
        """
        min_bars = 2 * self.adx_period + self.atr_long
        if len(df) < min_bars:
            raise ValueError(
                f"Need at least {min_bars} bars for regime detection, got {len(df)}"
            )

        adx_df   = compute_adx(df, period=self.adx_period)
        atr_ratio = compute_atr_ratio(df, short=self.atr_short, long=self.atr_long)

        history: list[BarRegime] = []
        for i in range(len(df)):
            adx = adx_df["adx"].iloc[i]
            dip = adx_df["di_plus"].iloc[i]
            dim = adx_df["di_minus"].iloc[i]
            vr  = float(atr_ratio.iloc[i])

            if any(v != v for v in (adx, dip, dim)):   # NaN guard
                regime = Regime.UNKNOWN
            else:
                regime = self._classify_bar(float(adx), float(dip), float(dim), vr)

            history.append(BarRegime(
                open_time=int(df["open_time"].iloc[i]),
                regime=regime,
                adx=float(adx) if adx == adx else 0.0,
                di_plus=float(dip) if dip == dip else 0.0,
                di_minus=float(dim) if dim == dim else 0.0,
                atr_ratio=vr,
            ))

        current = history[-1]
        distribution = self._distribution(history)
        dominant = max(distribution, key=lambda r: distribution[r]["count"])

        return RegimeResult(
            symbol=symbol,
            interval=interval,
            market=market,
            current_regime=current.regime,
            current_adx=current.adx,
            current_di_plus=current.di_plus,
            current_di_minus=current.di_minus,
            current_atr_ratio=current.atr_ratio,
            dominant_regime=Regime(dominant),
            regime_distribution=distribution,
            history=history,
        )

    def _classify_bar(
        self, adx: float, di_plus: float, di_minus: float, atr_ratio: float
    ) -> Regime:
        if atr_ratio > self.vol_spike_threshold:
            return Regime.VOLATILE
        if adx > self.trend_threshold:
            return Regime.TRENDING_UP if di_plus > di_minus else Regime.TRENDING_DOWN
        if adx < self.range_threshold:
            return Regime.RANGING
        return Regime.UNKNOWN

    @staticmethod
    def _distribution(history: list[BarRegime]) -> dict[str, dict]:
        counts: dict[str, int] = {}
        for b in history:
            key = b.regime.value
            counts[key] = counts.get(key, 0) + 1
        total = len(history)
        return {
            r: {"count": c, "pct": round(c / total * 100, 1)}
            for r, c in sorted(counts.items(), key=lambda x: -x[1])
        }
