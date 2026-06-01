"""XT.com Exchange REST API client with HMAC-SHA256 authentication."""

import hashlib
import hmac
import time
import urllib.parse
from typing import Any, Optional

import httpx


SPOT_BASE_URL = "https://sapi.xt.com"
FUTURES_BASE_URL = "https://fapi.xt.com"
COIN_FUTURES_BASE_URL = "https://dapi.xt.com"


class XTAPIError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"XT API Error {code}: {message}")


class XTClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        base_url: str = SPOT_BASE_URL,
        timeout: float = 10.0,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=timeout)

    def _sign(self, path: str, query_string: str = "", body: str = "") -> tuple[str, str]:
        timestamp = str(int(time.time() * 1000))
        parts = []
        if path:
            parts.append(f"path={path}")
        if query_string:
            parts.append(f"query={query_string}")
        if body:
            parts.append(f"body={body}")
        message = "&".join(parts)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return timestamp, signature

    def _auth_headers(self, path: str, query_string: str = "", body: str = "") -> dict:
        timestamp, signature = self._sign(path, query_string, body)
        return {
            "validate-appkey": self.api_key,
            "validate-timestamp": timestamp,
            "validate-signature": signature,
            "validate-algorithms": "HmacSHA256",
            "Content-Type": "application/json",
        }

    def _handle_response(self, response: httpx.Response) -> Any:
        data = response.json()
        # New API format: {"rc": 0, "mc": "SUCCESS", "result": {...}}
        # Old API format: {"code": 200, "data": {...}}
        if "rc" in data:
            if data["rc"] != 0:
                raise XTAPIError(data["rc"], data.get("mc", "Unknown error"))
            return data.get("result")
        if "code" in data:
            if data["code"] != 200:
                raise XTAPIError(data["code"], data.get("info", "Unknown error"))
            return data.get("data", data.get("result"))
        return data

    def get(self, path: str, params: Optional[dict] = None, auth: bool = False) -> Any:
        query_string = urllib.parse.urlencode(params or {})
        url = f"{self.base_url}{path}"
        if query_string:
            url = f"{url}?{query_string}"
        headers = self._auth_headers(path, query_string) if auth else {"Content-Type": "application/json"}
        response = self.client.get(url, headers=headers)
        response.raise_for_status()
        return self._handle_response(response)

    def post(self, path: str, body: Optional[dict] = None, params: Optional[dict] = None) -> Any:
        import json
        query_string = urllib.parse.urlencode(params or {})
        body_str = json.dumps(body or {}, separators=(",", ":"))
        headers = self._auth_headers(path, query_string, body_str)
        url = f"{self.base_url}{path}"
        if query_string:
            url = f"{url}?{query_string}"
        response = self.client.post(url, content=body_str, headers=headers)
        response.raise_for_status()
        return self._handle_response(response)

    def delete(self, path: str, params: Optional[dict] = None) -> Any:
        query_string = urllib.parse.urlencode(params or {})
        headers = self._auth_headers(path, query_string)
        url = f"{self.base_url}{path}"
        if query_string:
            url = f"{url}?{query_string}"
        response = self.client.delete(url, headers=headers)
        response.raise_for_status()
        return self._handle_response(response)

    # ────────────────────────────────────────────────────────────────
    # Public market data endpoints
    # ────────────────────────────────────────────────────────────────

    def get_server_time(self) -> dict:
        return self.get("/v4/public/time")

    def get_symbols(self) -> list:
        return self.get("/v4/public/symbol")

    def get_symbol(self, symbol: str) -> dict:
        return self.get("/v4/public/symbol", params={"symbol": symbol})

    def get_ticker(self, symbol: str) -> dict:
        return self.get("/v4/public/ticker/price", params={"symbol": symbol})

    def get_all_tickers(self) -> list:
        return self.get("/v4/public/ticker/price")

    def get_24h_ticker(self, symbol: str) -> dict:
        return self.get("/v4/public/ticker/24h", params={"symbol": symbol})

    def get_all_24h_tickers(self) -> list:
        return self.get("/v4/public/ticker/24h")

    def get_book_ticker(self, symbol: str) -> dict:
        return self.get("/v4/public/ticker/book", params={"symbol": symbol})

    def get_orderbook(self, symbol: str, limit: int = 20) -> dict:
        return self.get("/v4/public/depth", params={"symbol": symbol, "limit": limit})

    def get_klines(self, symbol: str, interval: str = "1h", limit: int = 100,
                   start_time: Optional[int] = None, end_time: Optional[int] = None) -> list:
        params: dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        return self.get("/v4/public/kline", params=params)

    def get_recent_trades(self, symbol: str, limit: int = 50) -> list:
        return self.get("/v4/public/trade/recent", params={"symbol": symbol, "limit": limit})

    # ────────────────────────────────────────────────────────────────
    # Private account / trading endpoints
    # ────────────────────────────────────────────────────────────────

    def get_balances(self) -> list:
        return self.get("/v4/balances", auth=True)

    def get_balance(self, currency: str) -> dict:
        return self.get("/v4/balance", params={"currency": currency}, auth=True)

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: str,
        price: Optional[str] = None,
        client_order_id: Optional[str] = None,
        time_in_force: Optional[str] = None,
    ) -> dict:
        body: dict[str, Any] = {
            "symbol": symbol,
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": quantity,
        }
        if price:
            body["price"] = price
        if client_order_id:
            body["clientOrderId"] = client_order_id
        if time_in_force:
            body["timeInForce"] = time_in_force.upper()
        return self.post("/v4/order", body=body)

    def cancel_order(self, order_id: str) -> dict:
        return self.delete("/v4/order", params={"orderId": order_id})

    def cancel_all_orders(self, symbol: str) -> dict:
        return self.delete("/v4/openOrders", params={"symbol": symbol})

    def get_order(self, order_id: str) -> dict:
        return self.get("/v4/order", params={"orderId": order_id}, auth=True)

    def get_open_orders(self, symbol: Optional[str] = None) -> list:
        params = {}
        if symbol:
            params["symbol"] = symbol
        return self.get("/v4/openOrders", params=params, auth=True)

    def get_order_history(
        self,
        symbol: Optional[str] = None,
        limit: int = 100,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> list:
        params: dict[str, Any] = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        return self.get("/v4/historyOrders", params=params, auth=True)

    def get_trade_history(
        self,
        symbol: Optional[str] = None,
        limit: int = 100,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> list:
        params: dict[str, Any] = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        return self.get("/v4/trades", params=params, auth=True)

    def close(self):
        self.client.close()
