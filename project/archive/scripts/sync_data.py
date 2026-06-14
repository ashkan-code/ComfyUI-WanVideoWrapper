#!/usr/bin/env python3
"""CLI script for syncing XT Exchange candle data to local SQLite storage.

Termux quick-start:
    cd project
    python scripts/sync_data.py --market spot --mode full
    python scripts/sync_data.py --market spot --mode incremental
    python scripts/sync_data.py --symbols btc_usdt eth_usdt --timeframes 1h 4h 1d
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import pathlib
import sys

# Allow running directly from the project/ directory without install
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from data_engine.collector import DataCollector
from data_engine.storage import CandleStore
from data_engine.sync import SyncManager
from xt_mcp.config import settings
from xt_mcp.logging_setup import configure_logging


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Sync XT Exchange candle data to local SQLite",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--market", choices=["spot", "futures"], default="spot",
        help="Which market to sync",
    )
    p.add_argument(
        "--mode", choices=["full", "incremental"], default="incremental",
        help="Full sync re-downloads max_history_days; incremental appends new bars only",
    )
    p.add_argument(
        "--symbols", nargs="+", default=None, metavar="SYM",
        help="Override default_symbols (e.g. btc_usdt eth_usdt)",
    )
    p.add_argument(
        "--timeframes", nargs="+", default=None, metavar="TF",
        help="Override default_timeframes (e.g. 1h 4h 1d)",
    )
    p.add_argument(
        "--db", default=None, metavar="PATH",
        help="SQLite file path (default: <data_dir>/<market>.db)",
    )
    p.add_argument(
        "--log-level", default=settings.log_level,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return p


async def _main(args: argparse.Namespace) -> None:
    configure_logging(args.log_level)
    log = logging.getLogger(__name__)

    db_path = args.db or f"{settings.data_dir}/{args.market}.db"
    store = CandleStore(db_path)
    collector = DataCollector()
    mgr = SyncManager(store=store, collector=collector)

    symbols = args.symbols or settings.default_symbols
    timeframes = args.timeframes or settings.default_timeframes

    log.info(
        "Starting %s sync | market=%s | symbols=%s | timeframes=%s | db=%s",
        args.mode, args.market, symbols, timeframes, db_path,
    )

    if args.mode == "full":
        summary = await mgr.full_sync(
            symbols=symbols, timeframes=timeframes, market=args.market
        )
    else:
        summary = await mgr.incremental_sync(
            symbols=symbols, timeframes=timeframes, market=args.market
        )

    total = sum(summary.values())
    log.info("Sync complete — total candles stored: %d", total)
    for key, count in sorted(summary.items()):
        log.info("  %-20s %d", key, count)


if __name__ == "__main__":
    asyncio.run(_main(_build_parser().parse_args()))
