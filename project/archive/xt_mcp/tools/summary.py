"""MCP tool for comprehensive symbol research report."""

from __future__ import annotations

import asyncio
import logging
import time

from regime.adx import compute_adx
from regime.classifier import RegimeClassifier
from risk.manager import RiskManager
from signals.engine import SignalEngine
from xt_mcp.exceptions import XTMCPError
from xt_mcp.tools.market import get_ticker as _get_ticker

logger = logging.getLogger(__name__)


def _error(exc: Exception) -> dict:
    logger.error("%s: %s", type(exc).__name__, exc)
    return {"error": True, "code": type(exc).__name__, "message": str(exc)}


async def get_symbol_report(
    symbol: str,
    interval: str = "1h",
    market: str = "spot",
    strategy: str = "combined_momentum",
    lookback: int = 300,
    capital: float | None = None,
    risk_pct: float = 1.0,
    atr_multiplier: float = 2.0,
    reward_ratio: float = 2.0,
) -> dict:
    """
    Comprehensive research report for a single symbol.

    Combines in one call:
    - Live ticker (price, 24h change, volume)
    - Current market regime (ADX-based) + dominant regime over lookback
    - Recent trading signals from the chosen strategy
    - ATR value for volatility context
    - Risk parameters (if capital is supplied): stop, target, position size

    Args:
        symbol:         Trading pair e.g. 'btc_usdt'.
        interval:       Candle interval for analysis (default '1h').
        market:         'spot' or 'futures' (default 'spot').
        strategy:       Signal strategy name (default 'combined_momentum').
        lookback:       Historical bars to fetch (default 300).
        capital:        Account capital in quote currency — enables risk section.
        risk_pct:       Capital percentage to risk per trade (default 1.0 = 1 %).
        atr_multiplier: ATR multiples for stop distance (default 2.0).
        reward_ratio:   Target / stop distance ratio (default 2.0 → 1:2 R:R).

    Returns:
        Unified report with sections: ticker, regime, signals, atr, risk (optional).
    """
    try:
        engine = SignalEngine()

        # Concurrent: ticker + signals/df
        ticker_task   = asyncio.create_task(_get_ticker(symbol, market))
        signals_task  = asyncio.create_task(
            engine.run_with_df(symbol, interval, strategy, market, lookback)
        )

        ticker_data        = await ticker_task
        signals, df        = await signals_task

        # ── Regime ───────────────────────────────────────────────────────────
        classifier = RegimeClassifier()
        try:
            regime_result = classifier.classify(df, symbol, interval, market)
            regime_section: dict = {
                "current": regime_result.current_regime.value,
                "description": regime_result.current_regime.description(),
                "dominant": regime_result.dominant_regime.value,
                "adx": round(regime_result.current_adx, 2),
                "di_plus": round(regime_result.current_di_plus, 2),
                "di_minus": round(regime_result.current_di_minus, 2),
                "atr_ratio": round(regime_result.current_atr_ratio, 3),
                "distribution": regime_result.regime_distribution,
            }
        except ValueError as e:
            regime_section = {"current": "UNKNOWN", "note": str(e)}

        # ── ATR ──────────────────────────────────────────────────────────────
        adx_df     = compute_adx(df, period=14)
        atr_series = adx_df["atr"].dropna()
        current_atr: float | None = float(atr_series.iloc[-1]) if not atr_series.empty else None

        # ── Signals ──────────────────────────────────────────────────────────
        buy_count  = sum(1 for s in signals if s.signal_type.value == "BUY")
        sell_count = sum(1 for s in signals if s.signal_type.value == "SELL")
        signals_section: dict = {
            "strategy": strategy,
            "total": len(signals),
            "buy_count": buy_count,
            "sell_count": sell_count,
            "recent": [s.to_dict() for s in signals[-5:]],
        }

        # ── Risk (optional) ──────────────────────────────────────────────────
        risk_section: dict | None = None
        if capital and capital > 0 and current_atr:
            entry_price = float(df["close"].iloc[-1])
            mgr = RiskManager(
                default_atr_multiplier=atr_multiplier,
                default_reward_ratio=reward_ratio,
            )
            st  = mgr.stops_from_atr(entry_price, "long", current_atr, atr_multiplier, reward_ratio)
            pos = mgr.size_fixed(capital, risk_pct / 100.0, entry_price, st.stop_price)
            risk_section = {
                "capital": capital,
                "risk_pct": risk_pct,
                "entry_price": entry_price,
                "atr": round(current_atr, 8),
                "stop_price": round(st.stop_price, 8),
                "target_price": round(st.target_price, 8),
                "risk_reward_ratio": st.risk_reward_ratio,
                "quantity": round(pos.quantity, 8),
                "risk_amount": round(pos.risk_amount, 4),
                "position_value": round(pos.position_value, 4),
            }

        return {
            "error": False,
            "symbol": symbol,
            "interval": interval,
            "market": market,
            "ticker": None if ticker_data.get("error") else ticker_data,
            "regime": regime_section,
            "signals": signals_section,
            "atr": round(current_atr, 8) if current_atr else None,
            "risk": risk_section,
            "generated_at": int(time.time() * 1000),
        }

    except XTMCPError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("get_symbol_report failed")
        return _error(exc)
