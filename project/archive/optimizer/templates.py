"""Strategy factories and default parameter grids for each optimizable template."""

from __future__ import annotations

from typing import Callable

from signals.rules import BBMeanRevertRule, EMACrossRule, MACDCrossRule, RSIRule
from signals.strategy import Strategy


def _build_rsi(params: dict) -> Strategy:
    return Strategy("rsi_opt", [RSIRule(
        period=int(params["period"]),
        buy_level=float(params["buy_level"]),
        sell_level=float(params["sell_level"]),
    )])


def _build_ema_cross(params: dict) -> Strategy:
    fast = int(params["fast"])
    slow = int(params["slow"])
    if fast >= slow:
        raise ValueError(f"fast({fast}) must be < slow({slow})")
    return Strategy("ema_opt", [EMACrossRule(fast=fast, slow=slow)])


def _build_macd(params: dict) -> Strategy:
    fast = int(params["fast"])
    slow = int(params["slow"])
    signal = int(params["signal"])
    if fast >= slow:
        raise ValueError(f"fast({fast}) must be < slow({slow})")
    return Strategy("macd_opt", [MACDCrossRule(fast=fast, slow=slow, signal=signal)])


def _build_bb(params: dict) -> Strategy:
    return Strategy("bb_opt", [BBMeanRevertRule(
        period=int(params["period"]),
        std=float(params["std"]),
    )])


# Registry: template name → {factory, default_grid}
TEMPLATES: dict[str, dict] = {
    "rsi": {
        "factory": _build_rsi,
        "default_grid": {
            "period":    [10, 14, 21],
            "buy_level": [25, 30, 35],
            "sell_level":[65, 70, 75],
        },
        "description": "RSI reversal — tune period, oversold and overbought thresholds",
    },
    "ema_cross": {
        "factory": _build_ema_cross,
        "default_grid": {
            "fast": [5, 9, 12],
            "slow": [20, 26, 50],
        },
        "description": "EMA golden/death cross — tune fast and slow periods",
    },
    "macd": {
        "factory": _build_macd,
        "default_grid": {
            "fast":   [8, 12],
            "slow":   [21, 26],
            "signal": [7, 9],
        },
        "description": "MACD histogram sign change — tune fast, slow, signal periods",
    },
    "bb": {
        "factory": _build_bb,
        "default_grid": {
            "period": [14, 20, 25],
            "std":    [1.5, 2.0, 2.5],
        },
        "description": "Bollinger Bands mean reversion — tune period and std multiplier",
    },
}


def get_template(name: str) -> dict:
    if name not in TEMPLATES:
        raise ValueError(f"Unknown template: {name!r}. Available: {list(TEMPLATES)}")
    return TEMPLATES[name]


def list_templates() -> list[str]:
    return list(TEMPLATES)
