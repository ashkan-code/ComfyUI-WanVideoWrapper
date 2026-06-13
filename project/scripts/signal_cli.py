"""XT Exchange signal CLI — uses Bitunix API, no prompts.

Usage:
  python scripts/signal_cli.py btc_usdt
  python scripts/signal_cli.py btc_usdt -s ema_cross -i 4h -n 500
  python scripts/signal_cli.py --scan -i 1h --top 10
  python scripts/signal_cli.py --scan -s macd_cross -i 4h --top 20
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bitunix.client as bx
from signals.registry import get_strategy

G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"
C = "\033[96m"; B = "\033[1m";  D = "\033[2m"; X = "\033[0m"

def g(t): return f"{G}{t}{X}"
def r(t): return f"{R}{t}{X}"
def y(t): return f"{Y}{t}{X}"
def c(t): return f"{C}{t}{X}"
def b(t): return f"{B}{t}{X}"


STRATEGIES = ["rsi_reversal", "ema_cross", "macd_cross", "bb_mean_revert", "combined_momentum"]
INTERVALS  = ["1m", "5m", "15m", "1h", "4h", "1d"]

_FALLBACK_SYMBOLS = [
    "btc_usdt","eth_usdt","bnb_usdt","sol_usdt","xrp_usdt",
    "ada_usdt","doge_usdt","avax_usdt","dot_usdt","link_usdt",
    "ltc_usdt","uni_usdt","atom_usdt","trx_usdt","near_usdt",
    "apt_usdt","op_usdt","arb_usdt","inj_usdt","sei_usdt",
    "ftm_usdt","matic_usdt","fil_usdt","gala_usdt","axs_usdt",
    "sand_usdt","mana_usdt","imx_usdt","xlm_usdt","etc_usdt",
]


async def _fetch_and_signal(symbol: str, strategy_name: str, interval: str, lookback: int):
    df = await bx.get_kline(symbol, interval, lookback)
    if df.empty:
        raise RuntimeError("empty dataframe")
    strategy = get_strategy(strategy_name)
    signals  = strategy.generate(df, symbol=symbol, market="futures", interval=interval)
    return signals, df


# ── single symbol ───────────────────────────────────────────────────────────

async def cmd_signal(symbol: str, strategy: str, interval: str, lookback: int) -> None:
    print(f"\n{y('...')} {b(symbol.upper())} | {strategy} | {interval} | Bitunix")
    try:
        signals, df = await _fetch_and_signal(symbol, strategy, interval, lookback)
    except Exception as exc:
        print(f"{r('ERROR:')} {exc}")
        sys.exit(1)

    price = df["close"].iloc[-1]
    buys  = sum(1 for s in signals if "BUY"  in str(s.signal_type))
    sells = sum(1 for s in signals if "SELL" in str(s.signal_type))

    print(f"\n{b('=' * 50)}")
    print(f"  Symbol   : {c(symbol.upper())}")
    print(f"  Strategy : {strategy}   Interval: {interval}")
    print(f"  Price    : {y(f'{price:,.6f}')}   Candles: {len(df)}")
    print(f"  Signals  : {len(signals)}  BUY: {g(str(buys))}  SELL: {r(str(sells))}")
    print(b('=' * 50))

    if not signals:
        print(f"\n  {y('No signals in this range.')}\n")
        return

    print(f"\n  {b('Last 10 signals:')}\n")
    for sig in signals[-10:]:
        d       = sig.to_dict()
        stype   = str(d.get("signal_type", "?"))
        px      = d.get("price", 0.0)
        ts      = d.get("timestamp", 0)
        is_buy  = "BUY" in stype
        col     = g if is_buy else r
        icon    = "^" if is_buy else "v"
        print(f"  {col(f'{icon} {stype:<12}')}  price: {y(f'{px:>16,.6f}')}  ts:{ts}")

    last_type = str(signals[-1].to_dict().get("signal_type", ""))
    print()
    if "BUY"  in last_type: print(f"  {b(g('>> LATEST: BUY'))}")
    if "SELL" in last_type: print(f"  {b(r('>> LATEST: SELL'))}")
    print()


# ── scan + best candidates ─────────────────────────────────────────────────

def _score(signals: list, df_len: int) -> float:
    """Score a symbol: recency of last BUY + buy/total ratio."""
    if not signals:
        return 0.0
    last = str(signals[-1].to_dict().get("signal_type", ""))
    if "BUY" not in last:
        return 0.0  # last signal must be BUY
    buys  = sum(1 for s in signals if "BUY"  in str(s.signal_type))
    total = len(signals)
    # recency bonus: last signal position (closer to end = better)
    recency = 1.0  # already filtered to last-is-BUY
    buy_ratio = buys / total if total else 0
    return round(recency * buy_ratio * 100, 2)


async def _scan_one(symbol: str, strategy: str, interval: str, lookback: int, sem: asyncio.Semaphore):
    async with sem:
        try:
            signals, df = await _fetch_and_signal(symbol, strategy, interval, lookback)
            score = _score(signals, len(df))
            price = df["close"].iloc[-1] if not df.empty else 0.0
            return {"symbol": symbol, "score": score, "signals": signals,
                    "price": price, "ok": True}
        except Exception as exc:
            return {"symbol": symbol, "score": 0.0, "signals": [],
                    "price": 0.0, "ok": False, "err": str(exc)}


async def cmd_scan(strategy: str, interval: str, pool: int, top: int, lookback: int) -> None:
    # 1. get symbols
    print(f"{y('...')} Fetching symbols from Bitunix...")
    syms = await bx.get_symbols(pool)
    if not syms:
        syms = _FALLBACK_SYMBOLS[:pool]
        print(f"{D}Using fallback list ({len(syms)} symbols){X}")
    else:
        print(f"    Got {len(syms)} USDT pairs")

    print(f"{y('...')} Scanning {len(syms)} symbols | {strategy} | {interval}\n")

    sem     = asyncio.Semaphore(5)
    tasks   = [_scan_one(s, strategy, interval, lookback, sem) for s in syms]
    results = await asyncio.gather(*tasks)

    ok      = [x for x in results if x["ok"]]
    failed  = len(results) - len(ok)

    # 2. filter: last signal must be BUY, score > 0
    candidates = [x for x in ok if x["score"] > 0]
    candidates.sort(key=lambda x: -x["score"])
    best = candidates[:top]

    print(f"{b('=' * 54)}")
    print(f"  SCAN RESULTS  |  Bitunix  |  {strategy}  |  {interval}")
    print(f"  Scanned: {len(syms)}   OK: {len(ok)}   Failed: {failed}")
    print(f"  BUY candidates: {g(str(len(candidates)))}   Showing top: {top}")
    print(b('=' * 54))

    if not best:
        print(f"\n  {y('No BUY candidates found. Try different strategy or interval.')}\n")
        return

    print(f"\n  {b(g('TOP BUY CANDIDATES:'))}\n")
    print(f"  {'#':<4} {'SYMBOL':<16} {'SCORE':>6}  {'PRICE':>16}  {'SIGNALS'}")
    print(f"  {'-'*4} {'-'*16} {'-'*6}  {'-'*16}  {'-'*7}")
    for i, x in enumerate(best, 1):
        sigs  = x["signals"]
        buys  = sum(1 for s in sigs if "BUY"  in str(s.signal_type))
        total = len(sigs)
        print(f"  {g(str(i)):<7} {c(x['symbol']):<19} {y(str(x['score'])):>8}  "
              f"{y(f'{x[\"price\"]:>14,.6f}')}"
              f"  BUY:{g(str(buys))} / {total}")

    print()


# ── entry point ────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        prog="signal_cli",
        description="Bitunix signal scanner — best candidates only",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/signal_cli.py btc_usdt\n"
            "  python scripts/signal_cli.py eth_usdt -s ema_cross -i 4h\n"
            "  python scripts/signal_cli.py --scan --top 10\n"
            "  python scripts/signal_cli.py --scan -s macd_cross -i 4h --top 15 --pool 80\n"
        ),
    )
    p.add_argument("symbol",         nargs="?", default=None,
                   help="symbol e.g. btc_usdt")
    p.add_argument("-s","--strategy", default="rsi_reversal", choices=STRATEGIES)
    p.add_argument("-i","--interval", default="1h", choices=INTERVALS)
    p.add_argument("-n","--lookback", default=200, type=int,
                   help="candles to load (default 200)")
    p.add_argument("--scan",          action="store_true",
                   help="scan market for best BUY candidates")
    p.add_argument("--top",           default=10, type=int,
                   help="show only top N best candidates (default 10)")
    p.add_argument("--pool",          default=50, type=int,
                   help="how many symbols to scan (default 50)")

    args = p.parse_args()

    if args.scan:
        asyncio.run(cmd_scan(args.strategy, args.interval,
                             args.pool, args.top, args.lookback))
    elif args.symbol:
        asyncio.run(cmd_signal(args.symbol, args.strategy,
                               args.interval, args.lookback))
    else:
        p.print_help()


if __name__ == "__main__":
    main()
