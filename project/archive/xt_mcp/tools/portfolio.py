"""MCP tools for portfolio correlation and multi-symbol backtesting."""

from __future__ import annotations

import asyncio
import logging

import pandas as pd

from portfolio.cointegration import analyze_pair, find_cointegrated_pairs
from portfolio.correlation import compute_correlation
from portfolio.portfolio_backtest import PortfolioBacktester
from signals.engine import SignalEngine
from signals.registry import get_strategy
from xt_mcp.exceptions import XTMCPError

logger = logging.getLogger(__name__)

_MAX_SYMBOLS = 20   # cap for portfolio tools (heavier than scanner)


def _error(exc: Exception) -> dict:
    logger.error("%s: %s", type(exc).__name__, exc)
    return {"error": True, "code": type(exc).__name__, "message": str(exc)}


async def _fetch_close_series(
    symbols: list[str],
    interval: str,
    market: str,
    lookback: int,
    concurrency: int = 5,
) -> dict[str, pd.Series]:
    """Fetch close price Series for each symbol concurrently."""
    engine = SignalEngine()
    semaphore = asyncio.Semaphore(concurrency)

    async def _one(sym: str) -> tuple[str, pd.Series | None]:
        async with semaphore:
            try:
                _, df = await engine.run_with_df(
                    symbol=sym, interval=interval,
                    strategy_name="rsi_reversal",
                    market=market, lookback=lookback,
                )
                return sym, df["close"].reset_index(drop=True) if not df.empty else None
            except Exception as exc:
                logger.warning("fetch_close %s: %s", sym, exc)
                return sym, None

    results = await asyncio.gather(*[_one(s) for s in symbols])
    return {sym: series for sym, series in results if series is not None}


async def get_correlation_matrix(
    symbols: list[str] | None = None,
    interval: str = "1h",
    market: str = "spot",
    lookback: int = 200,
    method: str = "returns",
    top_n: int = 5,
) -> dict:
    """
    Compute the return correlation matrix across multiple symbols.

    Args:
        symbols:  List of trading pairs (max 20). Defaults to BTC, ETH, BNB, SOL, XRP.
        interval: Candle interval: '1m','5m','15m','1h','4h','1d'
        market:   'spot' or 'futures'
        lookback: Historical bars per symbol (max 1000).
        method:   'returns' — correlate % returns (recommended) |
                  'prices'  — correlate raw price levels.
        top_n:    How many top/least-correlated pairs to highlight.

    Returns:
        Full correlation matrix, top correlated pairs (best for trend following),
        and most uncorrelated pairs (best for diversification).
    """
    try:
        target = (symbols or ["btc_usdt", "eth_usdt", "bnb_usdt", "sol_usdt", "xrp_usdt"])
        target = target[:_MAX_SYMBOLS]

        price_dict = await _fetch_close_series(target, interval, market, lookback)
        if len(price_dict) < 2:
            return _error(ValueError("Need at least 2 symbols with valid data"))

        result = compute_correlation(price_dict, method=method, top_n=top_n)
        return {"error": False, **result.to_dict()}

    except ValueError as exc:
        return _error(exc)
    except XTMCPError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("get_correlation_matrix failed")
        return _error(exc)


async def find_pairs(
    symbols: list[str] | None = None,
    interval: str = "1d",
    market: str = "spot",
    lookback: int = 200,
    significance: str = "5%",
) -> dict:
    """
    Test all symbol pairs for cointegration (pairs trading candidates).

    Uses an Engle-Granger style ADF test on the OLS residual spread between
    each pair. Cointegrated pairs move together long-term and diverge
    predictably — ideal for mean-reversion strategies.

    Args:
        symbols:      Symbols to test (max 10, so max 45 pairs). Defaults to
                      BTC, ETH, BNB, SOL, XRP, ADA, DOGE, AVAX, DOT, LINK.
        interval:     Candle interval — use '1d' or '4h' for cointegration.
        market:       'spot' or 'futures'
        lookback:     Historical bars (≥ 100 recommended for reliable ADF).
        significance: ADF significance level: '1%' | '5%' | '10%'

    Returns:
        All pairs sorted by ADF stat (most stationary first), with
        cointegrated pairs flagged and their hedge ratios.
    """
    try:
        defaults = [
            "btc_usdt", "eth_usdt", "bnb_usdt", "sol_usdt", "xrp_usdt",
            "ada_usdt", "doge_usdt", "avax_usdt", "dot_usdt", "link_usdt",
        ]
        target = (symbols or defaults)[:10]   # max 10 → 45 pairs

        price_dict = await _fetch_close_series(target, interval, market, lookback)
        if len(price_dict) < 2:
            return _error(ValueError("Need at least 2 symbols with valid data"))

        pairs = find_cointegrated_pairs(price_dict, significance=significance)
        coint = [p for p in pairs if p.cointegrated]

        return {
            "error": False,
            "symbols_tested": list(price_dict.keys()),
            "total_pairs": len(pairs),
            "cointegrated_pairs": len(coint),
            "significance": significance,
            "results": [p.to_dict() for p in pairs],
        }

    except ValueError as exc:
        return _error(exc)
    except XTMCPError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("find_pairs failed")
        return _error(exc)


async def portfolio_backtest(
    symbols: list[str] | None = None,
    strategy: str = "rsi_reversal",
    interval: str = "1h",
    market: str = "spot",
    lookback: int = 500,
    initial_capital: float = 10_000.0,
    commission_pct: float = 0.001,
) -> dict:
    """
    Backtest a signal strategy across multiple symbols with equal capital allocation.

    Capital is divided equally among all symbols. Results include per-symbol
    performance breakdown and a portfolio-level summary.

    Args:
        symbols:         List of pairs to include (max 20). Defaults to top 5.
        strategy:        Strategy to apply — see list_signal_strategies.
        interval:        Candle interval: '1m','5m','15m','1h','4h','1d'
        market:          'spot' or 'futures'
        lookback:        Historical bars per symbol (max 1000).
        initial_capital: Total portfolio capital in USD (split equally).
        commission_pct:  Per-leg commission fraction (default 0.001 = 0.1%).

    Returns:
        Per-symbol metrics, portfolio summary (total return, avg Sharpe,
        best/worst symbol), and list of profitable symbols.
    """
    try:
        defaults = ["btc_usdt", "eth_usdt", "bnb_usdt", "sol_usdt", "xrp_usdt"]
        target = (symbols or defaults)[:_MAX_SYMBOLS]

        get_strategy(strategy)   # validate early

        engine = SignalEngine()
        semaphore = asyncio.Semaphore(5)

        async def _fetch_one(sym: str):
            async with semaphore:
                try:
                    signals, df = await engine.run_with_df(
                        symbol=sym, interval=interval,
                        strategy_name=strategy,
                        market=market, lookback=lookback,
                    )
                    return sym, df, signals
                except Exception as exc:
                    logger.warning("portfolio_backtest fetch %s: %s", sym, exc)
                    return sym, pd.DataFrame(), []

        fetched = await asyncio.gather(*[_fetch_one(s) for s in target])

        symbol_dfs = {sym: df for sym, df, _ in fetched if not df.empty}
        symbol_signals = {sym: sigs for sym, _, sigs in fetched}

        if not symbol_dfs:
            return _error(ValueError("No valid data fetched for any symbol"))

        bt = PortfolioBacktester(
            initial_capital=initial_capital,
            commission_pct=commission_pct,
        )
        result = bt.run(
            symbol_dfs=symbol_dfs,
            symbol_signals=symbol_signals,
            strategy=strategy,
            interval=interval,
            market=market,
        )
        return {"error": False, **result.to_dict()}

    except ValueError as exc:
        return _error(exc)
    except XTMCPError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("portfolio_backtest failed")
        return _error(exc)
