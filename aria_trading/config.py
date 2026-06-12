"""
ARIA Trading System — Central Configuration
"""

CONFIG = {
    # ── Risk Management ─────────────────────────────────────
    "risk_per_trade_pct": 2.0,
    "max_concurrent_trades": 3,
    "daily_loss_limit_pct": 5.0,
    "weekly_loss_limit_pct": 10.0,
    "monthly_loss_limit_pct": 20.0,
    "min_confluence_score": 75,
    "min_rr_ratio": 2.0,
    "max_leverage": 25,
    "max_leverage_meme": 10,
    "max_position_pct": 20.0,
    "sl_buffer_pct": 0.003,

    # ── Signal Thresholds ───────────────────────────────────
    "funding_rate_long_max": 0.001,
    "funding_rate_short_max": -0.0005,
    "whale_inflow_alert_btc": 5000,
    "whale_tx_threshold_usd": 500000,
    "volume_spike_multiplier": 3.0,
    "gem_score_min": 70,
    "gem_score_high": 85,

    # ── Symbols ─────────────────────────────────────────────
    "symbols_count": 100,          # تعداد ارزهای برتر برای اسکن
    "symbols": [],                  # خودکار از XT.com پر میشه

    # ── Timeframes ──────────────────────────────────────────
    "htf": ["1d", "4h"],
    "ltf": ["1h", "15m", "5m"],
    "all_timeframes": ["1d", "4h", "1h", "15m", "5m"],

    # ── Intervals (seconds) ─────────────────────────────────
    "market_analysis_interval": 300,
    "whale_check_interval": 180,
    "gem_scan_interval": 600,
    "exit_check_interval": 30,

    # ── XT.com API ──────────────────────────────────────────
    "xt_rest_spot":    "https://sapi.xt.com",
    "xt_rest_futures": "https://fapi.xt.com",
    "xt_ws_public":    "wss://stream.xt.com/public",
    "xt_ws_futures":   "wss://fstream.xt.com/public",
    "xt_api_key":      "",
    "xt_api_secret":   "",

    # ── On-Chain ────────────────────────────────────────────
    "glassnode_api_key": "",

    # ── Telegram ────────────────────────────────────────────
    "telegram_bot_token": "8856332073:AAFTQs0NhEh3PoUsRw9YXRuJfTBJvkBh0bg",
    "telegram_chat_id":   "554649373",

    # ── Database ────────────────────────────────────────────
    "db_path": "aria_trading.db",
}
