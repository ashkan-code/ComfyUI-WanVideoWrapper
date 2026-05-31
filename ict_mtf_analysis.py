"""
ICT Multi-Timeframe Analysis - Top 20 Crypto Futures by Volume on Bitunix
"""

import asyncio
import json
import sys
import os

sys.path.insert(0, "/home/user/ComfyUI-WanVideoWrapper")

from bitunix_scanner.client import AsyncBitunixClient
from bitunix_scanner.ict import (
    market_structure,
    detect_order_blocks,
    detect_fvg,
    detect_liquidity_sweep,
    detect_mss_bos_ltf,
    find_ote_zone,
    find_impulse_for_ote,
    find_tiered_tp,
    _klines_to_df,
)

API_KEY = "68f0a1765f124bacb847afa8db78e480"
SECRET_KEY = "159808597389a1cd1fc429f9f469209b"

# Bitunix valid intervals: 1d, 4H/4h, 1h, 15m/15M, 5m/5M, 3m/3M
TIMEFRAMES = ["1d", "4H", "1h", "15m", "5m", "3m"]
TF_MAP = {"1d": "1d", "4H": "4h", "1h": "1h", "15m": "15m", "5m": "5m", "3m": "3m"}

MAX_SPREAD = 0.003   # 0.3% of price range (5m candle range/close) — filters illiquid coins
MAX_SL_PCT = 0.025   # 2.5% max SL from entry (crypto futures adjusted)
SL_BUFFER_PCT = 0.004  # 0.4% buffer above/below OB wick


def candle_confirmation(raw_5m: list, direction: str):
    """
    Check last closed candle on 5m for ICT candlestick confirmation.
    Returns (confirmed: bool, description: str)
    """
    df = _klines_to_df(raw_5m)
    if len(df) < 3:
        return False, ""

    # Use second-to-last candle as last closed
    c = df.iloc[-2]
    prev = df.iloc[-3]

    o, h, l, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
    body = abs(cl - o)
    upper_wick = h - max(o, cl)
    lower_wick = min(o, cl) - l
    candle_range = h - l

    if body == 0:
        body = candle_range * 0.01  # avoid div/0

    if direction == "bearish":
        # Bearish engulfing
        if (cl < o and  # bearish candle
                o > float(prev["close"]) and cl < float(prev["open"])):
            return True, "Bearish Engulfing 5m"
        # Shooting star: small body near low, upper wick >= 2x body
        if upper_wick >= 2 * body and lower_wick <= body * 0.5:
            return True, "Shooting Star 5m"
        # Pinbar with upper wick >= 2x body
        if upper_wick >= 2 * body:
            return True, "Bearish Pinbar 5m"

    elif direction == "bullish":
        # Bullish engulfing
        if (cl > o and  # bullish candle
                o < float(prev["close"]) and cl > float(prev["open"])):
            return True, "Bullish Engulfing 5m"
        # Hammer: small body near high, lower wick >= 2x body
        if lower_wick >= 2 * body and upper_wick <= body * 0.5:
            return True, "Hammer 5m"
        # Pinbar with lower wick >= 2x body
        if lower_wick >= 2 * body:
            return True, "Bullish Pinbar 5m"

    return False, ""


def check_ote(raw_5m: list, direction: str, entry: float) -> bool:
    """Check if entry price is within OTE zone (61.8-79% retracement)."""
    try:
        swing_low, swing_high = find_impulse_for_ote(raw_5m, direction, lookback=50)
        ote_low, ote_high = find_ote_zone(swing_low, swing_high, direction)
        return ote_low <= entry <= ote_high
    except Exception:
        return False


def get_spread_pct(raw_5m: list) -> float:
    """Calculate approximate spread as (high - low) / close of last candle."""
    df = _klines_to_df(raw_5m)
    if df.empty:
        return 999.0
    last = df.iloc[-1]
    cl = float(last["close"])
    if cl == 0:
        return 999.0
    return (float(last["high"]) - float(last["low"])) / cl


def get_key_levels(raw_daily: list, raw_4h: list) -> tuple:
    """Extract key support/resistance levels from Daily and 4H."""
    daily_levels = []
    fourh_levels = []

    # Daily OBs
    daily_obs = detect_order_blocks(raw_daily, "1d", max_obs=4, proximity_pct=0.08)
    for ob in daily_obs[:2]:
        daily_levels.append(f"OB({ob.ob_type[:1].upper()}): {ob.ob_low:.6g}-{ob.ob_high:.6g}")

    # Daily FVGs
    for direction in ("bullish", "bearish"):
        fvgs = detect_fvg(raw_daily, direction)[:2]
        for flo, fhi in fvgs:
            daily_levels.append(f"FVG: {flo:.6g}-{fhi:.6g}")

    # 4H OBs
    fourh_obs = detect_order_blocks(raw_4h, "4h", max_obs=4, proximity_pct=0.06)
    for ob in fourh_obs[:2]:
        fourh_levels.append(f"OB({ob.ob_type[:1].upper()}): {ob.ob_low:.6g}-{ob.ob_high:.6g}")

    # 4H liquidity: swing highs/lows
    df4h = _klines_to_df(raw_4h)
    if not df4h.empty:
        from bitunix_scanner.ict import _swing_highs, _swing_lows
        sh = _swing_highs(df4h.tail(50).reset_index(drop=True), n=3)
        sl = _swing_lows(df4h.tail(50).reset_index(drop=True), n=3)
        df4h_tail = df4h.tail(50).reset_index(drop=True)
        if sh:
            sh_price = float(df4h_tail["high"].iloc[sh[-1]])
            fourh_levels.append(f"Liq pool(H): {sh_price:.6g}")
        if sl:
            sl_price = float(df4h_tail["low"].iloc[sl[-1]])
            fourh_levels.append(f"Liq pool(L): {sl_price:.6g}")

    daily_str = ", ".join(daily_levels) if daily_levels else "N/A"
    fourh_str = ", ".join(fourh_levels) if fourh_levels else "N/A"
    return daily_str, fourh_str


async def analyze_symbol(client: AsyncBitunixClient, symbol: str) -> dict:
    """Full ICT MTF analysis for a single symbol."""
    result = {"symbol": symbol, "score": 0, "direction": None, "valid": False}

    # Fetch all timeframes concurrently
    tasks = {tf: client.get_klines(symbol, tf, limit=200) for tf in TIMEFRAMES}
    klines = {}
    for tf, coro in tasks.items():
        try:
            klines[tf] = await coro
        except Exception:
            klines[tf] = []

    # --- Structure Analysis ---
    # TIMEFRAMES = ["1d", "4H", "1h", "15m", "5m", "3m"]
    daily_ms = market_structure(klines.get("1d", []))
    fourh_ms = market_structure(klines.get("4H", []))

    # Determine direction from Daily bias (primary)
    if daily_ms == "bearish":
        direction = "bearish"
    elif daily_ms == "bullish":
        direction = "bullish"
    elif fourh_ms == "bearish":
        direction = "bearish"
    elif fourh_ms == "bullish":
        direction = "bullish"
    else:
        result["direction"] = "neutral"
        return result

    ob_dir = direction  # "bullish" | "bearish"

    # --- Scoring ---
    score = 0
    checks = {
        "daily_aligned": False,
        "fourh_ob": False,
        "fvg": False,
        "liq_sweep": False,
        "mss_bos": False,
        "ote": False,
        "candle": False,
    }

    # 1. Daily structure aligned (20 pts)
    if daily_ms in ("bullish", "bearish"):
        score += 20
        checks["daily_aligned"] = True

    # 2. 4H OB present in bias direction (15 pts)
    fourh_obs = detect_order_blocks(klines.get("4H", []), "4h", max_obs=6, proximity_pct=0.05)
    valid_4h_obs = [ob for ob in fourh_obs if ob.ob_type == ob_dir]

    # Also check 1H OBs
    oneh_obs = detect_order_blocks(klines.get("1h", []), "1h", max_obs=6, proximity_pct=0.04)
    valid_1h_obs = [ob for ob in oneh_obs if ob.ob_type == ob_dir]

    best_ob = None
    if valid_4h_obs:
        score += 15
        checks["fourh_ob"] = True
        best_ob = valid_4h_obs[0]
    elif valid_1h_obs:
        score += 8  # partial credit for 1H OB
        checks["fourh_ob"] = True
        best_ob = valid_1h_obs[0]

    # 3. FVG on 1H/15m (15 pts)
    fvg_1h = detect_fvg(klines.get("1h", []), ob_dir)
    fvg_15m = detect_fvg(klines.get("15m", []), ob_dir)
    best_fvg = None
    if fvg_1h or fvg_15m:
        score += 15
        checks["fvg"] = True
        best_fvg = fvg_1h[0] if fvg_1h else fvg_15m[0]

    # 4. Liquidity sweep on 15m (15 pts)
    sweep_ok, sweep_desc = detect_liquidity_sweep(klines.get("15m", []), ob_dir)
    if sweep_ok:
        score += 15
        checks["liq_sweep"] = True

    # 5. MSS/BOS on 5m (15 pts)
    mss_ok, mss_desc = detect_mss_bos_ltf(klines.get("5m", []), klines.get("15m", []), ob_dir)

    if mss_ok:
        score += 15
        checks["mss_bos"] = True

    # --- Entry price (current price) ---
    df5m = _klines_to_df(klines.get("5m", []))
    if df5m.empty:
        return result
    entry = float(df5m.iloc[-1]["close"])

    # 6. OTE zone on 5m (10 pts)
    ote_ok = check_ote(klines.get("5m", []), ob_dir, entry)
    if ote_ok:
        score += 10
        checks["ote"] = True

    # 7. Candle confirmation on 5m (10 pts)
    candle_ok, candle_desc = candle_confirmation(klines.get("5m", []), ob_dir)
    if candle_ok:
        score += 10
        checks["candle"] = True

    # --- Spread filter ---
    spread_pct = get_spread_pct(klines.get("5m", []))
    if spread_pct > MAX_SPREAD:
        result["score"] = score
        result["direction"] = direction
        result["spread_pct"] = round(spread_pct * 100, 4)
        result["skip_reason"] = f"spread too wide: {spread_pct:.4f}"
        return result

    # --- Stop Loss calculation ---
    sl = None
    if best_ob:
        if ob_dir == "bearish":
            # SHORT: SL above OB wick high + buffer
            sl = best_ob.wick_high * (1 + SL_BUFFER_PCT)
        else:
            # LONG: SL below OB wick low - buffer
            sl = best_ob.wick_low * (1 - SL_BUFFER_PCT)
    else:
        # Fallback: use ATR or fixed % SL
        if ob_dir == "bearish":
            sl = entry * 1.012
        else:
            sl = entry * 0.988

    sl_pct = abs(sl - entry) / entry
    if sl_pct > MAX_SL_PCT:
        result["score"] = score
        result["direction"] = direction
        result["sl_pct"] = round(sl_pct * 100, 4)
        result["skip_reason"] = f"SL too wide: {sl_pct*100:.2f}%"
        return result

    # --- TP calculation ---
    tp1, tp2, tp1_reason, tp2_reason = find_tiered_tp(
        klines.get("1h", []),
        klines.get("4H", []),
        entry,
        ob_dir,
        sl,
        min_rr=2.0,
    )

    risk = abs(entry - sl)
    tp1_rr = abs(tp1 - entry) / risk if risk > 0 else 0
    tp2_rr = abs(tp2 - entry) / risk if risk > 0 else 0

    # --- Build result ---
    result.update({
        "score": score,
        "direction": "LONG" if ob_dir == "bullish" else "SHORT",
        "daily_bias": daily_ms,
        "fourh_bias": fourh_ms,
        "entry": round(entry, 8),
        "sl": round(sl, 8),
        "sl_pct": round(sl_pct * 100, 4),
        "tp1": round(tp1, 8),
        "tp1_rr": round(tp1_rr, 2),
        "tp2": round(tp2, 8),
        "tp2_rr": round(tp2_rr, 2),
        "ob_high": round(best_ob.wick_high, 8) if best_ob else None,
        "ob_low": round(best_ob.wick_low, 8) if best_ob else None,
        "fvg_range": f"{best_fvg[0]:.8g}-{best_fvg[1]:.8g}" if best_fvg else "N/A",
        "liq_sweep": sweep_desc if sweep_ok else "None",
        "mss_detail": mss_desc if mss_ok else "None",
        "ote_ok": ote_ok,
        "candle_confirm": candle_desc if candle_ok else "None",
        "spread_pct": round(spread_pct * 100, 4),
        "checks": checks,
        "valid": True,
        "_klines": klines,  # keep for post-processing, strip later
    })

    return result


async def main():
    async with AsyncBitunixClient(API_KEY, SECRET_KEY) as client:
        # 1. Fetch top 20 symbols by baseVol
        tickers = await client.get_all_tickers()
        if not tickers:
            print(json.dumps({"no_signal": True, "btc_bias": "neutral", "reason": "Failed to fetch tickers"}))
            return

        # Sort by baseVol descending
        def parse_vol(t):
            try:
                return float(t.get("baseVol", 0) or 0)
            except Exception:
                return 0.0

        tickers_sorted = sorted(tickers, key=parse_vol, reverse=True)
        top20 = [t["symbol"] for t in tickers_sorted[:20] if t.get("symbol")]

        # 2. BTC klines for bias (use correct Bitunix intervals)
        btc_1d = await client.get_klines("BTCUSDT", "1d", limit=200)
        btc_4h = await client.get_klines("BTCUSDT", "4H", limit=200)
        btc_1h = await client.get_klines("BTCUSDT", "1h", limit=200)

        btc_daily_ms = market_structure(btc_1d)
        btc_4h_ms = market_structure(btc_4h)

        # 3. Analyze all top 20 symbols
        tasks = [analyze_symbol(client, sym) for sym in top20]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        # Filter valid candidates: must have score > 0, direction, and a complete setup (entry not None)
        candidates = [
            r for r in results
            if isinstance(r, dict)
            and r.get("score", 0) > 0
            and r.get("direction") not in (None, "neutral")
            and r.get("entry") is not None  # only fully computed setups
        ]

        # Sort by score descending
        candidates.sort(key=lambda x: x.get("score", 0), reverse=True)

        if not candidates:
            # Build partial candidates list for debug
            partial = [
                {"symbol": r.get("symbol"), "score": r.get("score"), "direction": r.get("direction"),
                 "skip": r.get("skip_reason", "no_entry")}
                for r in results
                if isinstance(r, dict) and r.get("score", 0) > 0
            ]
            partial.sort(key=lambda x: x.get("score", 0), reverse=True)
            print(json.dumps({
                "no_signal": True,
                "btc_bias": btc_daily_ms,
                "btc_daily": btc_daily_ms,
                "btc_4h": btc_4h_ms,
                "reason": "No valid ICT setups met all filters (spread/SL/entry) in top 20 symbols",
                "partial_candidates": partial[:10]
            }))
            return

        # 4. Get best symbol
        best = candidates[0]

        # 5. Get account info
        try:
            account = await client.get_account("USDT")
            available_usdt = float(account.get("availableBalance", 0) or account.get("available", 0) or 0)
        except Exception:
            available_usdt = 0.0

        # 6. Key levels for best symbol
        klines_stored = best.pop("_klines", {})
        daily_key_levels, fourh_key_levels = get_key_levels(
            klines_stored.get("1d", []),
            klines_stored.get("4H", [])
        )

        # Strip _klines from all candidates
        all_candidates_list = []
        for c in candidates:
            c.pop("_klines", None)
            all_candidates_list.append({
                "symbol": c.get("symbol"),
                "score": c.get("score"),
                "direction": c.get("direction"),
            })

        # Leverage calculation (conservative, based on SL %)
        sl_pct = best.get("sl_pct", 1.5)
        leverage = max(3, min(20, int(1.0 / (sl_pct / 100) * 0.5))) if sl_pct > 0 else 10

        output = {
            "btc_daily": btc_daily_ms,
            "btc_4h": btc_4h_ms,
            "symbol": best.get("symbol"),
            "direction": best.get("direction"),
            "score": best.get("score"),
            "daily_bias": best.get("daily_bias"),
            "fourh_bias": best.get("fourh_bias"),
            "entry": best.get("entry"),
            "sl": best.get("sl"),
            "sl_pct": best.get("sl_pct"),
            "tp1": best.get("tp1"),
            "tp1_rr": best.get("tp1_rr"),
            "tp2": best.get("tp2"),
            "tp2_rr": best.get("tp2_rr"),
            "leverage": leverage,
            "available_usdt": round(available_usdt, 2),
            "ob_high": best.get("ob_high"),
            "ob_low": best.get("ob_low"),
            "fvg_range": best.get("fvg_range"),
            "liq_sweep": best.get("liq_sweep"),
            "mss_detail": best.get("mss_detail"),
            "ote_ok": best.get("ote_ok"),
            "candle_confirm": best.get("candle_confirm"),
            "spread_pct": best.get("spread_pct"),
            "daily_key_levels": daily_key_levels,
            "fourh_key_levels": fourh_key_levels,
            "checks": best.get("checks"),
            "candidates_count": len(candidates),
            "all_candidates": all_candidates_list,
        }

        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
