"""Return correlation analysis between symbols (no external stat deps)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class PairCorr:
    symbol_a: str
    symbol_b: str
    correlation: float

    def to_dict(self) -> dict:
        return {
            "symbol_a": self.symbol_a,
            "symbol_b": self.symbol_b,
            "correlation": self.correlation,
        }


@dataclass
class CorrelationResult:
    symbols: list[str]
    method: str
    n_bars: int
    matrix: dict[str, dict[str, float]]
    top_positive: list[PairCorr]  # most correlated
    top_uncorrelated: list[PairCorr]  # least correlated (best for diversification)

    def to_dict(self) -> dict:
        return {
            "symbols": self.symbols,
            "method": self.method,
            "n_bars": self.n_bars,
            "matrix": self.matrix,
            "top_positive": [p.to_dict() for p in self.top_positive],
            "top_uncorrelated": [p.to_dict() for p in self.top_uncorrelated],
        }


def compute_correlation(
    price_series: dict[str, pd.Series],
    method: str = "returns",
    top_n: int = 5,
) -> CorrelationResult:
    """Compute Pearson correlation matrix across symbols.

    Args:
        price_series: dict of symbol → close price Series (same length / aligned).
        method:       'returns' (log-return correlation) or 'prices' (level correlation).
        top_n:        How many top/bottom pairs to return.

    Returns:
        CorrelationResult with full matrix and ranked pairs.
    """
    if not price_series:
        raise ValueError("price_series is empty")

    df = pd.DataFrame(price_series).dropna(how="all")

    if method == "returns":
        df = df.pct_change().dropna()
    elif method == "prices":
        pass  # use levels as-is
    else:
        raise ValueError(f"method must be 'returns' or 'prices', got {method!r}")

    if len(df) < 2:
        raise ValueError("Not enough bars to compute correlation after cleaning")

    corr = df.corr(method="pearson")
    symbols = list(price_series.keys())

    # Extract unique pairs (upper triangle)
    pairs: list[PairCorr] = []
    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            a, b = symbols[i], symbols[j]
            if a in corr.index and b in corr.columns:
                val = corr.loc[a, b]
                if not (val != val):  # NaN check
                    pairs.append(PairCorr(a, b, round(float(val), 4)))

    pairs.sort(key=lambda p: p.correlation, reverse=True)

    # Build matrix dict (round values)
    matrix: dict[str, dict[str, float]] = {}
    for s in symbols:
        if s in corr.index:
            matrix[s] = {
                t: round(float(corr.loc[s, t]), 4)
                for t in symbols
                if t in corr.columns and not (corr.loc[s, t] != corr.loc[s, t])
            }

    return CorrelationResult(
        symbols=symbols,
        method=method,
        n_bars=len(df),
        matrix=matrix,
        top_positive=pairs[:top_n],
        top_uncorrelated=sorted(pairs, key=lambda p: abs(p.correlation))[:top_n],
    )
