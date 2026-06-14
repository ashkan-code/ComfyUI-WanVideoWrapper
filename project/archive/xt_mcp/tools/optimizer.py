"""MCP tools for strategy parameter optimization."""

from __future__ import annotations

import logging

from optimizer.optimizer import StrategyOptimizer
from optimizer.templates import TEMPLATES, get_template, list_templates
from signals.engine import SignalEngine
from xt_mcp.exceptions import XTMCPError

logger = logging.getLogger(__name__)


def _error(exc: Exception) -> dict:
    logger.error("%s: %s", type(exc).__name__, exc)
    return {"error": True, "code": type(exc).__name__, "message": str(exc)}


async def optimize_strategy(
    symbol: str,
    template: str = "rsi",
    interval: str = "1h",
    market: str = "spot",
    lookback: int = 500,
    optimize_for: str = "sharpe_ratio",
    initial_capital: float = 10_000.0,
    commission_pct: float = 0.001,
    param_grid: dict | None = None,
    top_n: int = 10,
) -> dict:
    """
    Find the best parameters for a signal strategy via grid search + backtesting.

    Fetches historical candles once, then iterates over every combination of
    parameter values, backtests each combination, and returns results ranked by
    the chosen metric.

    Args:
        symbol:         Trading pair e.g. 'btc_usdt'
        template:       Strategy type to optimise: 'rsi' | 'ema_cross' | 'macd' | 'bb'
        interval:       Candle interval: '1m','5m','15m','1h','4h','1d'
        market:         'spot' or 'futures'
        lookback:       Historical bars (max 1000). Use ≥ 300 for reliable results.
        optimize_for:   Metric to maximise: 'sharpe_ratio' | 'total_return_pct' |
                        'win_rate_pct' | 'profit_factor' | 'max_drawdown_pct'
                        (max_drawdown_pct is minimised, not maximised)
        initial_capital:Starting capital in USD.
        commission_pct: Per-leg commission fraction (default 0.001 = 0.1%).
        param_grid:     Custom parameter grid as a dict of lists, e.g.
                        {"period": [10,14,21], "buy_level": [25,30], "sell_level": [70,75]}.
                        If omitted, the template's built-in default grid is used.
                        Max 100 total combinations (cartesian product is capped).
        top_n:          How many top results to include in the response (default 10).

    Returns:
        Dict with best params, top_n results, trial count, and elapsed time.

    Examples:
        optimize_strategy("btc_usdt", template="rsi", interval="4h")
        optimize_strategy("eth_usdt", template="ema_cross", optimize_for="total_return_pct")
        optimize_strategy("btc_usdt", template="rsi", param_grid={"period":[7,14],"buy_level":[20,30],"sell_level":[70,80]})
    """
    try:
        tmpl = get_template(template)
        grid = param_grid or tmpl["default_grid"]
        factory = tmpl["factory"]

        engine = SignalEngine()
        _, df = await engine.run_with_df(
            symbol=symbol,
            interval=interval,
            strategy_name="rsi_reversal",   # strategy name irrelevant — only df needed
            market=market,
            lookback=lookback,
        )

        optimizer = StrategyOptimizer(
            initial_capital=initial_capital,
            commission_pct=commission_pct,
        )
        result = optimizer.optimize(
            df=df,
            factory=factory,
            param_grid=grid,
            symbol=symbol,
            interval=interval,
            market=market,
            template=template,
            optimize_for=optimize_for,
        )

        return {
            "error": False,
            **result.to_dict(top_n=top_n),
        }

    except ValueError as exc:
        return _error(exc)
    except XTMCPError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("optimize_strategy failed")
        return _error(exc)


async def list_optimization_templates() -> dict:
    """
    List available strategy templates and their optimisable parameters.

    Returns:
        Dict with template names, descriptions, and default parameter grids.
    """
    return {
        "templates": {
            name: {
                "description": info["description"],
                "default_grid": info["default_grid"],
                "param_count": sum(len(v) for v in info["default_grid"].values()),
            }
            for name, info in TEMPLATES.items()
        },
        "optimize_for_options": [
            "sharpe_ratio", "total_return_pct", "win_rate_pct",
            "profit_factor", "max_drawdown_pct",
        ],
        "tip": (
            "Use 'sharpe_ratio' to find risk-adjusted performance. "
            "Use 'total_return_pct' for maximum raw profit. "
            "Custom param_grid overrides the default grid — keep combinations ≤ 100."
        ),
    }
