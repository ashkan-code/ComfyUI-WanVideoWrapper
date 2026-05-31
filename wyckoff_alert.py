#!/usr/bin/env python3
"""
Wyckoff HTF Alert System
  1. Scan spring on Weekly / Daily / 4H
  2. Show ranked results with score
  3. Start monitor -- when price arrives, full ICT analysis fires

Run:  python wyckoff_alert.py
"""
import asyncio, os, ssl, sys, time, math
sys.path.insert(0, os.path.dirname(__file__))

import aiohttp

from bitunix_scanner.client import AsyncBitunixClient
from bitunix_scanner.ict import (
    btc_ict_bias, detect_wyckoff_spring,
    _parse_klines, _swing_lows, _swing_highs, _atr_vals,
    market_structure, detect_fvg,
)
from bitunix_scanner.signals import _fmt
from bitunix_scanner.alert_monitor import AlertMonitor, PriceAlert, _bar, _rank_label, TF_ALERT_ZONE

API_KEY    = os.getenv("BITUNIX_API_KEY",    "7bee3f4756a0dbc89ae152f34c2175ac")
SECRET_KEY = os.getenv("BITUNIX_SECRET_KEY", "4e0a845778d49068297106a64cbcda61")

TF_CFG = {
    "1w": dict(
        kline_limit = 52,
        equal_tol   = 0.008,
        min_pierce  = 0.005,
        wick_ratio  = 2.0,
        max_age     = 3,
        min_gap     = 4,
        base_score  = 40,
    ),
    "1d": dict(
        kline_limit = 120,
        equal_tol   = 0.005,
        min_pierce  = 0.003,
        wick_ratio  = 2.2,
        max_age     = 5,
        min_gap     = 5,
        base_score  = 30,
    ),
    "4h": dict(
        kline_limit = 200,
        equal_tol   = 0.003,
        min_pierce  = 0.002,
        wick_ratio  = 2.5,
        max_age     = 8,
        min_gap     = 5,
        base_score  = 20,
    ),
}

SCAN_TFS   = ["1w", "1d", "4h"]
BATCH_SIZE = 15
SHOW_TOP   = 8
MIN_SCORE  = 35


def _score_htf(detail: dict, tf: str, raw4h: list, ict_dir: str,
               base_score: int) -> float:
    score = float(base_score)

    c = detail.get("candle", {})
    if c:
        body = abs(float(c.get("close", 0)) - float(c.get("open", 0)))
        if ict_dir == "bullish":
            wick = min(float(c.get("open", 0)), float(c.get("close", 0))) - float(c.get("low", 0))
        else:
            wick = float(c.get("high", 0)) - max(float(c.get("open", 0)), float(c.get("close", 0)))
        ratio = wick / body if body > 0 else 0
        score += min(ratio / 5.0, 1.0) * 20

    pierce = detail.get("pierce", 0)
    score += min(pierce / 2.0, 1.0) * 15

    gap = detail.get("gap", 0)
    score += min(gap / 20.0, 1.0) * 10

    age = detail.get("age", 99)
    score += max(0, 1.0 - age / 5.0) * 10

    if raw4h:
        ms4 = market_structure(raw4h, lookback=60)
        if ms4 == ict_dir:
            score += 5

    return min(score, 100.0)


async def _scan_one(client: AsyncBitunixClient,
                    symbol: str, price: float,
                    btc_bias: str, btc_detail: str,
                    direction: str, ict_dir: str):
    raw4h = await client.get_klines(symbol, "4h", 200)
    best  = None

    for tf in SCAN_TFS:
        cfg = TF_CFG[tf]
        raw = await client.get_klines(symbol, tf, cfg["kline_limit"])
        if not raw or len(raw) < 20:
            continue

        found, detail = detect_wyckoff_spring(
            raw, ict_dir,
            lookback    = cfg["kline_limit"],
            equal_tol   = cfg["equal_tol"],
            min_pierce  = cfg["min_pierce"],
            wick_ratio  = cfg["wick_ratio"],
            max_age     = cfg["max_age"],
            min_gap     = cfg["min_gap"],
        )
        if not found:
            continue

        score = _score_htf(detail, tf, raw4h, ict_dir, cfg["base_score"])

        c = detail.get("candle", {})
        if c:
            body = abs(float(c.get("close", 0)) - float(c.get("open", 0)))
            if ict_dir == "bullish":
                wk = min(float(c.get("open", 0)), float(c.get("close", 0))) - float(c.get("low", 0))
            else:
                wk = float(c.get("high", 0)) - max(float(c.get("open", 0)), float(c.get("close", 0)))
            wr = wk / body if body > 0 else 0.0
        else:
            wr = 0.0

        alert = PriceAlert(
            symbol     = symbol,
            direction  = direction,
            tf         = tf,
            level      = detail["level"],
            swept      = detail["swept"],
            pierce_pct = detail.get("pierce", 0),
            wick_ratio = wr,
            score      = score,
            btc_bias   = btc_bias,
        )

        if best is None or score > best.score:
            best = alert

    return best


def _fmt_alert(rank: int, a: PriceAlert) -> str:
    icon  = "L" if a.direction == "LONG" else "S"
    kind  = "Spring" if a.direction == "LONG" else "Upthrust"
    rl    = _rank_label(a.score)
    z     = TF_ALERT_ZONE.get(a.tf, 0.015) * 100
    b_ico = "bull" if a.btc_bias == "bullish" else ("bear" if a.btc_bias == "bearish" else "neut")
    return (
        f"+{'─'*58}+\n"
        f"|  #{rank:<2}  {icon} {kind}  {a.symbol:<14} [{a.tf.upper()}]      |\n"
        f"|  score: {a.score:>5.1f}/100  {_bar(a.score)}  {rl:<16}|\n"
        f"+{'─'*58}+\n"
        f"|  level   : {_fmt(a.level):<16}  pierce: {a.pierce_pct:.2f}%           |\n"
        f"|  swept   : {_fmt(a.swept):<16}  wick: {a.wick_ratio:.1f}x              |\n"
        f"|  BTC     : {b_ico:<10}  alert zone: +-{z:.1f}%              |\n"
        f"|  Waiting for price -- sniper signal on trigger          |\n"
        f"+{'─'*58}+"
    )


async def main():
    print("""
+====================================================+
|   Wyckoff HTF Alert  --  Weekly / Daily / 4H       |
|   HTF spring scan + price alert + ICT analysis     |
+====================================================+
""")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode    = ssl.CERT_NONE
    conn = aiohttp.TCPConnector(ssl=ssl_ctx)

    async with aiohttp.ClientSession(connector=conn) as session:
        client  = AsyncBitunixClient(API_KEY, SECRET_KEY, session)
        monitor = AlertMonitor(client)

        print("  BTC analysis ...", flush=True)
        btc_tf = {tf: await client.get_klines("BTCUSDT", tf, 100)
                  for tf in ("4h", "1h", "1d")}
        btc_bias, btc_detail = btc_ict_bias(btc_tf)
        b_tag = "BULL" if btc_bias == "bullish" else ("BEAR" if btc_bias == "bearish" else "NEUT")
        print(f"  BTC -> {b_tag}")
        print(f"     {btc_detail}\n")

        if btc_bias == "neutral":
            dirs = [("LONG", "bullish"), ("SHORT", "bearish")]
            print("  BTC neutral -- scanning both directions\n")
        else:
            direction = "LONG" if btc_bias == "bullish" else "SHORT"
            dirs      = [(direction, "bullish" if direction == "LONG" else "bearish")]

        tickers   = await client.get_all_tickers()
        price_map = {t["symbol"]: float(t["lastPrice"])
                     for t in tickers
                     if t.get("lastPrice") and float(t.get("lastPrice", 0)) > 0}
        symbols   = list(price_map.keys())
        print(f"  Scanning {len(symbols)} symbols on {SCAN_TFS} ...\n", flush=True)

        t0    = time.time()
        found = []

        for direction, ict_dir in dirs:
            for i in range(0, len(symbols), BATCH_SIZE):
                batch   = symbols[i: i + BATCH_SIZE]
                tasks   = [_scan_one(client, sym, price_map[sym],
                                     btc_bias, btc_detail, direction, ict_dir)
                           for sym in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for r in results:
                    if isinstance(r, PriceAlert):
                        found.append(r)
                done = i + len(batch)
                print(f"  {done}/{len(symbols)}  found: {len(found)}"
                      f"  [{time.time()-t0:.0f}s]", flush=True)

        elapsed = time.time() - t0
        print(f"\n{'='*56}")
        print(f"  Scan done -- {len(found)} HTF springs from {len(symbols)} symbols  [{elapsed:.0f}s]")
        print(f"{'='*56}\n")

        if not found:
            print("  No HTF spring found.\n")
            return

        found.sort(key=lambda a: a.score, reverse=True)

        print(f"\n{'='*68}")
        print(f"  SNIPER WATCHLIST -- {len(found)} HTF springs (ranked by score)")
        print(f"{'='*68}")
        print(f"  {'#':<4} {'symbol':<16} {'dir':<6} {'tf':<5} {'score':<12} {'level':<14} {'rank'}")
        print("  " + "-" * 62)
        for i, a in enumerate(found, 1):
            rl = _rank_label(a.score)
            print(f"  #{i:<3} {a.symbol:<16} {a.direction:<6} {a.tf:<5}"
                  f" {a.score:>5.1f}/100  {_fmt(a.level):<14} {rl}")

        print(f"\n{'='*68}")
        print(f"  Preview top {min(SHOW_TOP, len(found))}:")
        print(f"{'='*68}\n")

        top = found[:SHOW_TOP]
        for rank, a in enumerate(top, 1):
            print(_fmt_alert(rank, a))

        alert_candidates = [a for a in found if a.score >= MIN_SCORE]
        if not alert_candidates:
            alert_candidates = found[:5]

        print(f"\n{'='*68}")
        print(f"  Registering {len(alert_candidates)} levels for monitoring -- sniper signal on trigger:")
        print(f"{'='*68}")
        for a in alert_candidates:
            monitor.add(a)

        from bitunix_scanner.alert_monitor import POLL_SEC as _poll
        print(f"\n  Monitoring -- checking every {_poll}s")
        print(f"  Ctrl+C to exit\n")

        await monitor.run()


if __name__ == "__main__":
    asyncio.run(main())
