"""
ICT Multi-Timeframe Analysis — Top 20 Bitunix Futures by Volume
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
    find_impulse_for_ote,
    find_ote_zone,
    find_tiered_tp,
    _klines_to_df,
)

API_KEY    = "7bee3f4756a0dbc89ae152f34c2175ac"
SECRET_KEY = "4e0a845778d49068297106a64cbcda61"

INTERVALS = ["1D", "4H", "1H", "15m", "5m", "3m"]
MAP = {"1D": "1d", "4H": "4h", "1H": "1h", "15m": "15m", "5m": "5m", "3m": "3m"}

# ── helpers ──────────────────────────────────────────────────────────────────

def _candle_confirm(raw_5m: list, direction: str):
    """Check last closed candle on 5m for ICT confirmation pattern."""
    df = _klines_to_df(raw_5m)
    if len(df) < 3:
        return False, ""
    # Use second-to-last so the candle is closed
    c = df.iloc[-2]
    p = df.iloc[-3]
    o, h, l, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
    body = abs(cl - o)
    upper_wick = h - max(o, cl)
    lower_wick = min(o, cl) - l
    po, pcl = float(p["open"]), float(p["close"])

    if direction == "bearish":
        # Bearish engulfing
        if cl < o and cl < po and o > pcl:
            return True, "Bearish Engulfing 5m"
        # Shooting star: upper wick >= 2x body, small lower wick
        if body > 0 and upper_wick >= 2 * body and lower_wick <= body:
            return True, "Shooting Star 5m"
        # Pinbar with upper wick >= 2x body
        if body > 0 and upper_wick >= 2 * body:
            return True, "Bearish Pinbar 5m"
    else:
        # Bullish engulfing
        if cl > o and cl > po and o < pcl:
            return True, "Bullish Engulfing 5m"
        # Hammer: lower wick >= 2x body, small upper wick
        if body > 0 and lower_wick >= 2 * body and upper_wick <= body:
            return True, "Hammer 5m"
        # Pinbar with lower wick >= 2x body
        if body > 0 and lower_wick >= 2 * body:
            return True, "Bullish Pinbar 5m"
    return False, ""


def _spread_pct(raw_5m: list) -> float:
    df = _klines_to_df(raw_5m)
    if len(df) < 1:
        return 9999.0
    last = df.iloc[-1]
    rng = float(last["high"]) - float(last["low"])
    cl = float(last["close"])
    return rng / cl if cl > 0 else 9999.0


def _key_levels_str(raw: list, direction: str) -> str:
    """Summarise key OBs and FVGs from a timeframe."""
    obs = detect_order_blocks(raw, "htf", max_obs=3, proximity_pct=0.10)
    fvgs = detect_fvg(raw, direction)[:3]
    parts = []
    for ob in obs:
        parts.append(f"OB({ob.ob_type}): {ob.ob_low:.6g}-{ob.ob_high:.6g}")
    for flo, fhi in fvgs:
        parts.append(f"FVG: {flo:.6g}-{fhi:.6g}")
    return ", ".join(parts) if parts else "none"


# ── main analysis ─────────────────────────────────────────────────────────────

async def analyse():
    async with AsyncBitunixClient(API_KEY, SECRET_KEY) as client:

        # 1. Top 20 by baseVol
        tickers = await client.get_all_tickers()
        if not tickers:
            print(json.dumps({"no_signal": True, "btc_bias": "neutral",
                              "reason": "could not fetch tickers"}))
            return

        def _vol(t):
            try:
                return float(t.get("baseVol") or t.get("volume") or 0)
            except Exception:
                return 0.0

        top20 = sorted(tickers, key=_vol, reverse=True)[:20]
        symbols = [t["symbol"] for t in top20]

        # 2. BTC structure
        btc_klines = {}
        for iv in ["1D", "4H", "1H"]:
            btc_klines[MAP[iv]] = await client.get_klines("BTCUSDT", iv, 200)

        btc_daily = market_structure(btc_klines.get("1d", []))
        btc_4h    = market_structure(btc_klines.get("4h", []))

        # 3. Fetch klines for all symbols concurrently
        async def fetch_all_klines(sym):
            d = {}
            tasks = {iv: client.get_klines(sym, iv, 200) for iv in INTERVALS}
            results = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for iv, result in zip(tasks.keys(), results):
                d[MAP[iv]] = result if not isinstance(result, Exception) else []
            return d

        klines_map = {}
        for sym in symbols:
            klines_map[sym] = await fetch_all_klines(sym)
            await asyncio.sleep(0.05)   # gentle rate-limiting

        # 4. Score each symbol
        candidates = []

        for sym in symbols:
            kl = klines_map[sym]
            raw_1d  = kl.get("1d", [])
            raw_4h  = kl.get("4h", [])
            raw_1h  = kl.get("1h", [])
            raw_15m = kl.get("15m", [])
            raw_5m  = kl.get("5m", [])

            if not raw_5m or len(raw_5m) < 10:
                continue

            df5 = _klines_to_df(raw_5m)
            current_price = float(df5["close"].iloc[-1])

            # 3b. Daily + 4H structure → direction bias
            daily_bias = market_structure(raw_1d)
            fourh_bias = market_structure(raw_4h)

            # Determine trade direction from bias
            if daily_bias == "bullish" and fourh_bias in ("bullish", "neutral"):
                direction = "bullish"
            elif daily_bias == "bearish" and fourh_bias in ("bearish", "neutral"):
                direction = "bearish"
            elif daily_bias in ("bullish", "bearish"):
                direction = daily_bias
            else:
                direction = fourh_bias if fourh_bias != "neutral" else None

            if direction is None:
                continue

            trade_dir = "LONG" if direction == "bullish" else "SHORT"
            score = 0
            checks = {}

            # Daily aligned with BTC (20 pts)
            daily_aligned = (daily_bias == btc_daily) or (btc_daily == "neutral")
            if daily_aligned and daily_bias != "neutral":
                score += 20
            checks["daily_aligned"] = daily_aligned and daily_bias != "neutral"

            # 4H OB (15 pts)
            obs_4h = detect_order_blocks(raw_4h, "4h", max_obs=4, proximity_pct=0.05)
            obs_1h = detect_order_blocks(raw_1h, "1h", max_obs=4, proximity_pct=0.05)
            valid_obs = [ob for ob in (obs_4h + obs_1h) if ob.ob_type == direction]
            fourh_ob = len(valid_obs) > 0
            if fourh_ob:
                score += 15
            checks["fourh_ob"] = fourh_ob

            # FVG 1H/15m (15 pts)
            fvgs_1h  = detect_fvg(raw_1h,  direction)
            fvgs_15m = detect_fvg(raw_15m, direction)
            fvg_present = len(fvgs_1h) > 0 or len(fvgs_15m) > 0
            if fvg_present:
                score += 15
            checks["fvg"] = fvg_present

            # Liquidity sweep 15m (15 pts)
            liq_ok, liq_detail = detect_liquidity_sweep(raw_15m, direction)
            if liq_ok:
                score += 15
            checks["liq_sweep"] = liq_ok

            # MSS/BOS 5m (15 pts)
            mss_ok, mss_detail = detect_mss_bos_ltf(raw_5m, raw_15m, direction)
            if mss_ok:
                score += 15
            checks["mss_bos"] = mss_ok

            # OTE zone 5m (10 pts)
            sw_lo, sw_hi = find_impulse_for_ote(raw_5m, direction, lookback=60)
            ote_lo, ote_hi = find_ote_zone(sw_lo, sw_hi, direction)
            ote_ok = ote_lo <= current_price <= ote_hi
            if ote_ok:
                score += 10
            checks["ote"] = ote_ok

            # Candle confirmation 5m (10 pts)
            candle_ok, candle_detail = _candle_confirm(raw_5m, direction)
            if candle_ok:
                score += 10
            checks["candle"] = candle_ok

            # Spread filter
            spread = _spread_pct(raw_5m)
            if spread > 0.0012:
                continue

            candidates.append({
                "symbol": sym,
                "score": score,
                "direction": trade_dir,
                "direction_ict": direction,
                "daily_bias": daily_bias,
                "fourh_bias": fourh_bias,
                "current_price": current_price,
                "spread_pct": round(spread * 100, 4),
                "checks": checks,
                "valid_obs": valid_obs,
                "fvgs_1h": fvgs_1h,
                "fvgs_15m": fvgs_15m,
                "liq_detail": liq_detail,
                "mss_detail": mss_detail,
                "candle_detail": candle_detail,
                "ote_ok": ote_ok,
                "ote_range": (round(ote_lo, 8), round(ote_hi, 8)),
                "kl": kl,
            })

        # 5. Select best
        if not candidates:
            print(json.dumps({
                "no_signal": True,
                "btc_daily": btc_daily,
                "btc_4h": btc_4h,
                "reason": "no symbols passed all filters (spread / data)"
            }))
            return

        candidates.sort(key=lambda x: x["score"], reverse=True)
        best = candidates[0]

        # Build concise candidate list
        all_cands = [{"symbol": c["symbol"], "score": c["score"],
                      "direction": c["direction"]} for c in candidates]

        # 6. Entry / SL / TP for best symbol
        sym         = best["symbol"]
        direction   = best["direction_ict"]
        entry       = best["current_price"]
        valid_obs   = best["valid_obs"]
        kl          = best["kl"]

        # SL from nearest OB wick
        ob_high = ob_low = None
        sl = None
        if valid_obs:
            ob = sorted(valid_obs, key=lambda x: abs(entry - x.mid))[ 0]
            ob_high = ob.wick_high
            ob_low  = ob.wick_low
            if direction == "bearish":
                sl_raw = ob.wick_high * 1.004
            else:
                sl_raw = ob.wick_low * 0.996
            sl_pct = abs(sl_raw - entry) / entry
            if sl_pct <= 0.015:
                sl = sl_raw
            else:
                # Clamp to 1.5%
                sl = entry * (1.015 if direction == "bearish" else 0.985)
        else:
            sl = entry * (1.015 if direction == "bearish" else 0.985)
            ob_high = ob_low = None

        sl_pct = abs(sl - entry) / entry

        # TP1 and TP2
        tp1, tp2, tp1_reason, tp2_reason = find_tiered_tp(
            kl.get("1h", []), kl.get("4h", []),
            entry, direction, sl,
            min_rr=2.0
        )
        risk = abs(entry - sl)
        tp1_rr = abs(tp1 - entry) / risk if risk > 0 else 0
        tp2_rr = abs(tp2 - entry) / risk if risk > 0 else 0

        # FVG range string
        fvg_range = "none"
        all_fvgs = best["fvgs_1h"] + best["fvgs_15m"]
        if all_fvgs:
            flo, fhi = all_fvgs[0]
            fvg_range = f"{flo:.6g}-{fhi:.6g}"

        # Leverage (conservative)
        leverage = 10

        # Account balance
        try:
            acct = await client.get_account("USDT")
            avail_usdt = float(acct.get("available") or acct.get("availableBalance") or 0)
        except Exception:
            avail_usdt = 0.0

        # Key levels Daily / 4H
        daily_key_levels = _key_levels_str(kl.get("1d", []), direction)
        fourh_key_levels  = _key_levels_str(kl.get("4h", []), direction)

        result = {
            "btc_daily": btc_daily,
            "btc_4h": btc_4h,
            "symbol": sym,
            "direction": best["direction"],
            "score": best["score"],
            "daily_bias": best["daily_bias"],
            "fourh_bias": best["fourh_bias"],
            "entry": round(entry, 8),
            "sl": round(sl, 8),
            "sl_pct": round(sl_pct * 100, 3),
            "tp1": round(tp1, 8),
            "tp1_rr": round(tp1_rr, 2),
            "tp2": round(tp2, 8),
            "tp2_rr": round(tp2_rr, 2),
            "leverage": leverage,
            "available_usdt": round(avail_usdt, 2),
            "ob_high": round(ob_high, 8) if ob_high else None,
            "ob_low": round(ob_low, 8) if ob_low else None,
            "fvg_range": fvg_range,
            "liq_sweep": best["liq_detail"] or "not detected",
            "mss_detail": best["mss_detail"] or "not detected",
            "ote_ok": best["ote_ok"],
            "candle_confirm": best["candle_detail"] or "none",
            "spread_pct": best["spread_pct"],
            "daily_key_levels": daily_key_levels or "none",
            "fourh_key_levels": fourh_key_levels or "none",
            "checks": best["checks"],
            "candidates_count": len(candidates),
            "all_candidates": all_cands,
        }

        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(analyse())
