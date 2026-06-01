# XT Exchange MCP Server

MCP (Model Context Protocol) server برای صرافی [XT.com](https://www.xt.com).

## نصب

```bash
cd xt_mcp_server
pip install -r requirements.txt
```

## پیکربندی

متغیرهای محیطی برای دسترسی به APIهای خصوصی:

```bash
export XT_API_KEY="your_api_key_here"
export XT_API_SECRET="your_api_secret_here"
```

> **توجه:** برای APIهای عمومی (قیمت، اوردربوک و...) نیازی به کلید API نیست.

## اجرا

```bash
python server.py
```

## پیکربندی در Claude Desktop

فایل `claude_desktop_config.json` را ویرایش کنید:

```json
{
  "mcpServers": {
    "xt-exchange": {
      "command": "python",
      "args": ["/path/to/xt_mcp_server/server.py"],
      "env": {
        "XT_API_KEY": "your_api_key",
        "XT_API_SECRET": "your_api_secret"
      }
    }
  }
}
```

## ابزارهای موجود

### داده‌های بازار (عمومی - بدون نیاز به API Key)

| ابزار | توضیح |
|-------|--------|
| `xt_server_time` | زمان سرور XT |
| `xt_get_symbols` | لیست تمام جفت‌ارزها |
| `xt_get_ticker` | قیمت لحظه‌ای یک جفت‌ارز |
| `xt_get_all_tickers` | قیمت تمام جفت‌ارزها |
| `xt_get_24h_ticker` | آمار ۲۴ ساعته (High/Low/Volume) |
| `xt_get_all_24h_tickers` | آمار ۲۴ ساعته همه جفت‌ارزها |
| `xt_get_book_ticker` | بهترین bid/ask |
| `xt_get_orderbook` | دفتر سفارشات (bids و asks) |
| `xt_get_klines` | کندل‌استیک (OHLCV) |
| `xt_get_recent_trades` | معاملات اخیر |

### حساب و معاملات (نیاز به API Key)

| ابزار | توضیح |
|-------|--------|
| `xt_get_balances` | موجودی تمام ارزها |
| `xt_get_balance` | موجودی یک ارز خاص |
| `xt_place_order` | ثبت سفارش (BUY/SELL, LIMIT/MARKET) |
| `xt_cancel_order` | لغو سفارش |
| `xt_cancel_all_orders` | لغو تمام سفارشات یک جفت‌ارز |
| `xt_get_order` | جزئیات سفارش |
| `xt_get_open_orders` | سفارشات باز |
| `xt_get_order_history` | تاریخچه سفارشات |
| `xt_get_trade_history` | تاریخچه معاملات انجام‌شده |

## مثال استفاده

```
# قیمت بیتکوین
xt_get_ticker(symbol="btc_usdt")

# کندل ۱ ساعته بیتکوین (۱۰۰ کندل آخر)
xt_get_klines(symbol="btc_usdt", interval="1h", limit=100)

# دفتر سفارشات اتریوم
xt_get_orderbook(symbol="eth_usdt", limit=20)

# ثبت سفارش خرید
xt_place_order(symbol="btc_usdt", side="BUY", order_type="LIMIT", quantity="0.001", price="65000")
```
