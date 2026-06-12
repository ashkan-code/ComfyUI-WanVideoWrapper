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
    "max_position_pct": 20.0,       # max % of balance in one trade
    "sl_buffer_pct": 0.003,          # 0.3% buffer beyond structure

    # ── Signal Thresholds ───────────────────────────────────
    "funding_rate_long_max": 0.001,   # +0.1% — reject longs above this
    "funding_rate_short_max": -0.0005,# -0.05% — reject shorts below this
    "whale_inflow_alert_btc": 5000,   # BTC exchange inflow alert threshold
    "whale_tx_threshold_usd": 500000, # Minimum USD for whale tx tracking
    "volume_spike_multiplier": 3.0,   # 3x avg = volume anomaly
    "gem_score_min": 70,              # Minimum gem score to report
    "gem_score_high": 85,             # High-priority gem threshold

    # ── Symbols to Scan ─────────────────────────────────────
    "symbols": [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "AVAXUSDT",
        "ARBUSDT", "OPUSDT", "INJUSDT", "SUIUSDT", "APTUSDT",
        "LINKUSDT", "AAVEUSDT", "UNIUSDT", "LDOUSDT", "STXUSDT",
    ],

    # ── Timeframes ──────────────────────────────────────────
    "htf": ["1D", "4H"],
    "ltf": ["1H", "15m", "5m"],
    "all_timeframes": ["1D", "4H", "1H", "15m", "5m"],

    # ── Intervals (seconds) ─────────────────────────────────
    "market_analysis_interval": 300,   # 5 min
    "whale_check_interval": 180,       # 3 min
    "gem_scan_interval": 600,          # 10 min
    "exit_check_interval": 30,         # 30 sec

    # ── Exchange APIs (fill before running) ─────────────────
    "bitunix_api_key": "",
    "bitunix_api_secret": "",
    "bitunix_ws_url": "wss://fstream.bitunix.com/public",
    "bitunix_rest_url": "https://fapi.bitunix.com",
    "xt_api_key": "",
    "xt_api_secret": "",

    # ── On-Chain APIs (fill before running) ─────────────────
    "glassnode_api_key": "",

    # ── Telegram ────────────────────────────────────────────
    "telegram_bot_token": "",
    "telegram_chat_id": "",

    # ── Database ────────────────────────────────────────────
    "db_path": "aria_trading.db",
}
