"""Bot configuration — edit values or set via environment variables."""

import os
from dataclasses import dataclass, field


@dataclass
class Config:
    # ── API Credentials ──────────────────────────────────────────────────────
    api_key: str = field(default_factory=lambda: os.getenv("XT_API_KEY", ""))
    api_secret: str = field(default_factory=lambda: os.getenv("XT_API_SECRET", ""))

    # ── Fee Settings ─────────────────────────────────────────────────────────
    # XT.com default taker fee: 0.20%
    # With XT token VIP: can go down to 0.06%
    trading_fee: float = 0.002  # 0.20% per trade — change to your actual tier

    # ── Profit Threshold ─────────────────────────────────────────────────────
    # Minimum NET profit % after ALL 3 trade fees + spread cost
    # 3 trades × 0.2% = 0.6% breakeven → we need > 0.6% gross to profit
    min_profit_pct: float = 0.10  # 0.10% net minimum (conservative)

    # ── Capital Per Trade ────────────────────────────────────────────────────
    trade_amount_usdt: float = 100.0  # USDT to use per arbitrage cycle

    # ── Execution ────────────────────────────────────────────────────────────
    # DRY RUN = True means: scan + calculate, but DO NOT place real orders
    # Set to False only when you have verified profits in dry run first
    dry_run: bool = True

    order_type: str = "MARKET"      # MARKET (fast) or LIMIT (cheaper fee)
    scan_interval_sec: float = 1.0  # How often to scan (seconds)
    max_trades_per_min: int = 10    # Rate limit guard

    # ── Risk Controls ────────────────────────────────────────────────────────
    # Minimum orderbook liquidity (USDT equivalent) on each leg
    min_liquidity_usdt: float = 500.0
    # Stop bot after this many consecutive failed executions
    max_consecutive_failures: int = 5
    # Daily loss limit in USDT (bot stops if exceeded)
    max_daily_loss_usdt: float = 20.0

    # ── Scanning ─────────────────────────────────────────────────────────────
    base_currencies: list = field(default_factory=lambda: ["usdt"])
    # Top N ticker-only opportunities to do deep orderbook verification on
    top_to_verify: int = 5
