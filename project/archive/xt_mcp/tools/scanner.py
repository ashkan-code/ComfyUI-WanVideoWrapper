"""MCP tools for the market scanner."""

from __future__ import annotations

import logging

from scanner.scanner import MarketScanner, _MAX_SYMBOLS
from signals.registry import list_strategies
from xt_mcp.clients.spot import XTSpotClient
from xt_mcp.exceptions import XTMCPError

logger = logging.getLogger(__name__)

_DEFAULT_SYMBOLS = [
    "btc_usdt", "eth_usdt", "bnb_usdt", "sol_usdt", "xrp_usdt",
    "ada_usdt", "doge_usdt", "avax_usdt", "dot_usdt", "matic_usdt",
    "link_usdt", "ltc_usdt", "uni_usdt", "atom_usdt", "etc_usdt",
    "xlm_usdt", "algo_usdt", "near_usdt", "trx_usdt", "fil_usdt",
]


def _error(exc: Exception) -> dict:
    logger.error("%s: %s", type(exc).__name__, exc)
    return {"error": True, "code": type(exc).__name__, "message": str(exc)}


async def scan_market(
    symbols: list[str] | None = None,
    strategy: str = "rsi_reversal",
    interval: str = "1h",
    market: str = "spot",
    lookback: int = 200,
    concurrency: int = 5,
    only_with_signals: bool = True,
) -> dict:
    """
    Scan multiple symbols simultaneously using a signal strategy.

    Runs the strategy on each symbol in parallel and returns results ranked
    by signal activity. Useful for finding trading opportunities across the
    market without manually checking each pair.

    Args:
        symbols:           List of trading pairs to scan. Defaults to the top
                           20 liquid spot pairs. Max 50 symbols per call.
        strategy:          Strategy to apply — see list_signal_strategies.
        interval:          Candle interval: '1m','5m','15m','1h','4h','1d'
        market:            'spot' or 'futures'
        lookback:          Historical bars per symbol (max 1000, default 200).
                           Lower = faster scan; higher = better indicator warmup.
        concurrency:       Parallel API requests (1–10, default 5).
        only_with_signals: If True (default), only return symbols that fired
                           at least one signal. Set False to see all results.

    Returns:
        Dict with ranked symbol results, scan summary, and error counts.
    """
    try:
        target_symbols = (symbols or _DEFAULT_SYMBOLS)[:_MAX_SYMBOLS]
        if not target_symbols:
            return {"error": True, "code": "ValueError", "message": "No symbols to scan"}

        capped_concurrency = max(1, min(concurrency, 10))
        scanner = MarketScanner(concurrency=capped_concurrency, lookback=lookback)
        result = await scanner.scan(
            symbols=target_symbols,
            strategy_name=strategy,
            interval=interval,
            market=market,
        )

        if only_with_signals:
            display = result.with_signals()
        else:
            display = result.results

        return {
            "error": False,
            "strategy": result.strategy,
            "interval": result.interval,
            "market": result.market,
            "scanned": result.scanned,
            "succeeded": result.succeeded,
            "failed": result.failed,
            "symbols_with_signals": len(result.with_signals()),
            "elapsed_ms": round(result.elapsed_ms, 1),
            "results": [r.to_dict() for r in display],
        }

    except ValueError as exc:
        return _error(exc)
    except XTMCPError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("scan_market failed")
        return _error(exc)


async def list_scanner_presets() -> dict:
    """
    List available scanner configurations (strategy + interval presets).

    Returns:
        Dict with preset names, descriptions, and default symbol list.
    """
    presets = {
        "momentum_1h":  {"strategy": "combined_momentum", "interval": "1h",  "lookback": 200},
        "rsi_4h":       {"strategy": "rsi_reversal",      "interval": "4h",  "lookback": 300},
        "ema_cross_1d": {"strategy": "ema_cross",         "interval": "1d",  "lookback": 500},
        "breakout_15m": {"strategy": "volume_spike",      "interval": "15m", "lookback": 100},
        "full_1h":      {"strategy": "combined_full",     "interval": "1h",  "lookback": 300},
    }
    return {
        "presets": presets,
        "strategies": list_strategies(),
        "default_symbols": _DEFAULT_SYMBOLS,
        "tip": (
            "Pass preset values to scan_market. "
            "Use 'momentum_1h' for quick trend scans or 'full_1h' for high-confidence signals."
        ),
    }
