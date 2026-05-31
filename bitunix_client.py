import hashlib
import time
import uuid
import requests
import json

BASE_URL = "https://fapi.bitunix.com"


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _sign(api_key: str, secret_key: str, nonce: str, timestamp: str,
          query_params: str = "", body: str = "") -> str:
    digest = _sha256(nonce + timestamp + api_key + query_params + body)
    return _sha256(digest + secret_key)


def _headers(api_key: str, secret_key: str, query_params: str = "", body: str = "") -> dict:
    nonce = uuid.uuid4().hex  # 32-char random string
    timestamp = str(int(time.time() * 1000))
    sign = _sign(api_key, secret_key, nonce, timestamp, query_params, body)
    return {
        "api-key": api_key,
        "nonce": nonce,
        "timestamp": timestamp,
        "sign": sign,
        "Content-Type": "application/json",
    }


class BitunixClient:
    def __init__(self, api_key: str, secret_key: str):
        self.api_key = api_key
        self.secret_key = secret_key
        self.session = requests.Session()

    def _get(self, path: str, params: dict = None) -> dict:
        query_string = ""
        if params:
            sorted_items = sorted(params.items())
            query_string = "".join(f"{k}{v}" for k, v in sorted_items)
        headers = _headers(self.api_key, self.secret_key, query_string, "")
        url = BASE_URL + path
        resp = self.session.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict = None, params: dict = None) -> dict:
        query_string = ""
        if params:
            sorted_items = sorted(params.items())
            query_string = "".join(f"{k}{v}" for k, v in sorted_items)
        body_str = json.dumps(body, separators=(",", ":")) if body else ""
        headers = _headers(self.api_key, self.secret_key, query_string, body_str)
        url = BASE_URL + path
        resp = self.session.post(url, headers=headers, params=params,
                                 data=body_str, timeout=10)
        resp.raise_for_status()
        return resp.json()

    # ── Account ──────────────────────────────────────────────────────────────

    def get_account(self, margin_coin: str = "USDT") -> dict:
        """Get futures account balance."""
        params = {"marginCoin": margin_coin}
        return self._get("/api/v1/futures/account", params)

    def get_positions(self, symbol: str = None) -> dict:
        """Get open positions. Pass symbol to filter (e.g. 'BTCUSDT')."""
        params = {}
        if symbol:
            params["symbol"] = symbol
        return self._get("/api/v1/futures/position/get_pending_positions", params or None)

    # ── Market (public, no auth needed but using same client for convenience) ─

    def get_ticker(self, *symbols: str) -> dict:
        """Get ticker(s) for one or more symbols (public endpoint)."""
        resp = self.session.get(
            f"{BASE_URL}/api/v1/futures/market/tickers",
            params={"symbols": ",".join(symbols)},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    # ── Orders ────────────────────────────────────────────────────────────────

    def get_pending_orders(self, symbol: str = None) -> dict:
        """Get open/pending orders."""
        params = {}
        if symbol:
            params["symbol"] = symbol
        return self._get("/api/v1/futures/trade/get_pending_orders", params or None)

    def place_order(self, symbol: str, side: str, order_type: str,
                    qty: float, price: float = None, **kwargs) -> dict:
        """
        Place a futures order.
        side: 'BUY' or 'SELL'
        order_type: 'LIMIT' or 'MARKET'
        """
        body = {
            "symbol": symbol,
            "side": side,
            "orderType": order_type,
            "qty": str(qty),
        }
        if price is not None:
            body["price"] = str(price)
        body.update(kwargs)
        return self._post("/api/v1/futures/trade/place_order", body)

    def cancel_order(self, symbol: str, order_id: str) -> dict:
        """Cancel an order by ID."""
        body = {"symbol": symbol, "orderId": order_id}
        return self._post("/api/v1/futures/trade/cancel_order", body)


if __name__ == "__main__":
    API_KEY = "68f0a1765f124bacb847afa8db78e480"
    SECRET_KEY = "159808597389a1cd1fc429f9f469209b"

    client = BitunixClient(API_KEY, SECRET_KEY)

    print("=== Testing Bitunix connection ===\n")

    # Test 1: public ticker (no auth)
    print("[1] BTC/USDT ticker (public):")
    try:
        ticker = client.get_ticker("BTCUSDT", "ETHUSDT")
        print(json.dumps(ticker, indent=2))
    except Exception as e:
        print(f"  ERROR: {e}")

    print()

    # Test 2: account balance (private)
    print("[2] Account balance (private):")
    try:
        account = client.get_account()
        print(json.dumps(account, indent=2))
    except Exception as e:
        print(f"  ERROR: {e}")

    print()

    # Test 3: open positions (private)
    print("[3] Open positions (private):")
    try:
        positions = client.get_positions()
        print(json.dumps(positions, indent=2))
    except Exception as e:
        print(f"  ERROR: {e}")
