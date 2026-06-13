"""Portfolio-level backtesting: equal-weight allocation across multiple symbols."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

from backtesting.engine import Backtester
from backtesting.metrics import compute_metrics
from signals.models import Signal

logger = logging.getLogger(__name__)


@dataclass
class PortfolioResult:
    symbols: list[str]
    strategy: str
    interval: str
    market: str
    initial_capital: float
    final_capital: float
    portfolio_return_pct: float
    per_symbol: dict[str, dict]      # symbol → {metrics, trades, final_capital}
    portfolio_metrics: dict
    equity_curve: list[float]        # portfolio-level (sum of all positions)
    elapsed_symbols: int

    def to_dict(self) -> dict:
        return {
            "symbols": self.symbols,
            "strategy": self.strategy,
            "interval": self.interval,
            "market": self.market,
            "initial_capital": self.initial_capital,
            "final_capital": round(self.final_capital, 4),
            "portfolio_return_pct": round(self.portfolio_return_pct, 4),
            "portfolio_metrics": self.portfolio_metrics,
            "per_symbol": self.per_symbol,
            "equity_curve_length": len(self.equity_curve),
            "elapsed_symbols": self.elapsed_symbols,
        }


class PortfolioBacktester:
    """Runs a backtest across N symbols with equal capital allocation."""

    def __init__(
        self,
        initial_capital: float = 10_000.0,
        commission_pct: float = 0.001,
    ) -> None:
        self.initial_capital = initial_capital
        self.commission_pct = commission_pct

    def run(
        self,
        symbol_dfs: dict[str, pd.DataFrame],
        symbol_signals: dict[str, list[Signal]],
        strategy: str = "",
        interval: str = "",
        market: str = "spot",
    ) -> PortfolioResult:
        """Run equal-weight backtest across all symbols.

        Each symbol gets `initial_capital / N` capital. Equity curves are
        summed bar-by-bar to produce the portfolio equity curve.

        Args:
            symbol_dfs:     Mapping of symbol → OHLCV DataFrame.
            symbol_signals: Mapping of symbol → list of Signal objects.
        """
        symbols = list(symbol_dfs.keys())
        n = len(symbols)
        if n == 0:
            raise ValueError("symbol_dfs is empty")

        per_symbol_capital = self.initial_capital / n
        backtester = Backtester(
            initial_capital=per_symbol_capital,
            commission_pct=self.commission_pct,
        )

        per_symbol: dict[str, dict] = {}
        equity_curves: list[list[float]] = []

        for sym in symbols:
            df = symbol_dfs[sym]
            signals = symbol_signals.get(sym, [])
            try:
                result = backtester.run(
                    df=df, signals=signals,
                    symbol=sym, interval=interval,
                    strategy=strategy, market=market,
                )
                per_symbol[sym] = {
                    "final_capital": result.final_capital,
                    "return_pct": result.metrics.get("total_return_pct", 0.0),
                    "num_trades": len(result.trades),
                    "sharpe_ratio": result.metrics.get("sharpe_ratio", 0.0),
                    "max_drawdown_pct": result.metrics.get("max_drawdown_pct", 0.0),
                    "win_rate_pct": result.metrics.get("win_rate_pct", 0.0),
                }
                equity_curves.append(result.equity_curve)
            except Exception as exc:
                logger.warning("Portfolio backtest failed for %s: %s", sym, exc)
                per_symbol[sym] = {"error": str(exc)}
                equity_curves.append([per_symbol_capital])

        # Sum equity curves aligned to minimum length
        min_len = min(len(c) for c in equity_curves)
        portfolio_curve = [
            sum(c[i] for c in equity_curves)
            for i in range(min_len)
        ]

        final_capital = portfolio_curve[-1] if portfolio_curve else self.initial_capital
        ret_pct = (final_capital - self.initial_capital) / self.initial_capital * 100.0
        portfolio_metrics = _portfolio_metrics(per_symbol, final_capital, self.initial_capital)

        return PortfolioResult(
            symbols=symbols,
            strategy=strategy,
            interval=interval,
            market=market,
            initial_capital=self.initial_capital,
            final_capital=round(final_capital, 4),
            portfolio_return_pct=round(ret_pct, 4),
            per_symbol=per_symbol,
            portfolio_metrics=portfolio_metrics,
            equity_curve=[round(v, 4) for v in portfolio_curve],
            elapsed_symbols=len([s for s in per_symbol if "error" not in per_symbol[s]]),
        )


def _portfolio_metrics(per_symbol: dict[str, dict], final_capital: float, initial_capital: float) -> dict:
    valid = [v for v in per_symbol.values() if "error" not in v]
    if not valid:
        return {}

    returns = [v["return_pct"] for v in valid]
    total_return = (final_capital - initial_capital) / initial_capital * 100.0
    avg_symbol_return = sum(returns) / len(returns)
    best = max(valid, key=lambda v: v["return_pct"])
    worst = min(valid, key=lambda v: v["return_pct"])
    profitable = sum(1 for v in valid if v["return_pct"] > 0)

    return {
        "total_portfolio_return_pct": round(total_return, 4),
        "avg_symbol_return_pct": round(avg_symbol_return, 4),
        "best_symbol_return_pct": round(best["return_pct"], 4),
        "worst_symbol_return_pct": round(worst["return_pct"], 4),
        "profitable_symbols": profitable,
        "total_symbols": len(valid),
        "avg_sharpe": round(sum(v.get("sharpe_ratio", 0) or 0 for v in valid) / len(valid), 4),
        "avg_max_drawdown": round(sum(v.get("max_drawdown_pct", 0) for v in valid) / len(valid), 4),
    }
