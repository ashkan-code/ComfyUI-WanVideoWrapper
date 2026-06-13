"""Vectorised candlestick pattern detectors (pure numpy/pandas)."""

from __future__ import annotations

import numpy as np
import pandas as pd


# ── primitive helpers ─────────────────────────────────────────────────────────


def _body(o: np.ndarray, c: np.ndarray) -> np.ndarray:
    return np.abs(c - o)


def _rng(h: np.ndarray, l: np.ndarray) -> np.ndarray:
    return h - l


def _upper_shadow(h: np.ndarray, o: np.ndarray, c: np.ndarray) -> np.ndarray:
    return h - np.maximum(o, c)


def _lower_shadow(o: np.ndarray, c: np.ndarray, l: np.ndarray) -> np.ndarray:
    return np.minimum(o, c) - l


# ── single-bar patterns ───────────────────────────────────────────────────────


def detect_doji(df: pd.DataFrame, threshold: float = 0.1) -> np.ndarray:
    """Body < threshold × full range → indecision."""
    o, c, h, l = df["open"].values, df["close"].values, df["high"].values, df["low"].values
    body = _body(o, c)
    rng  = _rng(h, l)
    safe_rng = np.where(rng > 0, rng, np.nan)
    return (rng > 0) & (body / safe_rng < threshold)


def detect_hammer(df: pd.DataFrame) -> np.ndarray:
    """Lower shadow ≥ 2× body, upper shadow ≤ ½ body — bullish reversal."""
    o, c, h, l = df["open"].values, df["close"].values, df["high"].values, df["low"].values
    body  = _body(o, c)
    lower = _lower_shadow(o, c, l)
    upper = _upper_shadow(h, o, c)
    return (body > 0) & (lower >= 2.0 * body) & (upper <= 0.5 * body)


def detect_shooting_star(df: pd.DataFrame) -> np.ndarray:
    """Upper shadow ≥ 2× body, lower shadow ≤ ½ body — bearish reversal."""
    o, c, h, l = df["open"].values, df["close"].values, df["high"].values, df["low"].values
    body  = _body(o, c)
    upper = _upper_shadow(h, o, c)
    lower = _lower_shadow(o, c, l)
    return (body > 0) & (upper >= 2.0 * body) & (lower <= 0.5 * body)


# ── two-bar patterns ──────────────────────────────────────────────────────────


def detect_bullish_engulfing(df: pd.DataFrame) -> np.ndarray:
    """Green body fully engulfs preceding red body — bullish reversal."""
    o, c = df["open"].values, df["close"].values
    prev_o, prev_c = np.roll(o, 1), np.roll(c, 1)
    prev_bearish = prev_c < prev_o
    curr_bullish = c > o
    engulfs = (o <= prev_c) & (c >= prev_o)
    result = prev_bearish & curr_bullish & engulfs
    result[0] = False
    return result


def detect_bearish_engulfing(df: pd.DataFrame) -> np.ndarray:
    """Red body fully engulfs preceding green body — bearish reversal."""
    o, c = df["open"].values, df["close"].values
    prev_o, prev_c = np.roll(o, 1), np.roll(c, 1)
    prev_bullish = prev_c > prev_o
    curr_bearish = c < o
    engulfs = (o >= prev_c) & (c <= prev_o)
    result = prev_bullish & curr_bearish & engulfs
    result[0] = False
    return result


# ── three-bar patterns ────────────────────────────────────────────────────────


def _small_body_mask(
    o: np.ndarray, c: np.ndarray, h: np.ndarray, l: np.ndarray,
    threshold: float,
) -> np.ndarray:
    body = _body(o, c)
    rng  = _rng(h, l)
    safe = np.where(rng > 0, rng, np.nan)
    return (rng > 0) & (body / safe < threshold)


def detect_morning_star(
    df: pd.DataFrame, small_body_threshold: float = 0.3
) -> np.ndarray:
    """Bearish → small-body indecision → bullish closing above bar-0 midpoint."""
    o, c, h, l = df["open"].values, df["close"].values, df["high"].values, df["low"].values
    small = _small_body_mask(o, c, h, l, small_body_threshold)
    result = np.zeros(len(df), dtype=bool)
    for i in range(2, len(df)):
        bar2_bearish  = c[i - 2] < o[i - 2]
        bar1_small    = small[i - 1]
        bar0_bullish  = c[i] > o[i]
        midpoint      = (o[i - 2] + c[i - 2]) / 2.0
        closes_above  = c[i] > midpoint
        result[i] = bar2_bearish and bar1_small and bar0_bullish and closes_above
    return result


def detect_evening_star(
    df: pd.DataFrame, small_body_threshold: float = 0.3
) -> np.ndarray:
    """Bullish → small-body indecision → bearish closing below bar-0 midpoint."""
    o, c, h, l = df["open"].values, df["close"].values, df["high"].values, df["low"].values
    small = _small_body_mask(o, c, h, l, small_body_threshold)
    result = np.zeros(len(df), dtype=bool)
    for i in range(2, len(df)):
        bar2_bullish  = c[i - 2] > o[i - 2]
        bar1_small    = small[i - 1]
        bar0_bearish  = c[i] < o[i]
        midpoint      = (o[i - 2] + c[i - 2]) / 2.0
        closes_below  = c[i] < midpoint
        result[i] = bar2_bullish and bar1_small and bar0_bearish and closes_below
    return result


# ── registry ──────────────────────────────────────────────────────────────────


PATTERN_BIAS: dict[str, str] = {
    "doji":              "neutral",
    "hammer":            "bullish",
    "shooting_star":     "bearish",
    "bullish_engulfing": "bullish",
    "bearish_engulfing": "bearish",
    "morning_star":      "bullish",
    "evening_star":      "bearish",
}

DETECTORS: dict[str, object] = {
    "doji":              detect_doji,
    "hammer":            detect_hammer,
    "shooting_star":     detect_shooting_star,
    "bullish_engulfing": detect_bullish_engulfing,
    "bearish_engulfing": detect_bearish_engulfing,
    "morning_star":      detect_morning_star,
    "evening_star":      detect_evening_star,
}


def detect_all(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """Return {pattern_name: boolean_array} for every registered detector."""
    return {name: fn(df) for name, fn in DETECTORS.items()}   # type: ignore[operator]
