"""Long-only backtesting engine."""

from __future__ import annotations

import pandas as pd

from backtesting.metrics import compute_metrics
from backtesting.models import BacktestResult, Trade
from signals.models import Signal, SignalType


class Backtester:
    """Simulates long-only trading on historical OHLCV data driven by Signal objects."""

    def __init__(
        self,
        initial_capital: float = 10_000.0,
        commission_pct: float = 0.001,
    ) -> None:
        if initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if not (0.0 <= commission_pct < 1.0):
            raise ValueError("commission_pct must be in [0, 1)")
        self.initial_capital = initial_capital
        self.commission_pct = commission_pct

    def run(
        self,
        df: pd.DataFrame,
        signals: list[Signal],
        symbol: str = "",
        interval: str = "",
        strategy: str = "",
        market: str = "spot",
    ) -> BacktestResult:
        if df.empty or not signals:
            return BacktestResult(
                symbol=symbol,
                interval=interval,
                strategy=strategy,
                market=market,
                initial_capital=self.initial_capital,
                final_capital=self.initial_capital,
                trades=[],
                equity_curve=[self.initial_capital] * max(1, len(df)),
                metrics=compute_metrics([], [self.initial_capital], self.initial_capital),
            )

        signal_map: dict[int, SignalType] = {s.timestamp: s.signal_type for s in signals}

        capital = self.initial_capital
        position: float = 0.0   # units held
        entry_price: float = 0.0
        entry_time: int = 0

        trades: list[Trade] = []
        equity_curve: list[float] = []

        for _, row in df.iterrows():
            t = int(row["open_time"])
            close = float(row["close"])
            sig = signal_map.get(t)

            if sig == SignalType.BUY and position == 0.0 and capital > 0.0:
                cost = capital * (1.0 - self.commission_pct)
                position = cost / close
                entry_price = close
                entry_time = t
                capital = 0.0

            elif sig == SignalType.SELL and position > 0.0:
                proceeds = position * close * (1.0 - self.commission_pct)
                pnl = proceeds - (position * entry_price * (1.0 + self.commission_pct))
                pnl_pct = (close / entry_price - 1.0) * 100.0
                trades.append(Trade(
                    entry_time=entry_time,
                    exit_time=t,
                    entry_price=entry_price,
                    exit_price=close,
                    direction="LONG",
                    pnl=round(pnl, 8),
                    pnl_pct=round(pnl_pct, 6),
                ))
                capital = proceeds
                position = 0.0

            current_equity = capital + position * close
            equity_curve.append(current_equity)

        # Close open position at last bar
        if position > 0.0 and not df.empty:
            last_close = float(df.iloc[-1]["close"])
            last_time = int(df.iloc[-1]["open_time"])
            proceeds = position * last_close * (1.0 - self.commission_pct)
            pnl = proceeds - (position * entry_price * (1.0 + self.commission_pct))
            pnl_pct = (last_close / entry_price - 1.0) * 100.0
            trades.append(Trade(
                entry_time=entry_time,
                exit_time=last_time,
                entry_price=entry_price,
                exit_price=last_close,
                direction="LONG",
                pnl=round(pnl, 8),
                pnl_pct=round(pnl_pct, 6),
            ))
            capital = proceeds
            equity_curve[-1] = capital

        final_capital = equity_curve[-1] if equity_curve else self.initial_capital
        metrics = compute_metrics(trades, equity_curve, self.initial_capital)

        return BacktestResult(
            symbol=symbol,
            interval=interval,
            strategy=strategy,
            market=market,
            initial_capital=self.initial_capital,
            final_capital=round(final_capital, 4),
            trades=trades,
            equity_curve=[round(e, 4) for e in equity_curve],
            metrics=metrics,
        )
