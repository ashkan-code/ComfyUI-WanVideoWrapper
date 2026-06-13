"""Pivot-based confluence scanner — Bitunix.

Usage:
  python scripts/pivot_scan.py btc_usdt
  python scripts/pivot_scan.py btc_usdt --no-backtest
  python scripts/pivot_scan.py --scan --top 10
  python scripts/pivot_scan.py --scan --top 15 --pool 60 --min-prob 0.6
"""

from __future__ import annotations
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bitunix.client as bx
from pivot.engine    import detect_pivots
from pivot.cluster   import cluster_pivots, atr14
from pivot.structure import detect_structure
from pivot.analyzer  import analyze_reactions
from pivot.scorer    import score_cluster
from pivot.backtester import backtest_clusters

G="\033[92m";R="\033[91m";Y="\033[93m";C="\033[96m";B="\033[1m";D="\033[2m";X="\033[0m"
def g(t): return f"{G}{t}{X}"
def r(t): return f"{R}{t}{X}"
def y(t): return f"{Y}{t}{X}"
def c(t): return f"{C}{t}{X}"
def b(t): return f"{B}{t}{X}"

# Pivot window per timeframe: larger TF = smaller n (fewer, cleaner pivots)
_TF_N    = {"1h": 3, "4h": 2, "1d": 2}
_TFS     = ["1h", "4h", "1d"]
_FALLBACK = [
    "btc_usdt","eth_usdt","bnb_usdt","sol_usdt","xrp_usdt","ada_usdt",
    "doge_usdt","avax_usdt","dot_usdt","link_usdt","ltc_usdt","uni_usdt",
    "atom_usdt","trx_usdt","near_usdt","apt_usdt","op_usdt","arb_usdt",
    "inj_usdt","sei_usdt","ftm_usdt","matic_usdt","fil_usdt","axs_usdt","imx_usdt",
]


async def analyze_symbol(
    symbol: str,
    reaction_atr_multiple: float = 1.0,
    reaction_window: int = 10,
    min_touches: int = 4,
    tol_pct: float = 0.5,
    do_backtest: bool = True,
    cooldown: int = 10,
    min_gap: int = 5,
    max_per_cluster: int = 3,
) -> dict | None:
    # 1. Fetch 3 timeframes
    dfs = {}
    for tf in _TFS:
        try:
            dfs[tf] = await bx.get_kline(symbol, tf, 300)
        except Exception:
            return None

    df_1h = dfs.get("1h")
    if df_1h is None or len(df_1h) < 50:
        return None

    atr          = atr14(df_1h)
    current_price = float(df_1h["close"].iloc[-1])

    # 2. Extract pivots from each TF
    all_pivots = []
    for tf, df in dfs.items():
        if len(df) < 10:
            continue
        all_pivots.extend(detect_pivots(df, tf, n=_TF_N[tf], max_pivots=100))

    if not all_pivots:
        return None

    # 3. Cluster across all TFs (ATR from 1h)
    clusters = cluster_pivots(all_pivots, atr=atr, tol_pct=tol_pct)

    # 4. Market structure from 1d pivots
    pivots_1d = detect_pivots(dfs["1d"], "1d", n=2, max_pivots=50)
    structure  = detect_structure(pivots_1d)

    # 5. Reaction analysis on 1h data
    clusters = analyze_reactions(
        df_1h, clusters,
        reaction_atr_multiple=reaction_atr_multiple,
        reaction_window=reaction_window,
        min_touches=min_touches,
    )

    # 6. Score every cluster
    for cl in clusters:
        score_cluster(cl, structure, current_price)

    # Filter: drop clusters within 0.2% of current price (too close = noise)
    # and clusters with historical_touches < 2
    clusters = [
        cl for cl in clusters
        if abs(cl.center - current_price) / current_price > 0.002
        and cl.historical_touches >= 2
    ]

    clusters.sort(key=lambda c: -c.score)

    # 7. Backtest Lite
    bt = backtest_clusters(clusters, df_1h,
                           cooldown=cooldown,
                           min_gap=min_gap,
                           max_per_cluster=max_per_cluster) if do_backtest else None

    return {
        "symbol":   symbol,
        "price":    current_price,
        "trend":    structure.trend,
        "clusters": clusters,
        "backtest": bt,
        "atr":      atr,
    }


def _print_report(res: dict, top_n: int = 5) -> None:
    sym   = res["symbol"]
    price = res["price"]
    trend = res["trend"]
    atr   = res["atr"]
    bt    = res["backtest"]
    cls   = res["clusters"][:top_n]

    tc = g(trend) if trend=="UPTREND" else (r(trend) if trend=="DOWNTREND" else y(trend))
    print(f"\n{b('='*58)}")
    price_s = y(f"{price:,.6f}")
    print(f"  {c(sym.upper())}   price:{price_s}   trend:{tc}   ATR:{atr:.5f}")
    print(b('='*58))

    if not cls:
        print(f"  {y('No clusters found.')}\n")
        return

    print(f"\n  {b('PIVOT CLUSTERS:')}\n")
    hdr = f"  {'CLUSTER':>14}  {'DIST%':>6}  {'PROB':>6}  {'CONF':>6}  {'TFs':>3}  {'TCH':>4}  {'SCR':>4}  TF LIST"
    print(hdr)
    print(f"  {'-'*90}")

    for cl in cls:
        dist  = (cl.center - price) / price * 100
        tfs   = "+".join(sorted(cl.timeframes))
        pc    = g(f"{cl.probability:.2f}") if cl.probability>=0.65 else (y(f"{cl.probability:.2f}") if cl.probability>=0.5 else r(f"{cl.probability:.2f}"))
        cc    = g(f"{cl.confidence:.2f}") if cl.confidence>=0.7  else (y(f"{cl.confidence:.2f}") if cl.confidence>=0.4 else r(f"{cl.confidence:.2f}"))
        sc    = g(str(cl.score)) if cl.score>=70 else (y(str(cl.score)) if cl.score>=50 else str(cl.score))
        center_s = y(f"{cl.center:>14,.6f}")
        print(f"  {center_s}  {dist:>+6.2f}%  {pc:>14}  {cc:>14}  {cl.tf_count:>3}  {cl.historical_touches:>4}  {sc:>12}  {tfs}")

    if bt:
        pf    = f"{bt.profit_factor:.2f}" if bt.profit_factor != float("inf") else "inf"
        wrc   = g(f"{bt.win_rate:.1%}") if bt.win_rate>=0.55 else (y(f"{bt.win_rate:.1%}") if bt.win_rate>=0.45 else r(f"{bt.win_rate:.1%}"))
        exc   = g(f"{bt.expectancy:+.3f}") if bt.expectancy>0 else r(f"{bt.expectancy:+.3f}")
        mdd_s = r(f"{bt.max_drawdown:.2f}")
        pf_c  = g(pf) if bt.profit_factor >= 1.3 else (y(pf) if bt.profit_factor >= 1.0 else r(pf))
        print(f"\n  {b('BACKTEST RESULTS:')}")
        print(f"  trades:{bt.total_trades}  per100:{bt.trades_per_100}  avg_hold:{bt.avg_holding_bars}bars")
        print(f"  WR:{wrc}  PF:{pf_c}  Exp:{exc}ATR  MDD:{mdd_s}ATR  MaxLoss:{r(str(bt.max_consec_losses))}")
        if bt.overtrading_warning:
            print(f"  {r('WARNING: Possible overtrading / overfitting detected')}")
            print(f"  {D}  trades({bt.total_trades}) > candles*0.5 — reduce pool or increase cooldown{X}")
    print()


async def cmd_single(args) -> None:
    print(f"\n{y('...')} {b(args.symbol.upper())} | 1h+4h+1d | 300 candles | Bitunix")
    res = await analyze_symbol(
        args.symbol,
        reaction_atr_multiple=args.atr_mult,
        reaction_window=args.react_window,
        min_touches=args.min_touches,
        do_backtest=not args.no_backtest,
        cooldown=args.cooldown,
        min_gap=args.min_gap,
        max_per_cluster=args.max_per_cluster,
    )
    if not res:
        print(r("ERROR: could not fetch or analyze data"))
        sys.exit(1)
    _print_report(res)


async def cmd_scan(args) -> None:
    print(f"\n{y('...')} Fetching symbol list from Bitunix...")
    syms = await bx.get_symbols(args.pool)
    if not syms:
        syms = _FALLBACK[:args.pool]
        print(f"{D}Fallback: {len(syms)} symbols{X}")
    else:
        print(f"    {len(syms)} USDT pairs found. Scanning...")

    sem = asyncio.Semaphore(4)
    async def _run(sym):
        async with sem:
            return await analyze_symbol(sym, do_backtest=False,
                                        reaction_atr_multiple=args.atr_mult,
                                        reaction_window=args.react_window,
                                        min_touches=args.min_touches)

    results = await asyncio.gather(*[_run(s) for s in syms])
    results = [x for x in results if x and x["clusters"]]
    results = [x for x in results if x["clusters"][0].probability >= args.min_prob]
    results.sort(key=lambda x: -x["clusters"][0].score)
    top = results[:args.top]

    print(f"\n{b('='*64)}")
    print(f"  SCAN  |  {len(results)} candidates  |  top {args.top}  |  min_prob={args.min_prob}")
    print(b('='*64))

    if not top:
        print(f"\n  {y('No candidates above threshold.')}\n")
        return

    print(f"\n  {'#':<3} {'SYMBOL':<14} {'PRICE':>14}  {'TREND':<11}  {'PROB':>6}  {'CONF':>6}  {'SCR':>4}  {'CLUSTER':>14}")
    print(f"  {'-'*90}")
    for i, res in enumerate(top, 1):
        cl   = res["clusters"][0]
        tc   = g("UP") if res["trend"]=="UPTREND" else (r("DN") if res["trend"]=="DOWNTREND" else y("RNG"))
        pc   = g(f"{cl.probability:.2f}") if cl.probability>=0.65 else y(f"{cl.probability:.2f}")
        cc   = g(f"{cl.confidence:.2f}") if cl.confidence>=0.7 else (y(f"{cl.confidence:.2f}") if cl.confidence>=0.4 else r(f"{cl.confidence:.2f}"))
        sc   = g(str(cl.score)) if cl.score>=70 else (y(str(cl.score)) if cl.score>=50 else str(cl.score))
        price_s   = y(f"{res['price']:>12,.4f}")
        center_s  = y(f"{cl.center:>12,.4f}")
        sym_s     = c(res["symbol"])
        num_s     = g(str(i))
        print(f"  {num_s:<10} {sym_s:<17} {price_s}  {tc:<18}  {pc:>14}  {cc:>14}  {sc:>12}  {center_s}")
    print()


def main():
    p = argparse.ArgumentParser(
        prog="pivot_scan",
        description="Pivot confluence scanner — Bitunix",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/pivot_scan.py btc_usdt\n"
            "  python scripts/pivot_scan.py eth_usdt --no-backtest\n"
            "  python scripts/pivot_scan.py --scan --top 10\n"
            "  python scripts/pivot_scan.py --scan --pool 60 --min-prob 0.6 --top 15\n"
        ),
    )
    p.add_argument("symbol",         nargs="?", default=None)
    p.add_argument("--scan",         action="store_true")
    p.add_argument("--top",          type=int,   default=10)
    p.add_argument("--pool",         type=int,   default=50,   help="symbols to scan")
    p.add_argument("--min-prob",     type=float, default=0.55, dest="min_prob")
    p.add_argument("--atr-mult",     type=float, default=1.5,  dest="atr_mult",  help="reaction ATR multiple (default 1.5)")
    p.add_argument("--react-window", type=int,   default=10,   dest="react_window")
    p.add_argument("--min-touches",    type=int,   default=4,   dest="min_touches")
    p.add_argument("--no-backtest",    action="store_true",     dest="no_backtest")
    p.add_argument("--cooldown",       type=int,   default=10,  help="bars before re-trading same cluster")
    p.add_argument("--min-gap",        type=int,   default=5,   dest="min_gap",  help="min bars between any trades")
    p.add_argument("--max-per-cluster",type=int,   default=3,   dest="max_per_cluster", help="max trades per cluster")
    args = p.parse_args()

    if args.scan:
        asyncio.run(cmd_scan(args))
    elif args.symbol:
        asyncio.run(cmd_single(args))
    else:
        p.print_help()


if __name__ == "__main__":
    main()
