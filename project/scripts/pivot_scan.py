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
from pivot.backtester  import backtest_clusters
from pivot.optimizer   import run_sweep, opportunity_rank, TOTAL_COMBINATIONS
from pivot.trend_score import compute_trend_score, compute_volume_score
from pivot.regime      import detect_regime, regime_min_prob
from pivot.scorer      import compute_quality_score

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
    min_conf: float = 0.0,
    dist_atr: float | None = None,
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

    atr           = atr14(df_1h)
    current_price = float(df_1h["close"].iloc[-1])
    last_ts       = int(df_1h["open_time"].iloc[-1])

    # 2. Extract pivots from each TF
    all_pivots = []
    for tf, df in dfs.items():
        if len(df) < 10:
            continue
        all_pivots.extend(detect_pivots(df, tf, n=_TF_N[tf], max_pivots=100))

    if not all_pivots:
        return None

    # 3. Cluster across all TFs
    clusters = cluster_pivots(all_pivots, atr=atr, tol_pct=tol_pct)

    # 4. Market structure + signal quality scores (computed once per symbol)
    pivots_1d  = detect_pivots(dfs["1d"], "1d", n=2, max_pivots=50)
    structure  = detect_structure(pivots_1d)
    regime     = detect_regime(df_1h)
    t_score    = compute_trend_score(df_1h, structure)
    v_score    = compute_volume_score(df_1h)
    regime_adj = regime_min_prob(regime, 0.55) - 0.55   # delta from default baseline

    # 5. Reaction analysis on 1h data (touch-decay weighted probability)
    clusters = analyze_reactions(
        df_1h, clusters,
        reaction_atr_multiple=reaction_atr_multiple,
        reaction_window=reaction_window,
        min_touches=min_touches,
    )

    # 6. Score + quality score for each cluster
    for cl in clusters:
        score_cluster(cl, structure, current_price)
        compute_quality_score(cl, t_score, v_score, last_ts)

    # Filter: too close to price, insufficient touches, low confidence, zero quality
    clusters = [
        cl for cl in clusters
        if abs(cl.center - current_price) / current_price > 0.002
        and cl.historical_touches >= 2
        and cl.confidence >= min_conf
        and cl.quality_score > 0.0
    ]

    # Sort by quality × recency (highest quality, freshest first)
    clusters.sort(key=lambda cl: -(cl.quality_score * cl.recency_weight))

    # 7. Backtest with regime-adjusted probability threshold
    bt = backtest_clusters(
        clusters, df_1h,
        cooldown=cooldown,
        min_gap=min_gap,
        max_per_cluster=max_per_cluster,
        entry_dist_atr=dist_atr,
        regime_prob_adj=regime_adj,
    ) if do_backtest else None

    return {
        "symbol":      symbol,
        "price":       current_price,
        "trend":       structure.trend,
        "clusters":    clusters,
        "backtest":    bt,
        "atr":         atr,
        "regime":      regime,
        "trend_score": t_score,
        "vol_score":   v_score,
    }


def _print_report(res: dict, top_n: int = 5) -> None:
    sym   = res["symbol"]
    price = res["price"]
    trend = res["trend"]
    atr   = res["atr"]
    bt    = res["backtest"]
    cls   = res["clusters"][:top_n]

    regime  = res.get("regime", "?")
    ts_val  = res.get("trend_score", 0.5)
    vs_val  = res.get("vol_score", 0.5)
    tc      = g(trend) if trend=="UPTREND" else (r(trend) if trend=="DOWNTREND" else y(trend))
    ts_s    = g(f"{ts_val:.3f}") if ts_val>=0.65 else (y(f"{ts_val:.3f}") if ts_val>=0.40 else r(f"{ts_val:.3f}"))
    vs_s    = g(f"{vs_val:.3f}") if vs_val>=0.50 else (y(f"{vs_val:.3f}") if vs_val>=0.25 else r(f"{vs_val:.3f}"))
    rgm_c   = c(regime)

    print(f"\n{b('='*70)}")
    price_s = y(f"{price:,.6f}")
    print(f"  {c(sym.upper())}   price:{price_s}   trend:{tc}   ATR:{atr:.5f}")
    print(f"  TrendScore:{ts_s}   VolumeScore:{vs_s}   Regime:{rgm_c}")
    print(b('='*70))

    if not cls:
        print(f"  {y('No clusters found.')}\n")
        return

    print(f"\n  {b('PIVOT CLUSTERS:')}\n")
    hdr = f"  {'CLUSTER':>14}  {'DIST%':>6}  {'PROB':>6}  {'CONF':>6}  {'TFs':>3}  {'TCH':>4}  {'SCR':>4}  {'QUAL':>6}  {'RCY':>5}  TF LIST"
    print(hdr)
    print(f"  {'-'*108}")

    for cl in cls:
        dist   = (cl.center - price) / price * 100
        tfs    = "+".join(sorted(cl.timeframes))
        pc     = g(f"{cl.probability:.2f}") if cl.probability>=0.65 else (y(f"{cl.probability:.2f}") if cl.probability>=0.5 else r(f"{cl.probability:.2f}"))
        cc     = g(f"{cl.confidence:.2f}") if cl.confidence>=0.7  else (y(f"{cl.confidence:.2f}") if cl.confidence>=0.4 else r(f"{cl.confidence:.2f}"))
        sc     = g(str(cl.score)) if cl.score>=70 else (y(str(cl.score)) if cl.score>=50 else str(cl.score))
        qual   = cl.quality_score
        qual_s = g(f"{qual:.3f}") if qual>=0.15 else (y(f"{qual:.3f}") if qual>=0.08 else r(f"{qual:.3f}"))
        rcy_s  = g(f"{cl.recency_weight:.2f}") if cl.recency_weight>=0.7 else y(f"{cl.recency_weight:.2f}")
        center_s = y(f"{cl.center:>14,.6f}")
        print(f"  {center_s}  {dist:>+6.2f}%  {pc:>14}  {cc:>14}  {cl.tf_count:>3}  {cl.historical_touches:>4}  {sc:>12}  {qual_s:>14}  {rcy_s:>13}  {tfs}")

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
        # False-signal analysis
        la        = bt.loss_analysis or {}
        by_touch  = la.get("by_touch",  {})
        by_volume = la.get("by_volume", {})
        if by_touch or by_volume:
            print(f"  {b('FALSE SIGNALS:')}")
            if by_touch:
                tch_s = "  ".join(f"#{k}:{v}" for k, v in sorted(by_touch.items()))
                print(f"    by_touch:  {tch_s}")
            if by_volume:
                vol_s = "  ".join(f"{k}:{v}" for k, v in sorted(by_volume.items()))
                print(f"    by_volume: {vol_s}")
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
        min_conf=args.min_conf,
        dist_atr=args.dist_atr,
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
    if args.min_conf > 0.0:
        results = [x for x in results if x["clusters"][0].confidence >= args.min_conf]
    def _rank_key(x: dict) -> float:
        cl = x["clusters"][0]
        if cl.quality_score > 0.0:
            return cl.quality_score * cl.recency_weight
        return opportunity_rank(cl, x["trend"], x["price"])

    results.sort(key=lambda x: -_rank_key(x))
    top = results[:args.top]

    print(f"\n{b('='*64)}")
    print(f"  SCAN  |  {len(results)} candidates  |  top {args.top}  |  min_prob={args.min_prob}")
    print(b('='*64))

    if not top:
        print(f"\n  {y('No candidates above threshold.')}\n")
        return

    print(f"\n  {'#':<3} {'SYMBOL':<14} {'PRICE':>14}  {'TREND':<11}  {'PROB':>6}  {'CONF':>6}  {'QUAL':>6}  {'RCY':>5}  {'SCR':>4}  {'CLUSTER':>14}")
    print(f"  {'-'*112}")
    for i, res in enumerate(top, 1):
        cl     = res["clusters"][0]
        tc     = g("UP") if res["trend"]=="UPTREND" else (r("DN") if res["trend"]=="DOWNTREND" else y("RNG"))
        pc     = g(f"{cl.probability:.2f}") if cl.probability>=0.65 else y(f"{cl.probability:.2f}")
        cc     = g(f"{cl.confidence:.2f}") if cl.confidence>=0.7 else (y(f"{cl.confidence:.2f}") if cl.confidence>=0.4 else r(f"{cl.confidence:.2f}"))
        sc     = g(str(cl.score)) if cl.score>=70 else (y(str(cl.score)) if cl.score>=50 else str(cl.score))
        qual   = cl.quality_score
        qual_s = g(f"{qual:.3f}") if qual>=0.15 else (y(f"{qual:.3f}") if qual>=0.08 else r(f"{qual:.3f}"))
        rcy_s  = g(f"{cl.recency_weight:.2f}") if cl.recency_weight>=0.7 else y(f"{cl.recency_weight:.2f}")
        price_s  = y(f"{res['price']:>12,.4f}")
        center_s = y(f"{cl.center:>12,.4f}")
        sym_s    = c(res["symbol"])
        num_s    = g(str(i))
        print(f"  {num_s:<10} {sym_s:<17} {price_s}  {tc:<18}  {pc:>14}  {cc:>14}  {qual_s:>14}  {rcy_s:>13}  {sc:>12}  {center_s}")
    print()


def _print_sweep_table(results: list, symbol: str, n_robust: int) -> None:
    print(f"\n{b('='*78)}")
    print(f"  OPTIMIZATION — {c(symbol.upper())}   robust:{n_robust}/{TOTAL_COMBINATIONS:,}")
    print(b('='*78))

    if not results:
        print(f"\n  {y('No robust parameter sets found.')}")
        print(f"  Tip: add --show-all to include non-robust results\n")
        return

    # Header
    print(f"\n  {'#':>2}  {'PROB':>4} {'CONF':>4} {'TCH':>3} {'CW':>4}  {'TREND':>7}  {'CD':>2} {'DIST':>4}"
          f"    {'WR':>5}  {'PF':>5}  {'EXP':>7}  {'MDD':>5} {'N':>3}  CS")
    print(f"  {'-'*86}")

    for i, res in enumerate(results, 1):
        p     = res.params
        wr_s  = g(f"{res.win_rate:.1%}") if res.win_rate>=0.50 else (y(f"{res.win_rate:.1%}") if res.win_rate>=0.45 else r(f"{res.win_rate:.1%}"))
        pf_v  = res.profit_factor
        pf_s  = g(f"{pf_v:.2f}") if pf_v>=1.5 else (y(f"{pf_v:.2f}") if pf_v>=1.2 else r(f"{pf_v:.2f}"))
        exp_s = g(f"+{res.expectancy:.3f}") if res.expectancy>0 else r(f"{res.expectancy:+.3f}")
        mdd_s = r(f"{res.max_drawdown:.2f}")
        cs_s  = g(f"{res.composite_score:.4f}") if res.composite_score>=0.40 else y(f"{res.composite_score:.4f}")
        tag   = f"  {r('OVERFIT')}" if res.overfit_flag else ("  ★" if i == 1 else "")
        # Params section
        row_p = (f"{i:>3}  {p.min_prob:.2f} {p.min_conf:.2f} {p.min_touches:>3} {p.cluster_width_atr:.2f}"
                 f"  {p.trend_filter:>7}  {p.cooldown:>2} {p.dist_atr:.1f}")
        # Metrics section (colors embedded → use raw values for alignment)
        print(f"  {row_p}    {wr_s:>13}  {pf_s:>13}  {exp_s:>15}  {mdd_s:>13} {res.trade_count:>3}  {cs_s}{tag}")

    # Recommended config
    best = results[0]
    p    = best.params
    print(f"\n{b('='*78)}")
    print(f"  {b('RECOMMENDED')}  CS={g(f'{best.composite_score:.4f}')}"
          f"  WR={best.win_rate:.1%}  PF={best.profit_factor:.2f}"
          f"  Exp={best.expectancy:+.3f}ATR  MDD={best.max_drawdown:.2f}ATR  N={best.trade_count}")
    print(b('='*78))
    print(f"  min_prob={p.min_prob}  min_conf={p.min_conf}  min_touches={p.min_touches}")
    print(f"  cluster_width={p.cluster_width_atr}ATR  trend={p.trend_filter}  cooldown={p.cooldown}  dist={p.dist_atr}ATR")
    sym_lower = symbol.lower()
    cmd = (f"  python scripts/pivot_scan.py {sym_lower}"
           f" --min-prob {p.min_prob}"
           f" --min-conf {p.min_conf}"
           f" --min-touches {p.min_touches}"
           f" --cooldown {p.cooldown}"
           f" --dist-atr {p.dist_atr}")
    print(f"\n  Run with optimal settings:\n{y(cmd)}\n")


async def cmd_optimize(args) -> None:
    sym = args.symbol
    print(f"\n{y('...')} {b(sym.upper())} | Fetching 1h+4h+1d data (300 candles)...")
    dfs = {}
    for tf in _TFS:
        try:
            dfs[tf] = await bx.get_kline(sym, tf, 300)
        except Exception as e:
            print(r(f"ERROR fetching {tf}: {e}"))
            sys.exit(1)

    df_1h = dfs.get("1h")
    if df_1h is None or len(df_1h) < 50:
        print(r("ERROR: insufficient 1h data"))
        sys.exit(1)

    print(f"  Running parameter sweep [{TOTAL_COMBINATIONS:,} combinations]...")
    top, n_robust = run_sweep(
        dfs, _TF_N,
        reaction_atr_multiple=args.atr_mult,
        reaction_window=args.react_window,
        top_n=10,
        robust_only=not args.show_all,
        verbose=True,
    )

    _print_sweep_table(top, sym, n_robust)


def main():
    p = argparse.ArgumentParser(
        prog="pivot_scan",
        description="Pivot confluence scanner — Bitunix",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/pivot_scan.py btc_usdt\n"
            "  python scripts/pivot_scan.py btc_usdt --optimize\n"
            "  python scripts/pivot_scan.py eth_usdt --no-backtest\n"
            "  python scripts/pivot_scan.py --scan --top 10\n"
            "  python scripts/pivot_scan.py --scan --pool 60 --min-prob 0.6 --top 15\n"
        ),
    )
    p.add_argument("symbol",           nargs="?", default=None)
    p.add_argument("--scan",           action="store_true")
    p.add_argument("--optimize",       action="store_true",     help="run parameter sweep and show top configs")
    p.add_argument("--show-all",       action="store_true",     dest="show_all", help="include non-robust results in --optimize")
    p.add_argument("--top",            type=int,   default=10)
    p.add_argument("--pool",           type=int,   default=50,   help="symbols to scan")
    p.add_argument("--min-prob",       type=float, default=0.55, dest="min_prob")
    p.add_argument("--min-conf",       type=float, default=0.0,  dest="min_conf",  help="minimum cluster confidence (default 0)")
    p.add_argument("--atr-mult",       type=float, default=1.5,  dest="atr_mult",  help="reaction ATR multiple (default 1.5)")
    p.add_argument("--react-window",   type=int,   default=10,   dest="react_window")
    p.add_argument("--min-touches",    type=int,   default=4,    dest="min_touches")
    p.add_argument("--no-backtest",    action="store_true",      dest="no_backtest")
    p.add_argument("--cooldown",       type=int,   default=10,   help="bars before re-trading same cluster")
    p.add_argument("--min-gap",        type=int,   default=5,    dest="min_gap",   help="min bars between any trades")
    p.add_argument("--max-per-cluster",type=int,   default=3,    dest="max_per_cluster", help="max trades per cluster")
    p.add_argument("--dist-atr",       type=float, default=None, dest="dist_atr",  help="entry distance in ATR units (default: auto)")
    args = p.parse_args()

    if args.optimize and args.symbol:
        asyncio.run(cmd_optimize(args))
    elif args.scan:
        asyncio.run(cmd_scan(args))
    elif args.symbol:
        asyncio.run(cmd_single(args))
    else:
        p.print_help()


if __name__ == "__main__":
    main()
