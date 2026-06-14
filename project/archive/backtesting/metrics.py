"""Performance metrics computation for backtest results."""

from __future__ import annotations

import math

from backtesting.models import Trade


def compute_metrics(
    trades: list[Trade],
    equity_curve: list[float],
    initial_capital: float,
) -> dict:
    if not trades:
        return {
            "total_return_pct": 0.0,
            "num_trades": 0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "avg_trade_pct": 0.0,
            "best_trade_pct": 0.0,
            "worst_trade_pct": 0.0,
        }

    final_capital = equity_curve[-1] if equity_curve else initial_capital
    total_return_pct = (final_capital - initial_capital) / initial_capital * 100.0

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    win_rate_pct = len(wins) / len(trades) * 100.0

    gross_profit = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    max_drawdown_pct = _max_drawdown(equity_curve)
    sharpe = _sharpe_ratio(equity_curve)

    pnls = [t.pnl_pct for t in trades]
    avg_trade_pct = sum(pnls) / len(pnls)
    best_trade_pct = max(pnls)
    worst_trade_pct = min(pnls)

    return {
        "total_return_pct": round(total_return_pct, 4),
        "num_trades": len(trades),
        "win_rate_pct": round(win_rate_pct, 4),
        "profit_factor": round(profit_factor, 4) if math.isfinite(profit_factor) else None,
        "max_drawdown_pct": round(max_drawdown_pct, 4),
        "sharpe_ratio": round(sharpe, 4),
        "gross_profit": round(gross_profit, 4),
        "gross_loss": round(gross_loss, 4),
        "avg_trade_pct": round(avg_trade_pct, 4),
        "best_trade_pct": round(best_trade_pct, 4),
        "worst_trade_pct": round(worst_trade_pct, 4),
    }


def _max_drawdown(equity_curve: list[float]) -> float:
    if len(equity_curve) < 2:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for val in equity_curve:
        if val > peak:
            peak = val
        dd = (peak - val) / peak * 100.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _sharpe_ratio(equity_curve: list[float], risk_free: float = 0.0) -> float:
    if len(equity_curve) < 2:
        return 0.0
    returns = [
        (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
        for i in range(1, len(equity_curve))
    ]
    n = len(returns)
    mean_r = sum(returns) / n
    variance = sum((r - mean_r) ** 2 for r in returns) / n
    std_r = math.sqrt(variance)
    if std_r == 0.0:
        return 0.0
    return (mean_r - risk_free) / std_r * math.sqrt(n)
