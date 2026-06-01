#!/usr/bin/env python3
"""
XT.com Triangular Arbitrage Bot
================================
Scans all trading pairs on XT.com, finds triangular arbitrage
opportunities, verifies them against the live orderbook,
and executes only when net profit exceeds the configured threshold.

Usage:
    # Dry run (default — safe, no real orders)
    python bot.py

    # Live trading (set DRY_RUN=false + supply credentials)
    XT_API_KEY=xxx XT_API_SECRET=yyy python bot.py --live

    # Specify minimum profit threshold
    python bot.py --min-profit 0.15

    # Adjust trade size
    python bot.py --amount 500
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from collections import deque
from datetime import datetime, timezone

# Allow running from within the bot directory OR from repo root
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "xt_mcp_server"))

from config import Config
from scanner import find_opportunities, verify_with_orderbook
from executor import OrderExecutor, ExecutionResult

try:
    from xt_api import XTClient
except ImportError:
    print("ERROR: Cannot import XTClient. Make sure xt_mcp_server/ is next to xt_arbitrage_bot/")
    sys.exit(1)

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────

def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(level=level, format=fmt, datefmt="%H:%M:%S")

log = logging.getLogger("bot")


# ──────────────────────────────────────────────────────────────────────────────
# Stats tracker
# ──────────────────────────────────────────────────────────────────────────────

class BotStats:
    def __init__(self):
        self.scans = 0
        self.opportunities_found = 0
        self.executions_attempted = 0
        self.executions_successful = 0
        self.total_profit_usdt = 0.0
        self.total_loss_usdt = 0.0
        self.consecutive_failures = 0
        self.start_time = time.time()
        self.recent_profits: deque = deque(maxlen=20)

    @property
    def uptime_str(self) -> str:
        elapsed = int(time.time() - self.start_time)
        h, rem = divmod(elapsed, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    @property
    def net_pnl(self) -> float:
        return self.total_profit_usdt - self.total_loss_usdt

    def record_result(self, result: ExecutionResult):
        self.executions_attempted += 1
        if result.success:
            self.executions_successful += 1
            self.consecutive_failures = 0
            if result.net_profit_usdt >= 0:
                self.total_profit_usdt += result.net_profit_usdt
            else:
                self.total_loss_usdt += abs(result.net_profit_usdt)
            self.recent_profits.append(result.net_profit_usdt)
        else:
            self.consecutive_failures += 1

    def print_summary(self):
        win_rate = (
            self.executions_successful / self.executions_attempted * 100
            if self.executions_attempted > 0 else 0
        )
        log.info("─" * 60)
        log.info(f"  Uptime         : {self.uptime_str}")
        log.info(f"  Scans          : {self.scans}")
        log.info(f"  Opportunities  : {self.opportunities_found}")
        log.info(f"  Executions     : {self.executions_attempted} (win={win_rate:.1f}%)")
        log.info(f"  Net P&L        : {self.net_pnl:+.4f} USDT")
        log.info(f"  Profit         : {self.total_profit_usdt:.4f} USDT")
        log.info(f"  Loss           : {self.total_loss_usdt:.4f} USDT")
        log.info("─" * 60)


# ──────────────────────────────────────────────────────────────────────────────
# Main bot loop
# ──────────────────────────────────────────────────────────────────────────────

class ArbitrageBot:
    def __init__(self, config: Config):
        self._cfg = config
        self._client = XTClient(
            api_key=config.api_key,
            api_secret=config.api_secret,
        )
        self._executor = OrderExecutor(self._client, config)
        self._stats = BotStats()
        self._running = False

    def _fetch_tickers(self) -> list[dict]:
        """Fetch all book tickers (best bid/ask for all pairs)."""
        try:
            result = self._client.get("/v4/public/ticker/book")
            if isinstance(result, list):
                return result
            if isinstance(result, dict) and "tickers" in result:
                return result["tickers"]
            return []
        except Exception as e:
            log.warning(f"Failed to fetch tickers: {e}")
            return []

    def _fetch_orderbooks(self, symbols: list[str], depth: int = 10) -> dict[str, dict]:
        """Fetch orderbooks for given symbols."""
        books: dict[str, dict] = {}
        for sym in symbols:
            try:
                ob = self._client.get_orderbook(sym, limit=depth)
                if ob:
                    books[sym] = ob
            except Exception as e:
                log.debug(f"Orderbook fetch failed for {sym}: {e}")
        return books

    def _get_symbols_from_opportunity(self, opp) -> list[str]:
        t = opp.triangle
        return list({t.leg1.symbol, t.leg2.symbol, t.leg3.symbol})

    def _scan_cycle(self) -> list:
        """One complete scan cycle. Returns verified opportunities."""
        tickers = self._fetch_tickers()
        if not tickers:
            return []

        self._stats.scans += 1

        # Step 1: Fast scan using best bid/ask only
        raw_opps = find_opportunities(tickers, self._cfg)
        if not raw_opps:
            return []

        log.debug(f"Found {len(raw_opps)} raw opportunities")
        self._stats.opportunities_found += len(raw_opps)

        # Step 2: Verify top N with orderbook depth
        top = raw_opps[: self._cfg.top_to_verify]
        symbols_needed = set()
        for opp in top:
            symbols_needed.update(self._get_symbols_from_opportunity(opp))

        books = self._fetch_orderbooks(list(symbols_needed))

        verified = []
        for opp in top:
            v = verify_with_orderbook(opp, books, self._cfg)
            if v is not None:
                verified.append(v)

        return sorted(verified, key=lambda o: o.net_profit_pct, reverse=True)

    def _should_stop(self) -> bool:
        if self._stats.consecutive_failures >= self._cfg.max_consecutive_failures:
            log.error(
                f"Stopping: {self._stats.consecutive_failures} consecutive failures"
            )
            return True
        daily_loss = self._stats.total_loss_usdt - self._stats.total_profit_usdt
        if daily_loss >= self._cfg.max_daily_loss_usdt:
            log.error(f"Stopping: daily loss limit reached ({daily_loss:.2f} USDT)")
            return True
        return False

    def run(self):
        mode = "DRY-RUN" if self._cfg.dry_run else "LIVE TRADING"
        log.info("=" * 60)
        log.info(f"  XT.com Triangular Arbitrage Bot — {mode}")
        log.info(f"  Min profit     : {self._cfg.min_profit_pct:.2f}%")
        log.info(f"  Trade amount   : {self._cfg.trade_amount_usdt:.0f} USDT")
        log.info(f"  Fee per trade  : {self._cfg.trading_fee * 100:.2f}%")
        log.info(f"  Breakeven fees : {(1 - (1-self._cfg.trading_fee)**3) * 100:.3f}%")
        log.info(f"  Scan interval  : {self._cfg.scan_interval_sec}s")
        log.info("=" * 60)

        if not self._cfg.dry_run and (not self._cfg.api_key or not self._cfg.api_secret):
            log.error("LIVE mode requires XT_API_KEY and XT_API_SECRET environment variables")
            return

        self._running = True
        last_summary = time.time()

        try:
            while self._running:
                loop_start = time.time()

                try:
                    opps = self._scan_cycle()
                except Exception as e:
                    log.error(f"Scan error: {e}")
                    time.sleep(self._cfg.scan_interval_sec)
                    continue

                if opps:
                    best = opps[0]
                    log.info(f"OPPORTUNITY: {best}")

                    result = self._executor.execute(best)
                    self._stats.record_result(result)

                    if not result.success:
                        log.warning(f"Execution failed: {result.error}")
                    else:
                        log.info(result.summary())

                    if self._should_stop():
                        break
                else:
                    if self._stats.scans % 30 == 0:
                        log.info(
                            f"Scanning... (scan #{self._stats.scans}, "
                            f"no opportunities above {self._cfg.min_profit_pct:.2f}%)"
                        )

                # Print stats every 5 minutes
                if time.time() - last_summary > 300:
                    self._stats.print_summary()
                    last_summary = time.time()

                elapsed = time.time() - loop_start
                sleep_for = max(0, self._cfg.scan_interval_sec - elapsed)
                if sleep_for > 0:
                    time.sleep(sleep_for)

        except KeyboardInterrupt:
            log.info("Bot stopped by user (Ctrl+C)")

        finally:
            self._running = False
            log.info("Final statistics:")
            self._stats.print_summary()
            self._client.close()


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="XT.com Triangular Arbitrage Bot")
    parser.add_argument("--live", action="store_true", help="Enable live trading (default: dry run)")
    parser.add_argument("--min-profit", type=float, default=None, help="Min profit %% (default: 0.10)")
    parser.add_argument("--amount", type=float, default=None, help="Trade amount in USDT (default: 100)")
    parser.add_argument("--fee", type=float, default=None, help="Trading fee per trade (default: 0.002)")
    parser.add_argument("--interval", type=float, default=None, help="Scan interval in seconds (default: 1.0)")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    setup_logging(args.verbose)

    cfg = Config(
        api_key=os.getenv("XT_API_KEY", ""),
        api_secret=os.getenv("XT_API_SECRET", ""),
        dry_run=not args.live,
    )

    if args.min_profit is not None:
        cfg.min_profit_pct = args.min_profit
    if args.amount is not None:
        cfg.trade_amount_usdt = args.amount
    if args.fee is not None:
        cfg.trading_fee = args.fee
    if args.interval is not None:
        cfg.scan_interval_sec = args.interval

    bot = ArbitrageBot(cfg)
    bot.run()


if __name__ == "__main__":
    main()
