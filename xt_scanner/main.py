"""
XT.com Crypto Scalping Scanner
===============================
Orchestrates:
  1. Symbol discovery via REST
  2. Live WebSocket data ingestion
  3. Signal calculation loop
  4. Rich terminal dashboard
  5. Telegram alerts

Run:
    python main.py
    python main.py --token YOUR_BOT_TOKEN --chat YOUR_CHAT_ID
"""

import argparse
import asyncio
import logging
import sys
import time
from typing import List

import config
import signals as sig
import xt_websocket as ws
from dashboard import run_dashboard
from telegram_alert import run_alert_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")

# Shared signal cache updated by the signal loop, read by dashboard+alerts
_latest_results: List[sig.SignalResult] = []


def get_latest_results() -> List[sig.SignalResult]:
    return _latest_results


# ──────────────────────────────────────────────
# Signal calculation loop
# ──────────────────────────────────────────────

async def signal_loop(symbols: List[str], stop_event: asyncio.Event) -> None:
    global _latest_results
    while not stop_event.is_set():
        await asyncio.sleep(config.SIGNAL_INTERVAL_SEC)
        try:
            results = sig.compute_all_signals(symbols)
            _latest_results = results
            logger.debug("Signals computed for %d symbols", len(results))
        except Exception as exc:
            logger.error("Signal computation error: %s", exc)


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="XT.com Crypto Scalping Scanner")
    parser.add_argument("--token", help="Telegram bot token (overrides config.py)")
    parser.add_argument("--chat", help="Telegram chat ID (overrides config.py)")
    parser.add_argument(
        "--top",
        type=int,
        default=config.TOP_COINS_COUNT,
        help=f"Number of top coins to monitor (default: {config.TOP_COINS_COUNT})",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.token:
        config.TELEGRAM_BOT_TOKEN = args.token
    if args.chat:
        config.TELEGRAM_CHAT_ID = args.chat

    # ── Telegram credentials check ─────────────────────────
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("\n⚠️  Telegram credentials not configured.")
        print("   Edit xt_scanner/config.py and fill in:")
        print("     TELEGRAM_BOT_TOKEN = 'your_token_here'")
        print("     TELEGRAM_CHAT_ID   = 'your_chat_id_here'")
        print("   OR pass --token and --chat on the command line.\n")
        answer = input("Continue without Telegram alerts? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            sys.exit(0)

    # ── Telegram test ──────────────────────────────────────
    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        import aiohttp as _aio
        test_url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        try:
            async with _aio.ClientSession() as s:
                async with s.post(test_url, json={
                    "chat_id": config.TELEGRAM_CHAT_ID,
                    "text": "✅ XT Scanner started — alerts are active!"
                }, timeout=_aio.ClientTimeout(total=8)) as r:
                    body = await r.json()
                    if r.status == 200:
                        print("✅  Telegram OK — test message sent!\n")
                    else:
                        print(f"⚠️  Telegram error: {body.get('description')}")
                        print("   → توی تلگرام ربات رو پیدا کن و /start بزن\n")
        except Exception as e:
            print(f"⚠️  Telegram unreachable: {e}\n")

    # ── Symbol discovery ────────────────────────────────────
    print("\n🔍  Fetching top symbols from XT.com …")
    symbols = await ws.fetch_top_symbols_by_volume(args.top)
    print(f"✅  Monitoring {len(symbols)} symbols: {', '.join(s.upper() for s in symbols[:5])} …\n")

    stop_event = asyncio.Event()
    start_time = time.time()

    # ── Concurrent tasks ────────────────────────────────────
    tasks = [
        asyncio.create_task(ws.run_websocket(symbols, stop_event), name="websocket"),
        asyncio.create_task(signal_loop(symbols, stop_event), name="signals"),
        asyncio.create_task(
            run_dashboard(get_latest_results, stop_event, start_time), name="dashboard"
        ),
        asyncio.create_task(
            run_alert_loop(get_latest_results, stop_event), name="alerts"
        ),
    ]

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        logger.error("Fatal error: %s", exc)
    finally:
        stop_event.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        print("\n👋  Scanner stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋  Interrupted.")
