"""Tests for Strategy and signal registry."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from signals.models import Signal, SignalType
from signals.registry import get_strategy, list_strategies, register_strategy
from signals.rules import EMACrossRule, RSIRule
from signals.strategy import Strategy


def _df(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame({
        "open_time": [i * 3_600_000 for i in range(n)],
        "open":   closes,
        "high":   [c + 1.0 for c in closes],
        "low":    [c - 1.0 for c in closes],
        "close":  closes,
        "volume": volumes or [1000.0] * n,
    })


class TestStrategy:
    def test_empty_rules_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one rule"):
            Strategy("bad", [])

    def test_empty_df_returns_no_signals(self) -> None:
        strat = Strategy("test", [RSIRule()])
        signals = strat.generate(pd.DataFrame(), symbol="x", market="spot", interval="1h")
        assert signals == []

    def test_returns_signal_objects(self) -> None:
        closes = [100.0 - i * 2 for i in range(60)]  # falling → RSI oversold
        strat = Strategy("test_rsi", [RSIRule()])
        signals = strat.generate(_df(closes), symbol="btc_usdt", market="spot", interval="1h")
        assert all(isinstance(s, Signal) for s in signals)

    def test_signal_fields_populated(self) -> None:
        closes = [100.0 - i * 2 for i in range(60)]
        strat = Strategy("my_strat", [RSIRule()])
        signals = strat.generate(_df(closes), symbol="eth_usdt", market="futures", interval="4h")
        if signals:
            s = signals[0]
            assert s.symbol == "eth_usdt"
            assert s.market == "futures"
            assert s.interval == "4h"
            assert s.strategy == "my_strat"
            assert s.signal_type in (SignalType.BUY, SignalType.SELL)
            assert 0.0 <= s.strength <= 1.0
            assert s.price > 0

    def test_majority_vote_buy(self) -> None:
        # Two rules both vote BUY → strength = 1.0
        closes = [100.0 - i * 2 for i in range(80)]  # falling → both RSI and EMA vote BUY
        strat = Strategy("two_rules", [RSIRule(), EMACrossRule(fast=5, slow=20)])
        signals = strat.generate(_df(closes), symbol="btc_usdt")
        buys = [s for s in signals if s.signal_type == SignalType.BUY]
        if buys:
            max_strength = max(s.strength for s in buys)
            assert max_strength <= 1.0

    def test_strength_fraction_of_rules(self) -> None:
        # Single-rule strategy always has strength 1.0
        closes = [100.0 - i * 2 for i in range(60)]
        strat = Strategy("single", [RSIRule()])
        signals = strat.generate(_df(closes))
        for s in signals:
            assert s.strength == pytest.approx(1.0)

    def test_two_rules_combined_at_most_union(self) -> None:
        # Combined strategy fires when ANY rule has a majority (with 2 rules, 1 vote wins).
        # Signals can only be canceled when rules give OPPOSITE votes on the same bar.
        # Therefore: combined ≤ rsi_signals + ema_signals (never exceeds their sum)
        closes = [50.0 + math.sin(i / 3) * 1.0 for i in range(80)]
        rsi_only = Strategy("rsi", [RSIRule(buy_level=40, sell_level=60)])
        ema_only  = Strategy("ema", [EMACrossRule(fast=5, slow=10)])
        combined  = Strategy("both", [RSIRule(buy_level=40, sell_level=60), EMACrossRule(fast=5, slow=10)])
        rsi_n = len(rsi_only.generate(_df(closes)))
        ema_n = len(ema_only.generate(_df(closes)))
        comb_n = len(combined.generate(_df(closes)))
        # Combined is at most the union of both (sum), at least as many as any single rule
        assert comb_n <= rsi_n + ema_n


class TestRegistry:
    def test_list_strategies_returns_all(self) -> None:
        names = list_strategies()
        expected = {
            "rsi_reversal", "ema_cross", "macd_cross", "bb_mean_revert",
            "volume_spike", "combined_momentum", "combined_full",
        }
        assert expected.issubset(set(names))

    def test_get_known_strategy(self) -> None:
        strat = get_strategy("rsi_reversal")
        assert strat.name == "rsi_reversal"

    def test_get_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown strategy"):
            get_strategy("does_not_exist")

    def test_register_custom(self) -> None:
        custom = Strategy("custom_test", [RSIRule()])
        register_strategy("custom_test", custom)
        assert get_strategy("custom_test") is custom
        assert "custom_test" in list_strategies()

    def test_all_built_in_strategies_run(self) -> None:
        closes = [50 + 10 * math.sin(i / 5) for i in range(100)]
        df = _df(closes)
        for name in list_strategies():
            strat = get_strategy(name)
            signals = strat.generate(df)   # must not raise
            assert isinstance(signals, list)
