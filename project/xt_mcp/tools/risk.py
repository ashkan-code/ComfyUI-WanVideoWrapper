"""MCP tools for position sizing and risk management."""

from __future__ import annotations

import logging

from regime.adx import compute_adx
from risk.manager import RiskManager
from signals.engine import SignalEngine
from xt_mcp.exceptions import XTMCPError

logger = logging.getLogger(__name__)


def _error(exc: Exception) -> dict:
    logger.error("%s: %s", type(exc).__name__, exc)
    return {"error": True, "code": type(exc).__name__, "message": str(exc)}


async def calculate_position_size(
    capital: float,
    entry_price: float,
    stop_price: float,
    risk_pct: float = 1.0,
    method: str = "fixed",
    win_rate: float | None = None,
    avg_win: float | None = None,
    avg_loss: float | None = None,
) -> dict:
    """
    Calculate position size given a known entry and stop price.

    Two sizing methods:
    - 'fixed'  : risk exactly risk_pct% of capital between entry and stop.
    - 'kelly'  : use half-Kelly fraction derived from win_rate / avg_win / avg_loss.
                 Requires win_rate, avg_win, avg_loss (from a backtest result).
                 Kelly is capped at 25% of capital.

    Args:
        capital:    Total account capital in quote currency (e.g. USDT).
        entry_price: Planned entry price.
        stop_price:  Hard stop-loss price.
        risk_pct:   Percentage of capital to risk per trade (default 1.0 = 1%).
        method:     'fixed' or 'kelly'.
        win_rate:   Backtest win rate 0-1 (required for kelly).
        avg_win:    Average winning trade value (required for kelly).
        avg_loss:   Average losing trade value as positive number (required for kelly).

    Returns:
        Quantity to trade, position value, and risk amount.
    """
    try:
        if capital <= 0:
            raise ValueError("capital must be positive")
        if entry_price <= 0:
            raise ValueError("entry_price must be positive")
        if risk_pct <= 0 or risk_pct > 100:
            raise ValueError("risk_pct must be in (0, 100]")

        mgr = RiskManager()
        risk_frac = risk_pct / 100.0

        if method == "kelly":
            if win_rate is None or avg_win is None or avg_loss is None:
                raise ValueError("kelly method requires win_rate, avg_win, and avg_loss")
            pos = mgr.size_kelly(capital, win_rate, avg_win, avg_loss, entry_price, stop_price)
        else:
            pos = mgr.size_fixed(capital, risk_frac, entry_price, stop_price)

        return {"error": False, **pos.to_dict()}

    except ValueError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("calculate_position_size failed")
        return _error(exc)


async def calculate_risk_report(
    symbol: str,
    capital: float,
    entry_price: float,
    side: str = "long",
    risk_pct: float = 1.0,
    interval: str = "1h",
    market: str = "spot",
    atr_multiplier: float = 2.0,
    reward_ratio: float = 2.0,
    method: str = "fixed",
    win_rate: float | None = None,
    avg_win: float | None = None,
    avg_loss: float | None = None,
) -> dict:
    """
    Fetch live ATR for a symbol and produce a full risk report.

    Automatically calculates:
    - ATR-based stop-loss (entry ± atr_multiplier × ATR)
    - ATR-based take-profit (entry ± atr_multiplier × ATR × reward_ratio)
    - Position size so that hitting the stop risks exactly risk_pct% of capital
    - Maximum potential loss and gain in quote currency

    Args:
        symbol:         Trading pair e.g. 'btc_usdt'.
        capital:        Account capital in quote currency.
        entry_price:    Planned entry price.
        side:           'long' or 'short' (default 'long').
        risk_pct:       Capital percentage to risk per trade (default 1.0 = 1%).
        interval:       Candle interval for ATR calculation (default '1h').
        market:         'spot' or 'futures' (default 'spot').
        atr_multiplier: Stop distance in ATR multiples (default 2.0).
        reward_ratio:   Target distance as multiple of stop distance (default 2.0 → 1:2 R:R).
        method:         Sizing method 'fixed' or 'kelly'.
        win_rate:       Backtest win rate (required for kelly).
        avg_win:        Average winning trade (required for kelly).
        avg_loss:       Average losing trade as positive number (required for kelly).

    Returns:
        Full risk report: entry, stop, target, quantity, position value, max loss/gain.
    """
    try:
        if side not in ("long", "short"):
            raise ValueError("side must be 'long' or 'short'")
        if capital <= 0:
            raise ValueError("capital must be positive")
        if entry_price <= 0:
            raise ValueError("entry_price must be positive")
        if risk_pct <= 0 or risk_pct > 100:
            raise ValueError("risk_pct must be in (0, 100]")
        if method == "kelly" and (win_rate is None or avg_win is None or avg_loss is None):
            raise ValueError("kelly method requires win_rate, avg_win, and avg_loss")

        # Fetch recent candles to compute ATR
        engine = SignalEngine()
        _, df = await engine.run_with_df(
            symbol=symbol,
            interval=interval,
            strategy_name="rsi_reversal",
            market=market,
            lookback=100,
        )

        adx_df = compute_adx(df, period=14)
        atr_series = adx_df["atr"].dropna()
        if atr_series.empty:
            raise ValueError("Not enough data to compute ATR")
        current_atr = float(atr_series.iloc[-1])

        mgr = RiskManager(
            default_atr_multiplier=atr_multiplier,
            default_reward_ratio=reward_ratio,
        )
        report = mgr.full_report(
            symbol=symbol,
            interval=interval,
            market=market,
            capital=capital,
            risk_pct=risk_pct / 100.0,
            entry_price=entry_price,
            side=side,
            atr=current_atr,
            method=method,
            atr_multiplier=atr_multiplier,
            reward_ratio=reward_ratio,
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
        )

        return {"error": False, **report.to_dict()}

    except ValueError as exc:
        return _error(exc)
    except XTMCPError as exc:
        return _error(exc)
    except Exception as exc:
        logger.exception("calculate_risk_report failed")
        return _error(exc)
