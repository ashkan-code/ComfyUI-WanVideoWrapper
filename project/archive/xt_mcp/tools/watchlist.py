"""MCP tools for symbol watchlist and signal alerts."""

from __future__ import annotations

import logging
import time

from signals.engine import SignalEngine
from watchlist.manager import WatchlistManager
from xt_mcp.exceptions import XTMCPError

logger = logging.getLogger(__name__)


def _error(exc: Exception) -> dict:
    logger.error("%s: %s", type(exc).__name__, exc)
    return {"error": True, "code": type(exc).__name__, "message": str(exc)}


async def add_to_watchlist(
    symbol: str,
    strategy: str,
    interval: str = "1h",
    market: str = "spot",
) -> dict:
    """
    Add a symbol+strategy pair to the watchlist.

    Args:
        symbol:   Trading pair e.g. 'btc_usdt'.
        strategy: Signal strategy name — see list_signal_strategies.
        interval: Candle interval (default '1h').
        market:   'spot' or 'futures' (default 'spot').

    Returns:
        The created watchlist entry or an error if it already exists.
    """
    try:
        mgr = WatchlistManager()
        entry = mgr.add(symbol, strategy, interval, market)
        return {"error": False, "entry": entry.to_dict()}
    except ValueError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("add_to_watchlist failed")
        return _error(exc)


async def remove_from_watchlist(
    symbol: str,
    strategy: str,
    interval: str = "1h",
    market: str = "spot",
) -> dict:
    """
    Remove a symbol+strategy pair from the watchlist.

    Args:
        symbol:   Trading pair e.g. 'btc_usdt'.
        strategy: Signal strategy name.
        interval: Candle interval (default '1h').
        market:   'spot' or 'futures' (default 'spot').

    Returns:
        Whether the entry was found and removed.
    """
    try:
        mgr = WatchlistManager()
        removed = mgr.remove(symbol, strategy, interval, market)
        return {"error": False, "removed": removed}
    except Exception as exc:
        logger.exception("remove_from_watchlist failed")
        return _error(exc)


async def list_watchlist() -> dict:
    """
    List all symbol+strategy pairs currently on the watchlist.

    Returns:
        All watchlist entries with their configuration.
    """
    try:
        mgr = WatchlistManager()
        entries = mgr.list_entries()
        return {
            "error": False,
            "count": len(entries),
            "entries": [e.to_dict() for e in entries],
        }
    except Exception as exc:
        logger.exception("list_watchlist failed")
        return _error(exc)


async def check_watchlist_signals(lookback: int = 200) -> dict:
    """
    Scan every watchlist entry for new signals and log alerts.

    Only signals newer than the last logged alert for that entry are returned.
    On first check for an entry, signals from the last 24 hours are returned.

    Args:
        lookback: Historical bars to fetch per symbol (default 200).

    Returns:
        New alerts across all watchlist entries since the last check.
    """
    try:
        mgr = WatchlistManager()
        entries = mgr.list_entries()

        if not entries:
            return {
                "error": False,
                "message": "Watchlist is empty. Add symbols with add_to_watchlist.",
                "new_alerts": [],
                "total": 0,
            }

        engine = SignalEngine()
        new_alerts: list[dict] = []
        errors: list[dict] = []
        now_ms = int(time.time() * 1000)
        day_ms = 24 * 3600 * 1000

        for entry in entries:
            try:
                signals, _ = await engine.run_with_df(
                    symbol=entry.symbol,
                    interval=entry.interval,
                    strategy_name=entry.strategy,
                    market=entry.market,
                    lookback=min(lookback, 1000),
                )

                last_ts = mgr.get_last_signal_timestamp(
                    entry.symbol, entry.strategy, entry.interval, entry.market
                )
                cutoff = last_ts if last_ts is not None else (now_ms - day_ms)

                for sig in signals:
                    if sig.timestamp > cutoff:
                        alert = mgr.log_alert(
                            symbol=entry.symbol,
                            strategy=entry.strategy,
                            interval=entry.interval,
                            market=entry.market,
                            signal_type=sig.signal_type.value,
                            price=sig.price,
                            signal_timestamp=sig.timestamp,
                        )
                        new_alerts.append(alert.to_dict())

            except XTMCPError as exc:
                errors.append({"symbol": entry.symbol, "strategy": entry.strategy, "error": str(exc)})
            except Exception as exc:
                logger.error("check_watchlist_signals error for %s: %s", entry.symbol, exc)
                errors.append({"symbol": entry.symbol, "strategy": entry.strategy, "error": str(exc)})

        return {
            "error": False,
            "checked": len(entries),
            "new_alerts": new_alerts,
            "total": len(new_alerts),
            "errors": errors,
        }

    except Exception as exc:
        logger.exception("check_watchlist_signals failed")
        return _error(exc)


async def get_recent_alerts(limit: int = 20) -> dict:
    """
    Retrieve the most recent signal alerts from the alert log.

    Args:
        limit: Maximum number of alerts to return (default 20).

    Returns:
        Recent alerts ordered newest-first.
    """
    try:
        mgr = WatchlistManager()
        alerts = mgr.recent_alerts(limit=limit)
        return {
            "error": False,
            "count": len(alerts),
            "alerts": [a.to_dict() for a in alerts],
        }
    except Exception as exc:
        logger.exception("get_recent_alerts failed")
        return _error(exc)
