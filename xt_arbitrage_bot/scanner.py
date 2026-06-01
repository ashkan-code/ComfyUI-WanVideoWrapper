"""
Triangle arbitrage scanner for XT.com.

Algorithm:
  For each base currency B (e.g. USDT):
    For each pair (B/X):
      For each pair (X/Y) or (Y/X):
        If (Y/B) or (B/Y) exists → we have a triangle B→X→Y→B
        Calculate net profit after fees using real bid/ask prices
        If profit > threshold → yield opportunity
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from config import Config

log = logging.getLogger("scanner")


@dataclass
class Leg:
    symbol: str          # e.g. "btc_usdt"
    side: str            # "BUY" or "SELL"
    price: float         # ask (for BUY) or bid (for SELL)
    base: str            # base currency of the pair
    quote: str           # quote currency of the pair


@dataclass
class Triangle:
    leg1: Leg
    leg2: Leg
    leg3: Leg

    @property
    def key(self) -> str:
        return f"{self.leg1.symbol}|{self.leg2.symbol}|{self.leg3.symbol}"


@dataclass
class Opportunity:
    triangle: Triangle
    gross_profit_pct: float   # before fees
    net_profit_pct: float     # after all 3 fees
    start_amount: float       # USDT in
    end_amount: float         # USDT out (estimated)
    profit_usdt: float        # absolute profit

    def __str__(self) -> str:
        t = self.triangle
        return (
            f"[{self.net_profit_pct:+.4f}%] "
            f"{t.leg1.symbol}({t.leg1.side}) → "
            f"{t.leg2.symbol}({t.leg2.side}) → "
            f"{t.leg3.symbol}({t.leg3.side}) | "
            f"in={self.start_amount:.2f} out={self.end_amount:.4f} "
            f"profit={self.profit_usdt:.4f} USDT"
        )


class TickerGraph:
    """
    Builds a currency graph from ticker data.
    graph[currency_a][currency_b] = {"symbol": str, "bid": float, "ask": float}
    """

    def __init__(self):
        self.graph: dict[str, dict[str, dict]] = {}

    def add(self, symbol: str, bid: float, ask: float):
        parts = symbol.split("_")
        if len(parts) != 2:
            return
        base, quote = parts[0], parts[1]
        if bid <= 0 or ask <= 0:
            return

        self._set(base, quote, symbol, bid, ask)
        self._set(quote, base, symbol, bid, ask)

    def _set(self, from_c: str, to_c: str, symbol: str, bid: float, ask: float):
        if from_c not in self.graph:
            self.graph[from_c] = {}
        self.graph[from_c][to_c] = {"symbol": symbol, "bid": bid, "ask": ask}

    def neighbors(self, currency: str) -> dict[str, dict]:
        return self.graph.get(currency, {})


def _convert_amount(amount: float, from_c: str, to_c: str, edge: dict, fee: float) -> tuple[float, Leg]:
    """
    Convert `amount` of `from_c` into `to_c` using the given edge.
    Returns (resulting_amount, Leg).

    If from_c == base of pair → we SELL base, get quote  → use BID price
    If from_c == quote of pair → we BUY base, spend quote → use ASK price
    """
    symbol = edge["symbol"]
    base, quote = symbol.split("_")

    if from_c == base:
        # Selling base for quote: amount_base * bid = amount_quote
        price = edge["bid"]
        side = "SELL"
        out = amount * price * (1 - fee)
    else:
        # Buying base with quote: amount_quote / ask = amount_base
        price = edge["ask"]
        side = "BUY"
        out = (amount / price) * (1 - fee)

    leg = Leg(symbol=symbol, side=side, price=price, base=base, quote=quote)
    return out, leg


def _scan_triangles(graph: TickerGraph, base: str, start_amount: float, fee: float, min_profit: float):
    """
    Enumerate all base→X→Y→base triangles and yield profitable ones.
    """
    opportunities: list[Opportunity] = []

    for mid1, edge1 in graph.neighbors(base).items():
        amount1, leg1 = _convert_amount(start_amount, base, mid1, edge1, fee)
        if amount1 <= 0:
            continue

        for mid2, edge2 in graph.neighbors(mid1).items():
            if mid2 == base:
                continue  # skip direct back-conversion (not a triangle)

            amount2, leg2 = _convert_amount(amount1, mid1, mid2, edge2, fee)
            if amount2 <= 0:
                continue

            # Check if we can get back to base from mid2
            back_edges = graph.neighbors(mid2)
            if base not in back_edges:
                continue

            edge3 = back_edges[base]
            end_amount, leg3 = _convert_amount(amount2, mid2, base, edge3, fee)
            if end_amount <= 0:
                continue

            net_profit_pct = (end_amount - start_amount) / start_amount * 100
            # Gross = what we'd have with zero fees
            raw1 = start_amount / leg1.price if leg1.side == "BUY" else start_amount * leg1.price
            raw2 = raw1 / leg2.price if leg2.side == "BUY" else raw1 * leg2.price
            raw3 = raw2 / leg3.price if leg3.side == "BUY" else raw2 * leg3.price
            gross_profit_pct = (raw3 - start_amount) / start_amount * 100

            if net_profit_pct >= min_profit:
                opp = Opportunity(
                    triangle=Triangle(leg1, leg2, leg3),
                    gross_profit_pct=round(gross_profit_pct, 6),
                    net_profit_pct=round(net_profit_pct, 6),
                    start_amount=start_amount,
                    end_amount=round(end_amount, 6),
                    profit_usdt=round(end_amount - start_amount, 6),
                )
                opportunities.append(opp)

    return sorted(opportunities, key=lambda o: o.net_profit_pct, reverse=True)


def find_opportunities(tickers: list[dict], config: Config) -> list[Opportunity]:
    """
    Build graph from tickers and find all profitable triangles.
    `tickers` is the raw list from XTClient.get_all_book_tickers() or similar.
    Expected fields: symbol, bidPrice (or bp), askPrice (or ap).
    """
    graph = TickerGraph()

    for t in tickers:
        symbol = t.get("s") or t.get("symbol", "")
        bid = float(t.get("bp") or t.get("bidPrice") or t.get("bid") or 0)
        ask = float(t.get("ap") or t.get("askPrice") or t.get("ask") or 0)
        if symbol and bid > 0 and ask > 0:
            graph.add(symbol.lower(), bid, ask)

    all_opportunities: list[Opportunity] = []
    for base in config.base_currencies:
        opps = _scan_triangles(
            graph,
            base=base,
            start_amount=config.trade_amount_usdt,
            fee=config.trading_fee,
            min_profit=config.min_profit_pct,
        )
        all_opportunities.extend(opps)

    # Deduplicate by triangle key
    seen: set[str] = set()
    unique: list[Opportunity] = []
    for opp in sorted(all_opportunities, key=lambda o: o.net_profit_pct, reverse=True):
        k = opp.triangle.key
        if k not in seen:
            seen.add(k)
            unique.append(opp)

    return unique


def verify_with_orderbook(
    opp: Opportunity,
    orderbooks: dict[str, dict],
    config: Config,
) -> Optional[Opportunity]:
    """
    Re-price an opportunity using actual orderbook depth (walks the book).
    Returns updated Opportunity or None if no longer profitable.
    """
    try:
        legs = [opp.triangle.leg1, opp.triangle.leg2, opp.triangle.leg3]
        amount = opp.start_amount

        for leg in legs:
            ob = orderbooks.get(leg.symbol)
            if not ob:
                return None  # Can't verify → skip

            if leg.side == "BUY":
                levels = ob.get("asks") or ob.get("a", [])
                remaining = amount
                cost = 0.0
                base_out = 0.0
                for level in levels:
                    p, q = float(level[0]), float(level[1])
                    can_buy = min(q, remaining / p)
                    cost += can_buy * p
                    base_out += can_buy
                    remaining -= can_buy * p
                    if remaining <= 0:
                        break
                if remaining > 0:
                    return None  # Not enough liquidity
                effective_price = cost / base_out if base_out > 0 else 0
                amount = base_out * (1 - config.trading_fee)

            else:  # SELL
                levels = ob.get("bids") or ob.get("b", [])
                remaining_base = amount
                usdt_out = 0.0
                for level in levels:
                    p, q = float(level[0]), float(level[1])
                    can_sell = min(q, remaining_base)
                    usdt_out += can_sell * p
                    remaining_base -= can_sell
                    if remaining_base <= 0:
                        break
                if remaining_base > 0:
                    return None  # Not enough liquidity
                amount = usdt_out * (1 - config.trading_fee)

        end_amount = amount
        net_profit_pct = (end_amount - opp.start_amount) / opp.start_amount * 100

        if net_profit_pct < config.min_profit_pct:
            return None

        return Opportunity(
            triangle=opp.triangle,
            gross_profit_pct=opp.gross_profit_pct,
            net_profit_pct=round(net_profit_pct, 6),
            start_amount=opp.start_amount,
            end_amount=round(end_amount, 6),
            profit_usdt=round(end_amount - opp.start_amount, 6),
        )
    except Exception as e:
        log.debug(f"Orderbook verification failed: {e}")
        return None
