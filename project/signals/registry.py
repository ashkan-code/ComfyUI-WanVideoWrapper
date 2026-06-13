"""Registry of built-in trading strategies.

To add a custom strategy at runtime:
    from signals.registry import register_strategy
    register_strategy("my_strat", Strategy("my_strat", [MyRule()]))
"""

from __future__ import annotations

from signals.rules import BBMeanRevertRule, EMACrossRule, MACDCrossRule, RSIRule, VolumeSpikeRule
from signals.strategy import Strategy

_REGISTRY: dict[str, Strategy] = {}


def _build_defaults() -> None:
    _REGISTRY["rsi_reversal"] = Strategy(
        "rsi_reversal",
        [RSIRule(period=14, buy_level=30, sell_level=70)],
    )
    _REGISTRY["rsi_aggressive"] = Strategy(
        "rsi_aggressive",
        [RSIRule(period=14, buy_level=40, sell_level=60)],
    )
    _REGISTRY["ema_cross"] = Strategy(
        "ema_cross",
        [EMACrossRule(fast=9, slow=21)],
    )
    _REGISTRY["ema_cross_50_200"] = Strategy(
        "ema_cross_50_200",
        [EMACrossRule(fast=50, slow=200)],
    )
    _REGISTRY["macd_cross"] = Strategy(
        "macd_cross",
        [MACDCrossRule()],
    )
    _REGISTRY["bb_mean_revert"] = Strategy(
        "bb_mean_revert",
        [BBMeanRevertRule()],
    )
    _REGISTRY["volume_spike"] = Strategy(
        "volume_spike",
        [VolumeSpikeRule(period=20, multiplier=2.0)],
    )
    _REGISTRY["combined_momentum"] = Strategy(
        "combined_momentum",
        [RSIRule(), MACDCrossRule(), EMACrossRule()],
    )
    _REGISTRY["combined_full"] = Strategy(
        "combined_full",
        [RSIRule(), MACDCrossRule(), EMACrossRule(), BBMeanRevertRule(), VolumeSpikeRule()],
    )


_build_defaults()


def list_strategies() -> list[str]:
    return sorted(_REGISTRY.keys())


def get_strategy(name: str) -> Strategy:
    strat = _REGISTRY.get(name)
    if strat is None:
        raise ValueError(
            f"Unknown strategy {name!r}. Available: {list_strategies()}"
        )
    return strat


def register_strategy(name: str, strategy: Strategy) -> None:
    _REGISTRY[name] = strategy
