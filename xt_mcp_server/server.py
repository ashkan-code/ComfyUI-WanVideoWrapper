#!/usr/bin/env python3
"""MCP server for XT.com cryptocurrency exchange."""

import json
import os
from typing import Any, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolResult,
    ListToolsResult,
    TextContent,
    Tool,
)

from xt_api import XTAPIError, XTClient

# ────────────────────────────────────────────────────────────────────────────
# Server setup
# ────────────────────────────────────────────────────────────────────────────

app = Server("xt-exchange")

_client: Optional[XTClient] = None


def get_client() -> XTClient:
    global _client
    if _client is None:
        _client = XTClient(
            api_key=os.environ.get("XT_API_KEY"),
            api_secret=os.environ.get("XT_API_SECRET"),
        )
    return _client


def ok(data: Any) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))])


def err(message: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=f"Error: {message}")], isError=True)


# ────────────────────────────────────────────────────────────────────────────
# Tool definitions
# ────────────────────────────────────────────────────────────────────────────

TOOLS = [
    # ── Public / Market data ────────────────────────────────────────────────
    Tool(
        name="xt_server_time",
        description="Get the current server time from XT.com exchange.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="xt_get_symbols",
        description="Get all available trading symbols/pairs on XT.com.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="xt_get_ticker",
        description="Get the latest price ticker for a symbol.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Trading pair, e.g. btc_usdt"},
            },
            "required": ["symbol"],
        },
    ),
    Tool(
        name="xt_get_all_tickers",
        description="Get the latest price for all trading symbols.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="xt_get_24h_ticker",
        description="Get 24-hour price change statistics for a symbol (open, high, low, close, volume).",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Trading pair, e.g. btc_usdt"},
            },
            "required": ["symbol"],
        },
    ),
    Tool(
        name="xt_get_all_24h_tickers",
        description="Get 24-hour price change statistics for all symbols.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="xt_get_book_ticker",
        description="Get best bid and ask price for a symbol.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Trading pair, e.g. btc_usdt"},
            },
            "required": ["symbol"],
        },
    ),
    Tool(
        name="xt_get_orderbook",
        description="Get the order book (bids and asks) for a symbol.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Trading pair, e.g. btc_usdt"},
                "limit": {
                    "type": "integer",
                    "description": "Number of levels to return (default 20, max 200)",
                    "default": 20,
                },
            },
            "required": ["symbol"],
        },
    ),
    Tool(
        name="xt_get_klines",
        description="Get candlestick/kline data for a symbol.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Trading pair, e.g. btc_usdt"},
                "interval": {
                    "type": "string",
                    "description": "Kline interval: 1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w",
                    "enum": ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"],
                    "default": "1h",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of candles to return (default 100, max 1000)",
                    "default": 100,
                },
                "start_time": {
                    "type": "integer",
                    "description": "Start time in milliseconds (Unix timestamp)",
                },
                "end_time": {
                    "type": "integer",
                    "description": "End time in milliseconds (Unix timestamp)",
                },
            },
            "required": ["symbol"],
        },
    ),
    Tool(
        name="xt_get_recent_trades",
        description="Get the most recent trades for a symbol.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Trading pair, e.g. btc_usdt"},
                "limit": {
                    "type": "integer",
                    "description": "Number of trades to return (default 50, max 200)",
                    "default": 50,
                },
            },
            "required": ["symbol"],
        },
    ),
    # ── Private / Account & Trading ─────────────────────────────────────────
    Tool(
        name="xt_get_balances",
        description="Get all account balances. Requires XT_API_KEY and XT_API_SECRET environment variables.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="xt_get_balance",
        description="Get balance for a specific currency. Requires API credentials.",
        inputSchema={
            "type": "object",
            "properties": {
                "currency": {"type": "string", "description": "Currency code, e.g. usdt, btc"},
            },
            "required": ["currency"],
        },
    ),
    Tool(
        name="xt_place_order",
        description=(
            "Place a new order on XT.com. Requires API credentials. "
            "Side: BUY or SELL. Type: LIMIT or MARKET."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Trading pair, e.g. btc_usdt"},
                "side": {
                    "type": "string",
                    "description": "Order side: BUY or SELL",
                    "enum": ["BUY", "SELL"],
                },
                "order_type": {
                    "type": "string",
                    "description": "Order type: LIMIT or MARKET",
                    "enum": ["LIMIT", "MARKET"],
                },
                "quantity": {
                    "type": "string",
                    "description": "Order quantity (as string to preserve precision)",
                },
                "price": {
                    "type": "string",
                    "description": "Order price (required for LIMIT orders)",
                },
                "client_order_id": {
                    "type": "string",
                    "description": "Optional custom order ID",
                },
                "time_in_force": {
                    "type": "string",
                    "description": "Time in force: GTC (Good Till Cancel), IOC, FOK",
                    "enum": ["GTC", "IOC", "FOK"],
                },
            },
            "required": ["symbol", "side", "order_type", "quantity"],
        },
    ),
    Tool(
        name="xt_cancel_order",
        description="Cancel an open order by order ID. Requires API credentials.",
        inputSchema={
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "The order ID to cancel"},
            },
            "required": ["order_id"],
        },
    ),
    Tool(
        name="xt_cancel_all_orders",
        description="Cancel all open orders for a symbol. Requires API credentials.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Trading pair, e.g. btc_usdt"},
            },
            "required": ["symbol"],
        },
    ),
    Tool(
        name="xt_get_order",
        description="Get details of a specific order by order ID. Requires API credentials.",
        inputSchema={
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "The order ID to query"},
            },
            "required": ["order_id"],
        },
    ),
    Tool(
        name="xt_get_open_orders",
        description="Get all open (unfilled) orders. Requires API credentials.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Filter by trading pair (optional), e.g. btc_usdt",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="xt_get_order_history",
        description="Get order history. Requires API credentials.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Filter by trading pair (optional)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of records to return (default 100)",
                    "default": 100,
                },
                "start_time": {
                    "type": "integer",
                    "description": "Start time in milliseconds",
                },
                "end_time": {
                    "type": "integer",
                    "description": "End time in milliseconds",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="xt_get_trade_history",
        description="Get trade history (filled orders). Requires API credentials.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Filter by trading pair (optional)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of records to return (default 100)",
                    "default": 100,
                },
                "start_time": {
                    "type": "integer",
                    "description": "Start time in milliseconds",
                },
                "end_time": {
                    "type": "integer",
                    "description": "End time in milliseconds",
                },
            },
            "required": [],
        },
    ),
]


# ────────────────────────────────────────────────────────────────────────────
# Handlers
# ────────────────────────────────────────────────────────────────────────────

@app.list_tools()
async def list_tools() -> ListToolsResult:
    return ListToolsResult(tools=TOOLS)


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> CallToolResult:
    args = arguments or {}
    client = get_client()

    try:
        # ── Public endpoints ────────────────────────────────────────────────
        if name == "xt_server_time":
            return ok(client.get_server_time())

        if name == "xt_get_symbols":
            return ok(client.get_symbols())

        if name == "xt_get_ticker":
            return ok(client.get_ticker(args["symbol"]))

        if name == "xt_get_all_tickers":
            return ok(client.get_all_tickers())

        if name == "xt_get_24h_ticker":
            return ok(client.get_24h_ticker(args["symbol"]))

        if name == "xt_get_all_24h_tickers":
            return ok(client.get_all_24h_tickers())

        if name == "xt_get_book_ticker":
            return ok(client.get_book_ticker(args["symbol"]))

        if name == "xt_get_orderbook":
            return ok(client.get_orderbook(args["symbol"], limit=args.get("limit", 20)))

        if name == "xt_get_klines":
            return ok(client.get_klines(
                symbol=args["symbol"],
                interval=args.get("interval", "1h"),
                limit=args.get("limit", 100),
                start_time=args.get("start_time"),
                end_time=args.get("end_time"),
            ))

        if name == "xt_get_recent_trades":
            return ok(client.get_recent_trades(args["symbol"], limit=args.get("limit", 50)))

        # ── Private endpoints ───────────────────────────────────────────────
        if not client.api_key or not client.api_secret:
            return err("API credentials not set. Please set XT_API_KEY and XT_API_SECRET environment variables.")

        if name == "xt_get_balances":
            return ok(client.get_balances())

        if name == "xt_get_balance":
            return ok(client.get_balance(args["currency"]))

        if name == "xt_place_order":
            return ok(client.place_order(
                symbol=args["symbol"],
                side=args["side"],
                order_type=args["order_type"],
                quantity=args["quantity"],
                price=args.get("price"),
                client_order_id=args.get("client_order_id"),
                time_in_force=args.get("time_in_force"),
            ))

        if name == "xt_cancel_order":
            return ok(client.cancel_order(args["order_id"]))

        if name == "xt_cancel_all_orders":
            return ok(client.cancel_all_orders(args["symbol"]))

        if name == "xt_get_order":
            return ok(client.get_order(args["order_id"]))

        if name == "xt_get_open_orders":
            return ok(client.get_open_orders(symbol=args.get("symbol")))

        if name == "xt_get_order_history":
            return ok(client.get_order_history(
                symbol=args.get("symbol"),
                limit=args.get("limit", 100),
                start_time=args.get("start_time"),
                end_time=args.get("end_time"),
            ))

        if name == "xt_get_trade_history":
            return ok(client.get_trade_history(
                symbol=args.get("symbol"),
                limit=args.get("limit", 100),
                start_time=args.get("start_time"),
                end_time=args.get("end_time"),
            ))

        return err(f"Unknown tool: {name}")

    except XTAPIError as e:
        return err(str(e))
    except Exception as e:
        return err(f"Unexpected error: {e}")


# ────────────────────────────────────────────────────────────────────────────
# Entry point
# ────────────────────────────────────────────────────────────────────────────

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
