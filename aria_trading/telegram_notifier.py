"""
ARIA Trading System — Telegram notification helper.
"""

import logging
import aiohttp
from config import CONFIG

logger = logging.getLogger(__name__)


async def send(text: str) -> None:
    """Send a plain text message to the configured Telegram chat."""
    token = CONFIG["telegram_bot_token"]
    chat_id = CONFIG["telegram_chat_id"]
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error("Telegram error %d: %s", resp.status, body)
    except Exception as exc:
        logger.error("Telegram send failed: %s", exc)


async def trade_opened(trade: dict) -> None:
    msg = (
        f"🟢 <b>TRADE OPENED</b>\n"
        f"Symbol: {trade['symbol']}\n"
        f"Direction: {trade['direction'].upper()}\n"
        f"Entry: {trade['entry_price']}\n"
        f"SL: {trade['stop_loss']}\n"
        f"TP1: {trade['tp1']} | TP2: {trade['tp2']}\n"
        f"Score: {trade['confluence_score']}/100\n"
        f"Risk: ${trade.get('risk_amount_usdt', '?'):.2f}"
    )
    await send(msg)


async def trade_closed(trade: dict) -> None:
    icon = "✅" if trade.get("pnl_usdt", 0) >= 0 else "❌"
    msg = (
        f"{icon} <b>TRADE CLOSED</b>\n"
        f"Symbol: {trade['symbol']}\n"
        f"Exit: {trade['exit_price']} ({trade['exit_reason']})\n"
        f"PnL: ${trade.get('pnl_usdt', 0):+.2f} ({trade.get('pnl_pct', 0):+.2f}%)\n"
        f"RR achieved: {trade.get('rr_actual', 0):.2f}"
    )
    await send(msg)


async def gem_alert(gem: dict) -> None:
    msg = (
        f"💎 <b>GEM CANDIDATE</b>\n"
        f"Symbol: {gem['symbol']}\n"
        f"Score: {gem['gem_score']}/100 ({gem['priority']})\n"
        f"Direction: {gem['direction'].upper()}\n"
        f"Entry zone: {gem['technical']['entry_zone']['low']} – {gem['technical']['entry_zone']['high']}\n"
        f"SL: {gem['suggested_sl']} | TP1: {gem['suggested_tp1']}\n"
        f"RR: {gem['rr_ratio']:.1f}x\n"
        f"{gem['summary']}"
    )
    await send(msg)


async def risk_alert(message: str) -> None:
    await send(f"⚠️ <b>RISK ALERT</b>\n{message}")
