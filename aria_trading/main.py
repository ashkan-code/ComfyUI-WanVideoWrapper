"""
ARIA Trading System — Entry Point
==================================
Usage:
    python main.py                        # paper trading mode
    python main.py --balance 5000         # set starting balance
    python main.py --live                 # enable live order placement
    python main.py --debug                # verbose logging

IMPORTANT: Run in paper mode and backtest before enabling --live.
"""

import argparse
import asyncio
import logging
import sys

from config import CONFIG
from orchestrator import Orchestrator
import xt_client as xt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ARIA AI Trading System")
    parser.add_argument("--balance", type=float, default=1000.0,
                        help="Starting account balance in USDT (default: 1000)")
    parser.add_argument("--top", type=int, default=None,
                        help=f"Number of top coins to scan (default: {CONFIG['symbols_count']})")
    parser.add_argument("--live", action="store_true",
                        help="Enable live order execution (default: paper mode)")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug logging")
    return parser.parse_args()


def setup_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("aria_trading.log"),
        ],
    )


def check_config() -> list[str]:
    """Return list of missing required config fields."""
    warnings = []
    if not CONFIG["telegram_bot_token"]:
        warnings.append("telegram_bot_token")
    if not CONFIG["telegram_chat_id"]:
        warnings.append("telegram_chat_id")
    if not CONFIG["xt_api_key"]:
        warnings.append("xt_api_key (needed for live trading)")
    return warnings


async def main() -> None:
    args = parse_args()
    setup_logging(args.debug)
    logger = logging.getLogger("main")

    print("\n" + "═" * 50)
    print("  ARIA — Autonomous Reasoning Intelligence for Assets")
    print("  AI Trading System v1.0")
    print("═" * 50)

    # Config check
    missing = check_config()
    if missing:
        print(f"\n⚠️  Missing config fields: {', '.join(missing)}")
        print("   Edit aria_trading/config.py to fill them in.\n")

    mode = "🔴 LIVE" if args.live else "🟡 PAPER"
    print(f"\n  Mode    : {mode}")
    print(f"  Balance : ${args.balance:,.2f} USDT")
    print(f"  Symbols : {len(CONFIG['symbols'])} pairs")
    print(f"  Min score: {CONFIG['min_confluence_score']}/100")
    print(f"  Risk/trade: {CONFIG['risk_per_trade_pct']}%\n")

    if args.live:
        confirm = input("⚠️  You are about to enable LIVE trading. Type 'YES' to confirm: ")
        if confirm.strip() != "YES":
            print("Aborted.")
            return

    # ── Fetch symbols from XT.com ──────────────────────────
    if args.top:
        CONFIG["symbols_count"] = args.top
    scan_label = str(CONFIG["symbols_count"]) if CONFIG["symbols_count"] < 9999 else "همه"
    print(f"\n🔍  در حال دریافت {scan_label} نماد از XT.com …")
    symbols = await xt.fetch_top_symbols(CONFIG["symbols_count"])
    CONFIG["symbols"] = symbols
    print(f"✅  {len(symbols)} نماد بارگذاری شد: {', '.join(s.upper() for s in symbols[:5])} …\n")

    orchestrator = Orchestrator(account_balance=args.balance)

    try:
        await orchestrator.start()
    except KeyboardInterrupt:
        print("\n👋 ARIA stopped by user.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Interrupted.")
