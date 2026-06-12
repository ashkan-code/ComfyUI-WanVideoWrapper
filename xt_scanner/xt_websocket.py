"""
XT.com WebSocket client — fetches top USDT pairs and streams
live trade + depth data into shared state dicts.
"""

import asyncio
import json
import logging
import time
from collections import deque
from typing import Dict, List

import aiohttp
import websockets
from websockets.exceptions import ConnectionClosed

import config

logger = logging.getLogger(__name__)

# Shared state written by this module, read by signals.py and dashboard.py
# { symbol: deque([{"price": float, "qty": float, "ts": float, "side": "buy"|"sell"}, ...]) }
trade_data: Dict[str, deque] = {}

# { symbol: {"bids": [[price, qty], ...], "asks": [[price, qty], ...]} }
orderbook_data: Dict[str, dict] = {}

# { symbol: float }  — latest trade price
last_price: Dict[str, float] = {}


# ──────────────────────────────────────────────
# REST — symbol discovery
# ──────────────────────────────────────────────

async def fetch_usdt_symbols() -> List[str]:
    """Return all ONLINE USDT spot symbols sorted by 24 h quote volume (desc)."""
    url = config.XT_REST_BASE + config.XT_SYMBOLS_ENDPOINT
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()
            data = await resp.json()

    symbols = []
    for item in data.get("result", {}).get("symbols", []):
        if (
            item.get("quoteCurrency", "").lower() == "usdt"
            and item.get("state", "").upper() == "ONLINE"
        ):
            symbols.append(item["symbol"])

    logger.info("Found %d active USDT symbols", len(symbols))
    return symbols


async def fetch_top_symbols_by_volume(n: int = config.TOP_COINS_COUNT) -> List[str]:
    """
    Fetch 24 h tickers from the REST API to rank by quote volume,
    then return the top-N symbol names.
    """
    url = config.XT_REST_BASE + "/v4/public/ticker"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                resp.raise_for_status()
                data = await resp.json()

        tickers = data.get("result", [])
        usdt_tickers = [
            t for t in tickers
            if str(t.get("s", "")).endswith("_usdt")
        ]
        # sort descending by quoteVolume ("qv")
        usdt_tickers.sort(key=lambda t: float(t.get("qv", 0) or 0), reverse=True)
        top = [t["s"] for t in usdt_tickers[:n]]
        logger.info("Top %d symbols by volume: %s", n, top[:5])
        return top
    except Exception as exc:
        logger.warning("Could not fetch tickers for volume ranking (%s); falling back to symbol list", exc)
        all_syms = await fetch_usdt_symbols()
        return all_syms[:n]


# ──────────────────────────────────────────────
# WebSocket helpers
# ──────────────────────────────────────────────

def _init_symbol(symbol: str) -> None:
    if symbol not in trade_data:
        trade_data[symbol] = deque(maxlen=5000)
    if symbol not in orderbook_data:
        orderbook_data[symbol] = {"bids": [], "asks": []}


def _handle_trade(symbol: str, payload: dict) -> None:
    """Parse a trade event and append to trade_data."""
    # XT trade payload shape: {"t": ts_ms, "p": "price", "q": "qty", "b": true/false}
    # 'b' is True when the buyer is the market maker (i.e., seller aggressed) → sell-side
    try:
        price = float(payload["p"])
        qty = float(payload["q"])
        ts = float(payload.get("t", time.time() * 1000)) / 1000
        # b=True → maker buy → aggressor is seller
        side = "sell" if payload.get("b", False) else "buy"

        _init_symbol(symbol)
        trade_data[symbol].append({"price": price, "qty": qty, "ts": ts, "side": side})
        last_price[symbol] = price
    except (KeyError, ValueError) as exc:
        logger.debug("Bad trade payload for %s: %s | %s", symbol, exc, payload)


def _handle_depth(symbol: str, payload: dict) -> None:
    """Replace the full order-book snapshot."""
    try:
        _init_symbol(symbol)
        bids = [[float(p), float(q)] for p, q in payload.get("b", [])]
        asks = [[float(p), float(q)] for p, q in payload.get("a", [])]
        # keep sorted: bids desc, asks asc
        bids.sort(key=lambda x: x[0], reverse=True)
        asks.sort(key=lambda x: x[0])
        orderbook_data[symbol] = {"bids": bids, "asks": asks}
    except (KeyError, ValueError) as exc:
        logger.debug("Bad depth payload for %s: %s", symbol, exc)


# ──────────────────────────────────────────────
# Subscription builder
# ──────────────────────────────────────────────

def _build_subscriptions(symbols: List[str]) -> List[dict]:
    """Build the subscribe messages for trade + depth channels."""
    msgs = []
    msg_id = 1
    for sym in symbols:
        msgs.append({
            "method": "subscribe",
            "params": [f"trade@{sym}"],
            "id": msg_id,
        })
        msg_id += 1
        msgs.append({
            "method": "subscribe",
            "params": [f"depth@{sym},{config.ORDER_BOOK_DEPTH}"],
            "id": msg_id,
        })
        msg_id += 1
    return msgs


# ──────────────────────────────────────────────
# Main WebSocket loop
# ──────────────────────────────────────────────

async def run_websocket(symbols: List[str], stop_event: asyncio.Event) -> None:
    """
    Connect to the XT.com public WebSocket, subscribe to trade+depth
    for all given symbols, and pump messages until stop_event is set.
    Reconnects automatically on disconnect.
    """
    sub_msgs = _build_subscriptions(symbols)
    backoff = 1

    while not stop_event.is_set():
        try:
            logger.info("Connecting to %s …", config.XT_WS_URL)
            async with websockets.connect(
                config.XT_WS_URL,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
            ) as ws:
                backoff = 1  # reset on successful connect
                logger.info("Connected. Subscribing to %d channels …", len(sub_msgs))

                # send subscriptions in batches to avoid flooding
                for i, msg in enumerate(sub_msgs):
                    await ws.send(json.dumps(msg))
                    if i % 10 == 9:
                        await asyncio.sleep(0.05)

                # receive loop
                _debug_count = 0
                async for raw in ws:
                    if stop_event.is_set():
                        break
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    # log first 10 raw messages to identify XT.com format
                    if _debug_count < 10:
                        logger.info("RAW MSG #%d: %s", _debug_count, str(msg)[:300])
                        _debug_count += 1

                    # XT.com may use "topic" or "event" as the channel key
                    topic = (
                        msg.get("topic")
                        or msg.get("event")
                        or msg.get("e")
                        or msg.get("channel")
                        or ""
                    )
                    data = msg.get("data") or msg.get("d") or {}

                    if not topic:
                        continue

                    if topic.startswith("trade@"):
                        symbol = topic.split("@", 1)[1]
                        if isinstance(data, list):
                            for trade in data:
                                _handle_trade(symbol, trade)
                        elif isinstance(data, dict):
                            _handle_trade(symbol, data)

                    elif topic.startswith("depth@"):
                        symbol = topic.split("@", 1)[1].split(",")[0]
                        _handle_depth(symbol, data)

        except ConnectionClosed as exc:
            logger.warning("WebSocket closed: %s. Reconnecting in %ds …", exc, backoff)
        except Exception as exc:
            logger.error("WebSocket error: %s. Reconnecting in %ds …", exc, backoff)

        if not stop_event.is_set():
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
