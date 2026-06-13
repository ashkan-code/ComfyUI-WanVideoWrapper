"""MCP tool for walk-forward strategy validation."""

from __future__ import annotations

import logging

from optimizer.templates import get_template
from walk_forward.walk_forward import WalkForwardValidator
from signals.engine import SignalEngine
from xt_mcp.exceptions import XTMCPError

logger = logging.getLogger(__name__)


def _error(exc: Exception) -> dict:
    logger.error("%s: %s", type(exc).__name__, exc)
    return {"error": True, "code": type(exc).__name__, "message": str(exc)}


async def walk_forward_validate(
    symbol: str,
    template: str = "rsi",
    interval: str = "1h",
    market: str = "spot",
    lookback: int = 1000,
    optimize_for: str = "sharpe_ratio",
    n_windows: int = 5,
    train_ratio: float = 0.7,
    initial_capital: float = 10_000.0,
    commission_pct: float = 0.001,
    param_grid: dict | None = None,
) -> dict:
    """
    Validate a strategy with walk-forward optimisation to avoid overfitting.

    Splits historical data into N rolling windows. On each window the parameter
    grid is optimised on the training portion, and the best parameters are then
    backtested on the unseen test portion. Aggregated out-of-sample metrics
    across all windows give a realistic estimate of live performance.

    The overfitting_ratio in the result compares avg in-sample vs out-of-sample
    performance: a ratio near 1.0 is ideal; >> 1 suggests curve-fitting.

    Args:
        symbol:         Trading pair e.g. 'btc_usdt'
        template:       Strategy template: 'rsi' | 'ema_cross' | 'macd' | 'bb'
        interval:       Candle interval: '1m','5m','15m','1h','4h','1d'
        market:         'spot' or 'futures'
        lookback:       Total historical bars (max 1000). Use 1000 for reliable WFO.
        optimize_for:   Metric to maximise in-sample per window:
                        'sharpe_ratio' | 'total_return_pct' | 'win_rate_pct' |
                        'profit_factor' | 'max_drawdown_pct'
        n_windows:      Rolling windows to use (3–10 recommended, max 20).
        train_ratio:    Fraction of each window used for training (0.5–0.9).
        initial_capital:Starting capital per backtest (USD).
        commission_pct: Per-leg commission fraction (default 0.001 = 0.1%).
        param_grid:     Custom parameter ranges. If None, uses template defaults.

    Returns:
        Dict with per-window results, aggregate out-of-sample metrics,
        overfitting ratio, and consistency (% profitable windows).
    """
    try:
        tmpl = get_template(template)
        grid = param_grid or tmpl["default_grid"]

        engine = SignalEngine()
        _, df = await engine.run_with_df(
            symbol=symbol,
            interval=interval,
            strategy_name="rsi_reversal",
            market=market,
            lookback=lookback,
        )

        validator = WalkForwardValidator(
            initial_capital=initial_capital,
            commission_pct=commission_pct,
        )
        result = validator.validate(
            df=df,
            template_name=template,
            param_grid=grid,
            optimize_for=optimize_for,
            n_windows=n_windows,
            train_ratio=train_ratio,
            symbol=symbol,
            interval=interval,
            market=market,
        )

        return {"error": False, **result.to_dict()}

    except ValueError as exc:
        return _error(exc)
    except XTMCPError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("walk_forward_validate failed")
        return _error(exc)
