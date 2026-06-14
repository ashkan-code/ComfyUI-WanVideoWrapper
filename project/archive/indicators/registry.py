"""Indicator registry: maps spec strings to compute functions.

Spec format: "name" or "name:param1:param2"
  Examples:
    "rsi"        → RSI(14)
    "rsi:7"      → RSI(7)
    "sma:50"     → SMA(50)
    "macd"       → MACD(12,26,9)
    "macd:8:21:5"→ MACD(8,21,5)
    "bb:20:2"    → Bollinger Bands(20, std=2.0)
    "atr:14"     → ATR(14)
    "stoch"      → Stochastic(14,3)
    "obv"        → OBV
    "vwap"       → VWAP
"""

from __future__ import annotations

from typing import Callable

import pandas as pd

from indicators import momentum, trend, volatility, volume as vol_mod

# Each entry: fn(df, *positional_params_from_spec) -> dict[str, pd.Series]
_IndicatorFn = Callable[..., dict[str, pd.Series]]

_REGISTRY: dict[str, _IndicatorFn] = {}


def _reg(name: str) -> Callable[[_IndicatorFn], _IndicatorFn]:
    def decorator(fn: _IndicatorFn) -> _IndicatorFn:
        _REGISTRY[name] = fn
        return fn
    return decorator


# ── Trend ────────────────────────────────────────────────────────────────────

@_reg("sma")
def _sma(df: pd.DataFrame, period: int = 20) -> dict[str, pd.Series]:
    return {"sma": trend.sma(df["close"], int(period))}


@_reg("ema")
def _ema(df: pd.DataFrame, period: int = 20) -> dict[str, pd.Series]:
    return {"ema": trend.ema(df["close"], int(period))}


@_reg("dema")
def _dema(df: pd.DataFrame, period: int = 20) -> dict[str, pd.Series]:
    return {"dema": trend.dema(df["close"], int(period))}


@_reg("wma")
def _wma(df: pd.DataFrame, period: int = 20) -> dict[str, pd.Series]:
    return {"wma": trend.wma(df["close"], int(period))}


# ── Momentum ─────────────────────────────────────────────────────────────────

@_reg("rsi")
def _rsi(df: pd.DataFrame, period: int = 14) -> dict[str, pd.Series]:
    return {"rsi": momentum.rsi(df["close"], int(period))}


@_reg("macd")
def _macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict[str, pd.Series]:
    result = momentum.macd(df["close"], int(fast), int(slow), int(signal))
    return {col: result[col] for col in result.columns}


@_reg("stoch")
def _stoch(
    df: pd.DataFrame,
    k_period: int = 14,
    d_period: int = 3,
) -> dict[str, pd.Series]:
    result = momentum.stochastic(
        df["high"], df["low"], df["close"], int(k_period), int(d_period)
    )
    return {col: result[col] for col in result.columns}


# ── Volatility ────────────────────────────────────────────────────────────────

@_reg("bb")
def _bb(
    df: pd.DataFrame,
    period: int = 20,
    std: float = 2.0,
) -> dict[str, pd.Series]:
    result = volatility.bollinger_bands(df["close"], int(period), float(std))
    return {col: result[col] for col in result.columns}


@_reg("atr")
def _atr(df: pd.DataFrame, period: int = 14) -> dict[str, pd.Series]:
    return {"atr": volatility.atr(df["high"], df["low"], df["close"], int(period))}


# ── Volume ────────────────────────────────────────────────────────────────────

@_reg("obv")
def _obv(df: pd.DataFrame) -> dict[str, pd.Series]:
    return {"obv": vol_mod.obv(df["close"], df["volume"])}


@_reg("vwap")
def _vwap(df: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        "vwap": vol_mod.vwap(df["high"], df["low"], df["close"], df["volume"])
    }


# ── Public API ────────────────────────────────────────────────────────────────

def list_indicators() -> list[str]:
    """Return sorted list of all registered indicator names."""
    return sorted(_REGISTRY.keys())


def compute(spec: str, df: pd.DataFrame) -> dict[str, pd.Series]:
    """Compute one indicator from a spec string, e.g. 'rsi:7' or 'sma:50'.

    Returns a dict of {column_name: pd.Series} to be merged into the result.
    Raises ValueError for unknown indicator names.
    """
    parts = spec.strip().split(":")
    name = parts[0].lower()
    raw_params = parts[1:]

    fn = _REGISTRY.get(name)
    if fn is None:
        raise ValueError(
            f"Unknown indicator {name!r}. Available: {list_indicators()}"
        )

    # Coerce params: ints unless they contain a decimal point
    params = [float(p) if "." in p else int(p) for p in raw_params]
    return fn(df, *params)
