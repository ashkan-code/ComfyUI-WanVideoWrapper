#!/usr/bin/env python3
"""
Pairs Arb Signal Tracker -- Bitunix Futures
Entry signal when z-score diverges, Exit signal when z returns OR timeout.
NO orders placed. Display only.

Usage:
  python arbitrage.py           # single scan
  python arbitrage.py --live    # full entry+exit monitor
"""
import argparse, asyncio, os, ssl, sys, time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
sys.path.insert(0, os.path.dirname(__file__))

import aiohttp

from bitunix_scanner.client    import AsyncBitunixClient
from bitunix_scanner.arbitrage import (
    scan, ArbOpp, _bar, _rank,
    ROUND_TRIP_FEES, TOP_SYMBOLS,
    _corr, _ratio_stats, _closes, _half_life,
)
from bitunix_scanner.signals import _fmt

API_KEY    = os.getenv("BITUNIX_API_KEY",    "68f0a1765f124bacb847afa8db78e480")
SECRET_KEY = os.getenv("BITUNIX_SECRET_KEY", "159808597389a1cd1fc429f9f469209b")

SCAN_INTERVAL  = 30      # seconds between scans
MONITOR_MINS   = 30      # minutes between exit checks
TIMEOUT_HOURS  = 6       # hours -- force EXIT after this
Z_EXIT         = 0.5     # exit when z < this
SHOW_TOP       = 3       # show top N sniper signals only
W = 46


def _line(c="-"): return c * W


# ── Active signal tracker ──────────────────────────────────────────────────────

@dataclass
class OpenSignal:
    sym_a:       str
    sym_b:       str
    direction_a: str   # LONG | SHORT
    direction_b: str
    entry_price_a: float
    entry_price_b: float
    entry_z:     float
    entry_net:   float
    score:       float
    opened_at:   float = field(default_factory=time.time)

    @property
    def age_hours(self) -> float:
        return (time.time() - self.opened_at) / 3600


_open_signals: List[OpenSignal] = []


# ── Display helpers ────────────────────────────────────────────────────────────

def _fmt_entry(rank: int, o: ArbOpp) -> str:
    a_dir = "LONG " if o.direction_a == "LONG" else "SHORT"
    b_dir = "LONG " if o.direction_b == "LONG" else "SHORT"
    hl_tag = (f"{o.half_life:.0f}h" if o.half_life < 999 else "n/a")
    lines = [
        "",
        _line("="),
        f" SNIPER #{rank}  {_rank(o.score)}",
        f" score: {o.score:.1f}/100  {_bar(o.score)}",
        _line("-"),
        f" {a_dir} {o.sym_a}",
        f"        @ {_fmt(o.price_a)}",
        f" {b_dir} {o.sym_b}",
        f"        @ {_fmt(o.price_b)}",
        _line("-"),
        f" z        : {o.z_score:+.2f}",
        f" corr     : {o.corr:.2f} / {o.corr_recent:.2f}",
        f" half-life: {hl_tag}  (revert speed)",
        f" net est  : {o.net*100:>+.3f}%",
        f" exit     : z<{Z_EXIT} OR {TIMEOUT_HOURS}h",
        _line("="),
        "",
    ]
    return "\n".join(lines)


def _fmt_exit(sig: OpenSignal, reason: str,
              cur_z: float, cur_pa: float, cur_pb: float) -> str:
    age_h = sig.age_hours
    pnl_a = (cur_pa - sig.entry_price_a) / sig.entry_price_a * 100
    pnl_b = (cur_pb - sig.entry_price_b) / sig.entry_price_b * 100
    if sig.direction_a == "LONG":
        pnl_a_net = pnl_a
        pnl_b_net = -pnl_b
    else:
        pnl_a_net = -pnl_a
        pnl_b_net = pnl_b
    total_pnl = (pnl_a_net + pnl_b_net) / 2

    lines = [
        "",
        _line("="),
        f" EXIT SIGNAL  -- {reason}",
        _line("-"),
        f" {sig.sym_a} ({sig.direction_a})",
        f"   entry={_fmt(sig.entry_price_a)}  now={_fmt(cur_pa)}",
        f"   pnl  = {pnl_a_net:>+.3f}%",
        f" {sig.sym_b} ({sig.direction_b})",
        f"   entry={_fmt(sig.entry_price_b)}  now={_fmt(cur_pb)}",
        f"   pnl  = {pnl_b_net:>+.3f}%",
        _line("-"),
        f" combined pnl : {total_pnl:>+.3f}%",
        f" z at entry   : {sig.entry_z:>+.2f}",
        f" z now        : {cur_z:>+.2f}",
        f" time open    : {age_h:.1f}h",
        _line("="),
        "",
    ]
    return "\n".join(lines)


# ── Single scan display ────────────────────────────────────────────────────────

def _summary(opps: List[ArbOpp], elapsed: float):
    print(f"\n{_line('=')}")
    print(f" {len(opps)} signal(s)  [{elapsed:.1f}s]")
    if not opps:
        print(" No opportunity -- market aligned")
        print(_line("="))
        return
    print(_line("="))
    print(f" {'#':<3} {'A':<14} {'B':<14} {'net':<9} {'rank'}")
    print(f" {_line('-')}")
    for i, o in enumerate(opps[:SHOW_TOP], 1):
        print(f" #{i:<2} {o.sym_a:<14} {o.sym_b:<14} "
              f"{o.net*100:>+.3f}%  {_rank(o.score)}")


# ── Monitor open signals ───────────────────────────────────────────────────────

async def _check_exits(client: AsyncBitunixClient):
    """Check all open signals -- print EXIT if conditions met."""
    if not _open_signals:
        return

    # fetch current prices + klines for z recalculation
    tickers = await client.get_all_tickers()
    price_map = {t["symbol"]: float(t["lastPrice"])
                 for t in tickers if t.get("lastPrice")}

    to_remove = []
    for sig in _open_signals:
        cur_pa = price_map.get(sig.sym_a, 0)
        cur_pb = price_map.get(sig.sym_b, 0)
        if not cur_pa or not cur_pb:
            continue

        # recalculate z-score
        try:
            kl_a = await client.get_klines(sig.sym_a, "1h", 100)
            kl_b = await client.get_klines(sig.sym_b, "1h", 100)
            ca, cb = _closes(kl_a), _closes(kl_b)
            cur_r, mu, sd = _ratio_stats(ca, cb)
            cur_z = (cur_r - mu) / sd if sd > 0 else 0
        except Exception:
            cur_z = sig.entry_z   # fallback

        # exit conditions
        timeout = sig.age_hours >= TIMEOUT_HOURS
        z_back  = abs(cur_z) < Z_EXIT

        if z_back or timeout:
            reason = "z returned to mean" if z_back else f"timeout {TIMEOUT_HOURS}h"
            print(_fmt_exit(sig, reason, cur_z, cur_pa, cur_pb))
            to_remove.append(sig)

    for sig in to_remove:
        _open_signals.remove(sig)


# ── Live z-score updater ───────────────────────────────────────────────────────

async def _z_now_all(client: AsyncBitunixClient) -> dict:
    """Compute current z for each open signal concurrently."""
    if not _open_signals:
        return {}

    async def _one(sig: OpenSignal):
        try:
            kl_a = await client.get_klines(sig.sym_a, "1h", 100)
            kl_b = await client.get_klines(sig.sym_b, "1h", 100)
            ca, cb = _closes(kl_a), _closes(kl_b)
            cur_r, mu, sd = _ratio_stats(ca, cb)
            return id(sig), (cur_r - mu) / sd if sd > 0 else sig.entry_z
        except Exception:
            return id(sig), sig.entry_z

    results = await asyncio.gather(*[_one(s) for s in _open_signals])
    return dict(results)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live",     action="store_true",
                        help="entry+exit monitor mode")
    parser.add_argument("--interval", type=int, default=SCAN_INTERVAL)
    args = parser.parse_args()

    print(f"""
{_line('=')}
 Pairs Arb Signal Tracker -- Bitunix
 ENTRY : corr>=0.60 | z>=1.5 | net>=0.15%
 EXIT  : z<{Z_EXIT} OR after {TIMEOUT_HOURS}h
 NO orders placed -- display only
{_line('=')}
""")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode    = ssl.CERT_NONE
    conn = aiohttp.TCPConnector(ssl=ssl_ctx)

    async with aiohttp.ClientSession(connector=conn) as session:
        client = AsyncBitunixClient(API_KEY, SECRET_KEY, session)

        async def _one_scan():
            t0      = time.time()
            print(f" [{time.strftime('%H:%M:%S')}] Scanning {TOP_SYMBOLS} symbols ...",
                  flush=True)
            opps    = await scan(client)
            elapsed = time.time() - t0
            _summary(opps, elapsed)

            new_entries = 0
            for i, o in enumerate(opps[:SHOW_TOP], 1):
                # skip if already tracking this pair
                already = any(
                    (s.sym_a == o.sym_a and s.sym_b == o.sym_b) or
                    (s.sym_a == o.sym_b and s.sym_b == o.sym_a)
                    for s in _open_signals
                )
                if already:
                    continue

                print(_fmt_entry(i, o))

                if args.live:
                    _open_signals.append(OpenSignal(
                        sym_a=o.sym_a, sym_b=o.sym_b,
                        direction_a=o.direction_a, direction_b=o.direction_b,
                        entry_price_a=o.price_a, entry_price_b=o.price_b,
                        entry_z=o.z_score, entry_net=o.net,
                        score=o.score,
                    ))
                    new_entries += 1

            if args.live and new_entries:
                print(f" Tracking {len(_open_signals)} open signal(s)")
            return opps

        # single scan mode
        if not args.live:
            await _one_scan()
            return

        # live mode: scan + monitor loop
        print(f" Live -- scan every {args.interval}s"
              f"  |  exit check every {MONITOR_MINS}m"
              f"  |  Ctrl+C to exit\n")

        last_exit_check = 0.0

        while True:
            try:
                await _one_scan()

                # check exits every MONITOR_MINS
                now = time.time()
                if now - last_exit_check >= MONITOR_MINS * 60:
                    if _open_signals:
                        print(f"\n [{time.strftime('%H:%M:%S')}]"
                              f" Checking {len(_open_signals)} open signal(s) ...",
                              flush=True)
                        await _check_exits(client)
                    last_exit_check = now

                # show open signals status with live z
                if _open_signals:
                    print(f"\n Open signals: {len(_open_signals)}")
                    z_map = await _z_now_all(client)
                    for s in _open_signals:
                        z_now = z_map.get(id(s), s.entry_z)
                        conv  = abs(z_now) < abs(s.entry_z)
                        tag   = "[<]" if conv else "[>]"
                        print(f"  {s.sym_a}+{s.sym_b}")
                        print(f"  in={s.entry_z:+.2f} now={z_now:+.2f} {tag}"
                              f" {s.age_hours:.1f}h")

            except Exception as e:
                print(f" ERROR: {e}")

            await asyncio.sleep(args.interval)


if __name__ == "__main__":
    asyncio.run(main())
