"""XT Exchange signal CLI — fully automated, no prompts.

Usage examples:
  python scripts/signal_cli.py btc_usdt
  python scripts/signal_cli.py btc_usdt -s ema_cross -i 4h -m spot -n 500
  python scripts/signal_cli.py --scan -s rsi_reversal -i 1h -m spot --top 30
  python scripts/signal_cli.py --scan -i 4h --top 50
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from signals.engine import SignalEngine
from scanner.scanner import MarketScanner
from xt_mcp.clients.spot import XTSpotClient
from xt_mcp.clients.futures import XTFuturesClient

G = "\033[92m"  # green
R = "\033[91m"  # red
Y = "\033[93m"  # yellow
C = "\033[96m"  # cyan
B = "\033[1m"   # bold
D = "\033[2m"   # dim
X = "\033[0m"   # reset


def g(t): return f"{G}{t}{X}"
def r(t): return f"{R}{t}{X}"
def y(t): return f"{Y}{t}{X}"
def c(t): return f"{C}{t}{X}"
def b(t): return f"{B}{t}{X}"


# ── single symbol signal ────────────────────────────────────────────────────

async def cmd_signal(symbol: str, strategy: str, interval: str, market: str, lookback: int) -> None:
    print(f"\n{y('...')} Fetching {b(symbol.upper())} | {strategy} | {interval} | {market}")
    engine = SignalEngine()
    try:
        signals, df = await engine.run_with_df(
            symbol=symbol, interval=interval,
            strategy_name=strategy, market=market,
            lookback=min(lookback, 1000),
        )
    except Exception as exc:
        print(f"{r('ERROR:')} {exc}")
        print(f"{D}Tip: try -m spot if futures fails{X}")
        sys.exit(1)

    price = df["close"].iloc[-1] if not df.empty else 0.0
    print(f"\n{b('=' * 48)}")
    print(f"  Symbol   : {c(symbol.upper())}")
    print(f"  Strategy : {strategy}")
    print(f"  Interval : {interval}   Market: {market}")
    print(f"  Price    : {y(f'{price:,.6f}')}")
    print(f"  Candles  : {len(df)}")
    print(b('=' * 48))

    if not signals:
        print(f"\n  {y('No signals found in this range.')}\n")
        return

    buy_count  = sum(1 for s in signals if "BUY"  in str(s.signal_type))
    sell_count = sum(1 for s in signals if "SELL" in str(s.signal_type))
    print(f"\n  Total: {len(signals)}  |  BUY: {g(str(buy_count))}  |  SELL: {r(str(sell_count))}")
    print(f"\n  {b('Last 10 signals:')}\n")

    for sig in signals[-10:]:
        d        = sig.to_dict()
        stype    = str(d.get("signal_type", "?"))
        price_s  = d.get("price", 0.0)
        ts       = d.get("timestamp", 0)
        is_buy   = "BUY" in stype
        col      = g if is_buy else r
        icon     = "^" if is_buy else "v"
        print(f"  {col(f'{icon} {stype:<12}')}  price: {y(f'{price_s:>16,.6f}')}  ts: {ts}")

    last_type = str(signals[-1].to_dict().get("signal_type", ""))
    print()
    if "BUY"  in last_type: print(f"  {b(g('>> LATEST: BUY'))}")
    if "SELL" in last_type: print(f"  {b(r('>> LATEST: SELL'))}")
    print()


# ── market scan ────────────────────────────────────────────────────────────

async def _fetch_symbols(market: str, top: int) -> list[str]:
    print(f"{y('...')} Fetching symbol list from XT ({market})...")
    try:
        client = XTSpotClient() if market == "spot" else XTFuturesClient()
        raw    = await client.get_symbols()
        syms   = [s.symbol for s in raw if str(getattr(s, "symbol", "")).endswith("_usdt")]
    except Exception as exc:
        print(f"{D}Symbol fetch failed ({exc}), using fallback list.{X}")
        syms = [
            "btc_usdt","eth_usdt","bnb_usdt","sol_usdt","xrp_usdt",
            "ada_usdt","doge_usdt","avax_usdt","dot_usdt","matic_usdt",
            "link_usdt","ltc_usdt","uni_usdt","atom_usdt","xlm_usdt",
            "trx_usdt","etc_usdt","near_usdt","apt_usdt","op_usdt",
            "arb_usdt","fil_usdt","ftm_usdt","sand_usdt","mana_usdt",
            "gala_usdt","axs_usdt","imx_usdt","inj_usdt","sei_usdt",
        ]
    return syms[:top]


async def cmd_scan(strategy: str, interval: str, market: str, top: int) -> None:
    symbols = await _fetch_symbols(market, top)
    print(f"{y('...')} Scanning {len(symbols)} symbols | {strategy} | {interval} | {market}")
    print(f"{D}(this may take a minute...){X}\n")

    scanner = MarketScanner(concurrency=5, lookback=200)
    try:
        result = await scanner.scan(symbols=symbols, strategy_name=strategy,
                                    interval=interval, market=market)
    except Exception as exc:
        print(f"{r('ERROR:')} {exc}")
        sys.exit(1)

    active      = result.with_signals()
    buy_results = [x for x in active if x.buy_signals  > x.sell_signals]
    sel_results = [x for x in active if x.sell_signals >= x.buy_signals and x.sell_signals > 0]

    print(f"{b('=' * 52)}")
    print(f"  SCAN RESULTS")
    print(f"  Scanned: {result.scanned}  OK: {result.succeeded}  Err: {result.failed}")
    print(f"  Active : {len(active)}  BUY: {g(str(len(buy_results)))}  SELL: {r(str(len(sel_results)))}")
    print(f"  Time   : {result.elapsed_ms/1000:.1f}s")
    print(b('=' * 52))

    if buy_results:
        print(f"\n  {b(g('BUY signals:'))}\n")
        for x in buy_results[:20]:
            d = x.latest_signal.to_dict() if x.latest_signal else {}
            p = d.get("price", 0.0)
            print(f"  {g('^')} {c(x.symbol):<18} signals:{g(str(x.buy_signals))}  price:{y(f'{p:>14,.6f}')}")

    if sel_results:
        print(f"\n  {b(r('SELL signals:'))}\n")
        for x in sel_results[:20]:
            d = x.latest_signal.to_dict() if x.latest_signal else {}
            p = d.get("price", 0.0)
            print(f"  {r('v')} {c(x.symbol):<18} signals:{r(str(x.sell_signals))}  price:{y(f'{p:>14,.6f}')}")

    if not active:
        print(f"\n  {y('No symbols with active signals found.')}")
    print()


# ── entry point ────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        prog="signal_cli",
        description="XT Exchange signal tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/signal_cli.py btc_usdt\n"
            "  python scripts/signal_cli.py eth_usdt -s ema_cross -i 4h\n"
            "  python scripts/signal_cli.py --scan -i 1h --top 30\n"
            "  python scripts/signal_cli.py --scan -s macd_cross -i 4h -m spot --top 50\n"
        ),
    )
    p.add_argument("symbol",        nargs="?", default=None,
                   help="symbol e.g. btc_usdt  (omit for --scan)")
    p.add_argument("-s","--strategy", default="rsi_reversal",
                   choices=["rsi_reversal","ema_cross","macd_cross","bb_mean_revert","combined_momentum"],
                   help="signal strategy (default: rsi_reversal)")
    p.add_argument("-i","--interval", default="1h",
                   choices=["1m","5m","15m","1h","4h","1d"],
                   help="candle interval (default: 1h)")
    p.add_argument("-m","--market",   default="spot",
                   choices=["spot","futures"],
                   help="market (default: spot)")
    p.add_argument("-n","--lookback", default=200, type=int,
                   help="candles to load for single symbol (default: 200, max: 1000)")
    p.add_argument("--scan",          action="store_true",
                   help="scan full market instead of one symbol")
    p.add_argument("--top",           default=30, type=int,
                   help="max symbols to scan (default: 30)")

    args = p.parse_args()

    if args.scan:
        asyncio.run(cmd_scan(args.strategy, args.interval, args.market, args.top))
    elif args.symbol:
        asyncio.run(cmd_signal(args.symbol, args.strategy, args.interval, args.market, args.lookback))
    else:
        p.print_help()


if __name__ == "__main__":
    main()
