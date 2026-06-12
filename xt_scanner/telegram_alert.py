"""
Telegram alerting — sends a formatted message when score > threshold.
Deduplicates by symbol so only one alert fires per signal window.
"""

import asyncio
import logging
import time
from typing import Dict

import config
from signals import SignalResult

logger = logging.getLogger(__name__)

# Tracks last alert time per symbol to suppress repeated messages
_last_alert: Dict[str, float] = {}
_COOLDOWN_SEC = 300   # minimum gap between two alerts for the same symbol


def _format_message(r: SignalResult) -> str:
    sym = r.symbol.upper()
    price = r.price

    if r.direction == "LONG":
        stop = round(price * (1 - config.STOP_LOSS_PCT), 8)
        target = round(price * (1 + config.TARGET_PCT), 8)
    else:
        stop = round(price * (1 + config.STOP_LOSS_PCT), 8)
        target = round(price * (1 - config.TARGET_PCT), 8)

    return (
        f"🚨 SIGNAL: {sym}\n"
        f"Direction: {r.direction}\n"
        f"Entry: {price}\n"
        f"Stop: {stop}\n"
        f"Target: {target}\n"
        f"Score: {r.score}%\n"
        f"CVD: {r.cvd:+.4f}\n"
        f"OBI: {r.obi_ratio:.3f}"
    )


async def _send_telegram(text: str) -> None:
    """Send a message via the Telegram Bot API using aiohttp."""
    import aiohttp

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error("Telegram API error %d: %s", resp.status, body)
                else:
                    logger.info("Telegram alert sent for signal")
    except Exception as exc:
        logger.error("Failed to send Telegram message: %s", exc)


async def maybe_alert(results: list[SignalResult]) -> None:
    """Check each result and fire Telegram alerts for high-score signals."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return  # credentials not configured

    now = time.time()
    for r in results:
        if r.score < config.SCORE_ALERT_THRESHOLD:
            continue
        last = _last_alert.get(r.symbol, 0)
        if now - last < _COOLDOWN_SEC:
            continue  # still in cooldown

        _last_alert[r.symbol] = now
        msg = _format_message(r)
        logger.info("Firing Telegram alert for %s (score=%.1f)", r.symbol, r.score)
        await _send_telegram(msg)


async def run_alert_loop(
    get_results,          # callable → List[SignalResult]
    stop_event: asyncio.Event,
) -> None:
    """Background loop that checks signals and sends alerts."""
    while not stop_event.is_set():
        results = get_results()
        await maybe_alert(results)
        await asyncio.sleep(config.SIGNAL_INTERVAL_SEC)
