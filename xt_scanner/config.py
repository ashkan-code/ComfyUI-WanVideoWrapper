# XT.com Crypto Scalping Scanner — Configuration

# XT.com REST API
XT_REST_BASE = "https://sapi.xt.com"
XT_SYMBOLS_ENDPOINT = "/v4/public/symbol"

# XT.com WebSocket
XT_WS_URL = "wss://stream.xt.com/public"

# Scanner settings
TOP_COINS_COUNT = 200          # number of top-volume coins to monitor
SIGNAL_INTERVAL_SEC = 10      # recalculate signals every N seconds
DASHBOARD_REFRESH_SEC = 5     # refresh terminal table every N seconds
TRADE_WINDOW_SEC = 60         # rolling window kept for CVD (seconds)
ORDER_BOOK_DEPTH = 20         # depth levels to subscribe to
ORDER_BOOK_TOP = 10           # top N levels used for OBI calculation

# Signal thresholds
OBI_LONG_THRESHOLD = 2.5      # OBI ratio above this → LONG signal
OBI_SHORT_THRESHOLD = 0.4     # OBI ratio below this → SHORT signal
SCORE_ALERT_THRESHOLD = 60    # score above this triggers Telegram alert (%)

# Signal weights (must sum to 1.0)
WEIGHT_CVD = 0.35
WEIGHT_OBI = 0.35
WEIGHT_SWEEP = 0.30

# Stop-loss / target multipliers
STOP_LOSS_PCT = 0.005         # 0.5%
TARGET_PCT = 0.010            # 1.0%

# Telegram — fill in before running
TELEGRAM_BOT_TOKEN = "8911486921:AAGMdTFc0IIKJfnMeltEbXtnZ3tRKWJ_fTY"
TELEGRAM_CHAT_ID = "554649373"
