"""Strategy: combines one or more Rules into a list of Signals via majority vote."""

from __future__ import annotations

import pandas as pd

from signals.models import Signal, SignalType
from signals.rules import Rule


class Strategy:
    """Combines *rules* and generates signals by majority vote.

    A bar triggers a BUY when more rules vote BUY than SELL (and at least one
    votes BUY).  Symmetrically for SELL.  Ties and bars with no votes are
    skipped.  *strength* = fraction of rules that agree with the winning side.
    """

    def __init__(self, name: str, rules: list[Rule]) -> None:
        if not rules:
            raise ValueError("Strategy must have at least one rule")
        self.name = name
        self.rules = rules

    def generate(
        self,
        df: pd.DataFrame,
        symbol: str = "",
        market: str = "spot",
        interval: str = "1h",
    ) -> list[Signal]:
        """Evaluate all rules and return a Signal per bar where consensus exists."""
        if df.empty:
            return []

        evaluations = [rule.evaluate(df) for rule in self.rules]
        signals: list[Signal] = []
        n_rules = len(self.rules)

        for i in range(len(df)):
            votes = [ev.iloc[i] for ev in evaluations]
            buys = sum(1 for v in votes if v == SignalType.BUY)
            sells = sum(1 for v in votes if v == SignalType.SELL)

            if buys > sells:
                sig_type = SignalType.BUY
                strength = buys / n_rules
            elif sells > buys:
                sig_type = SignalType.SELL
                strength = sells / n_rules
            else:
                continue

            row = df.iloc[i]
            signals.append(
                Signal(
                    symbol=symbol,
                    market=market,
                    interval=interval,
                    timestamp=int(row["open_time"]),
                    signal_type=sig_type,
                    strategy=self.name,
                    price=float(row["close"]),
                    strength=strength,
                    metadata={"buy_votes": buys, "sell_votes": sells},
                )
            )

        return signals
