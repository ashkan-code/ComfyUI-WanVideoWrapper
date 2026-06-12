"""
ARIA Trading System — Telegram Notifier
Sends ALL signals to Telegram: entry, exit, TP levels, SL, gems, warnings.
"""

import logging
import aiohttp
from config import CONFIG

logger = logging.getLogger(__name__)


async def send(text: str) -> None:
    """Send a plain-text (HTML) message to the configured chat."""
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


# ──────────────────────────────────────────────────────────
# SYSTEM
# ──────────────────────────────────────────────────────────

async def system_online() -> None:
    await send(
        "🤖 <b>ARIA ONLINE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "سیستم هوش مصنوعی ترید فعال شد\n"
        f"نمادها: {len(CONFIG['symbols'])} جفت ارز\n"
        f"حداقل امتیاز: {CONFIG['min_confluence_score']}/100\n"
        f"ریسک هر ترید: {CONFIG['risk_per_trade_pct']}%\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )


async def system_offline(reason: str = "") -> None:
    await send(f"🔴 <b>ARIA OFFLINE</b>\n{reason}")


# ──────────────────────────────────────────────────────────
# GEM SIGNAL
# ──────────────────────────────────────────────────────────

async def gem_found(gem: dict) -> None:
    sym = gem["symbol"].upper().replace("_USDT", "/USDT")
    direction = "📈 LONG" if gem["direction"] == "long" else "📉 SHORT"
    wyckoff = gem.get("wyckoff", {})
    tech = gem.get("technical", {})
    ez = tech.get("entry_zone", {})

    await send(
        f"💎 <b>GEM CANDIDATE — {sym}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"جهت: {direction}\n"
        f"امتیاز: <b>{gem['gem_score']}/100</b> ({gem['priority']})\n"
        f"\n"
        f"📊 <b>وایکوف:</b> Phase {wyckoff.get('phase','?')} — {wyckoff.get('event','?')}\n"
        f"اطمینان: {wyckoff.get('confidence',0)}%\n"
        f"\n"
        f"🎯 <b>سطوح پیشنهادی:</b>\n"
        f"ورود: {gem.get('suggested_entry',0):.6g}\n"
        f"حد ضرر: {gem.get('suggested_sl',0):.6g}\n"
        f"هدف ۱: {gem.get('suggested_tp1',0):.6g}\n"
        f"هدف ۲: {gem.get('suggested_tp2',0):.6g}\n"
        f"R/R: {gem.get('rr_ratio',0):.1f}x\n"
        f"\n"
        f"💬 {gem.get('summary','')}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )


# ──────────────────────────────────────────────────────────
# SETUP QUALIFIED
# ──────────────────────────────────────────────────────────

async def setup_qualified(setup: dict) -> None:
    sym = setup["symbol"].upper().replace("_USDT", "/USDT")
    direction = "📈 LONG" if setup["direction"] == "long" else "📉 SHORT"
    bd = setup.get("confluence_breakdown", {})

    await send(
        f"⚡ <b>SETUP QUALIFIED — {sym}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"جهت: {direction}\n"
        f"امتیاز کانفلوئنس: <b>{setup['confluence_score']}/100</b>\n"
        f"نوع ستاپ: {setup.get('setup_type','')}\n"
        f"\n"
        f"📐 <b>جزئیات امتیاز:</b>\n"
        f"ساختار HTF: {bd.get('htf_structure',0)} pts\n"
        f"سیگنال نهنگ: {bd.get('whale_signal',0)} pts\n"
        f"فاندینگ ریت: {bd.get('funding_rate',0)} pts\n"
        f"حجم/CVD: {bd.get('volume',0)+bd.get('cvd',0)} pts\n"
        f"\n"
        f"🎯 <b>سطوح:</b>\n"
        f"ورود: {setup.get('entry_trigger_price',0):.6g}\n"
        f"حد ضرر: {setup.get('stop_loss',0):.6g}  ({setup.get('distance_to_sl_pct',0):.2f}%)\n"
        f"TP1: {setup.get('take_profit_1',0):.6g}\n"
        f"TP2: {setup.get('take_profit_2',0):.6g}\n"
        f"R/R: {setup.get('rr_ratio',0):.2f}x\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏳ منتظر تریگر ورود..."
    )


# ──────────────────────────────────────────────────────────
# TRADE ENTRY
# ──────────────────────────────────────────────────────────

async def trade_opened(trade: dict) -> None:
    sym = trade["symbol"].upper().replace("_USDT", "/USDT")
    direction = "📈 LONG" if trade["direction"] == "long" else "📉 SHORT"
    tp1 = trade.get("take_profit_1", trade.get("tp1", 0))
    tp2 = trade.get("take_profit_2", trade.get("tp2", 0))

    await send(
        f"🟢 <b>ورود به معامله — {sym}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"جهت: {direction}\n"
        f"قیمت ورود: <b>{trade.get('entry_price',0):.6g}</b>\n"
        f"\n"
        f"🛡 حد ضرر: {trade.get('stop_loss',0):.6g}\n"
        f"🎯 هدف ۱:  {tp1:.6g}  (بستن ۵۰%)\n"
        f"🎯 هدف ۲:  {tp2:.6g}  (بستن ۳۰%)\n"
        f"\n"
        f"💰 حجم: ${trade.get('position_size_usdt',0):.2f}\n"
        f"⚡ اهرم: {trade.get('leverage',1)}x\n"
        f"🔴 ریسک: ${trade.get('risk_amount_usdt',0):.2f}\n"
        f"📊 امتیاز: {trade.get('confluence_score',0)}/100\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )


# ──────────────────────────────────────────────────────────
# TP HITS
# ──────────────────────────────────────────────────────────

async def tp1_hit(symbol: str, price: float, new_sl: float) -> None:
    sym = symbol.upper().replace("_USDT", "/USDT")
    await send(
        f"✅ <b>هدف ۱ رسید — {sym}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"قیمت: {price:.6g}\n"
        f"۵۰٪ پوزیشن بسته شد\n"
        f"حد ضرر به نقطه ورود منتقل شد: {new_sl:.6g}\n"
        f"باقی پوزیشن: ۵۰٪ — ریسک‌فری ✅\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )


async def tp2_hit(symbol: str, price: float, new_sl: float) -> None:
    sym = symbol.upper().replace("_USDT", "/USDT")
    await send(
        f"✅✅ <b>هدف ۲ رسید — {sym}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"قیمت: {price:.6g}\n"
        f"۳۰٪ دیگر بسته شد\n"
        f"حد ضرر به هدف ۱ منتقل شد: {new_sl:.6g}\n"
        f"باقی پوزیشن: ۲۰٪ — در سود قفل شده 🔒\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )


async def tp3_hit(symbol: str, price: float, pnl_pct: float) -> None:
    sym = symbol.upper().replace("_USDT", "/USDT")
    await send(
        f"🏆 <b>هدف ۳ رسید — {sym}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"قیمت خروج: {price:.6g}\n"
        f"کل پوزیشن بسته شد\n"
        f"سود کل: <b>+{pnl_pct:.2f}%</b> 🎉\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )


# ──────────────────────────────────────────────────────────
# SL HIT
# ──────────────────────────────────────────────────────────

async def sl_hit(symbol: str, price: float, loss_pct: float) -> None:
    sym = symbol.upper().replace("_USDT", "/USDT")
    await send(
        f"❌ <b>حد ضرر فعال شد — {sym}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"قیمت خروج: {price:.6g}\n"
        f"ضرر: {loss_pct:.2f}%\n"
        f"\n"
        f"📋 تحلیل ذخیره شد\n"
        f"⏳ اسکن فرصت بعدی در حال انجام...\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )


# ──────────────────────────────────────────────────────────
# PARTIAL EXIT
# ──────────────────────────────────────────────────────────

async def partial_exit(symbol: str, pct: float, reason: str, new_sl: float | None = None) -> None:
    sym = symbol.upper().replace("_USDT", "/USDT")
    sl_text = f"\nحد ضرر جدید: {new_sl:.6g}" if new_sl else ""
    await send(
        f"⚠️ <b>خروج جزئی — {sym}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{pct:.0f}٪ پوزیشن بسته شد\n"
        f"دلیل: {reason}{sl_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )


# ──────────────────────────────────────────────────────────
# INVALIDATION
# ──────────────────────────────────────────────────────────

async def setup_invalidated(symbol: str, reason: str) -> None:
    sym = symbol.upper().replace("_USDT", "/USDT")
    await send(
        f"🚫 <b>ستاپ کنسل شد — {sym}</b>\n"
        f"دلیل: {reason}"
    )


# ──────────────────────────────────────────────────────────
# WHALE / MARKET ALERTS
# ──────────────────────────────────────────────────────────

async def whale_alert(symbol: str, signal: str, summary: str) -> None:
    sym = symbol.upper().replace("_USDT", "/USDT")
    icon = "🟢" if "BULL" in signal else "🔴" if "BEAR" in signal else "⚡"
    await send(
        f"{icon} <b>سیگنال نهنگ — {sym}</b>\n"
        f"نوع: {signal}\n"
        f"{summary}"
    )


async def risk_alert(message: str) -> None:
    await send(f"🚨 <b>هشدار ریسک</b>\n━━━━━━━━━━━━━━━━━━━━\n{message}")


async def daily_drawdown_halt() -> None:
    await send(
        "🛑 <b>توقف اضطراری</b>\n"
        f"ضرر روزانه به {CONFIG['daily_loss_limit_pct']}% رسید\n"
        "تمام معاملات جدید متوقف شد\n"
        "فردا ادامه می‌دهیم."
    )


# ──────────────────────────────────────────────────────────
# WEEKLY REPORT
# ──────────────────────────────────────────────────────────

async def weekly_report(report_text: str) -> None:
    await send(f"📊 <b>گزارش هفتگی</b>\n━━━━━━━━━━━━━━━━━━━━\n{report_text}")
