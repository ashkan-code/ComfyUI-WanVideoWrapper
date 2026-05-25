"""
SPELLUSDT — ICT Chart Generator
رسم چارت با تمام سطوح ICT: OB، FVG، Liquidity، Entry/SL/TP
"""

import asyncio
import aiohttp
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyArrowPatch
import pandas as pd
from datetime import datetime

import sys
sys.path.insert(0, "/home/user/ComfyUI-WanVideoWrapper")
from bitunix_scanner.client import AsyncBitunixClient
from bitunix_scanner.ict import (
    detect_order_blocks, detect_fvg, detect_liquidity_sweep,
    find_impulse_for_ote, find_ote_zone, _klines_to_df, _swing_highs, _swing_lows
)

API_KEY    = "7bee3f4756a0dbc89ae152f34c2175ac"
SECRET_KEY = "4e0a845778d49068297106a64cbcda61"
SYM        = "SPELLUSDT"


def _to_df(raw):
    df = _klines_to_df(raw)
    df["dt"] = pd.to_datetime(df["time"], unit="ms")
    return df


def draw_candles(ax, df, width_frac=0.6):
    """Draw OHLC candlesticks manually."""
    w = (df["dt"].iloc[1] - df["dt"].iloc[0]).total_seconds() / 86400 * width_frac
    for _, row in df.iterrows():
        color = "#26a69a" if row["close"] >= row["open"] else "#ef5350"
        # wick
        ax.plot([row["dt"], row["dt"]], [row["low"], row["high"]],
                color=color, linewidth=0.8, zorder=2)
        # body
        body_lo = min(row["open"], row["close"])
        body_hi = max(row["open"], row["close"])
        rect = mpatches.FancyBboxPatch(
            (matplotlib.dates.date2num(row["dt"]) - w/2, body_lo),
            w, max(body_hi - body_lo, row["close"] * 0.00002),
            boxstyle="square,pad=0", linewidth=0,
            facecolor=color, zorder=3,
            transform=ax.transData
        )
        ax.add_patch(rect)


async def main():
    async with aiohttp.ClientSession() as session:
        client = AsyncBitunixClient(API_KEY, SECRET_KEY, session)

        print("Fetching klines…")
        c1h  = await client.get_klines(SYM, "1h",  80)
        c15m = await client.get_klines(SYM, "15m", 100)
        c5m  = await client.get_klines(SYM, "5m",  60)

        df1h  = _to_df(c1h[-60:])
        df15m = _to_df(c15m[-80:])
        df5m  = _to_df(c5m[-50:])

        cur = float(c5m[-1]["close"])
        print(f"Current price: {cur:.8f}")

        # ── ICT levels ────────────────────────────────────────────────────
        # Order Blocks
        obs_1h  = detect_order_blocks(c1h,  "1h",  max_obs=4, proximity_pct=0.06)
        obs_15m = detect_order_blocks(c15m, "15m", max_obs=4, proximity_pct=0.06)

        # FVG
        fvg_1h_bear  = detect_fvg(c1h,  "bearish")[:4]
        fvg_15m_bear = detect_fvg(c15m, "bearish")[:3]

        # Liquidity sweep level
        _, liq_detail = detect_liquidity_sweep(c15m, "bearish")
        liq_level = None
        if liq_detail:
            try:
                liq_level = float(liq_detail.split()[-1])
            except Exception:
                pass

        # OTE zone
        sw_lo, sw_hi = find_impulse_for_ote(c15m, "bearish")
        ote_lo, ote_hi = find_ote_zone(sw_lo, sw_hi, "bearish")

        # Trade levels
        entry = 0.00015690
        sl    = 0.00015813
        tp1   = 0.00015444
        tp2   = 0.00015259

        # ── Figure: 3 rows (1H / 15m / 5m) ──────────────────────────────
        fig, axes = plt.subplots(3, 1, figsize=(18, 22),
                                 facecolor="#131722",
                                 gridspec_kw={"hspace": 0.08})
        fig.suptitle(f"SPELLUSDT  ICT Analysis  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                     color="white", fontsize=14, fontweight="bold", y=0.99)

        datasets = [
            (axes[0], df1h,  "1H",  obs_1h,  fvg_1h_bear),
            (axes[1], df15m, "15m", obs_15m, fvg_15m_bear),
            (axes[2], df5m,  "5m",  [],      []),
        ]

        for ax, df, label, obs, fvgs in datasets:
            ax.set_facecolor("#131722")
            ax.tick_params(colors="#aaaaaa", labelsize=7)
            for spine in ax.spines.values():
                spine.set_edgecolor("#2a2e39")
            ax.grid(color="#1e222d", linewidth=0.5, zorder=0)
            ax.set_ylabel(label, color="#aaaaaa", fontsize=9)

            # Candles
            for _, row in df.iterrows():
                color = "#26a69a" if row["close"] >= row["open"] else "#ef5350"
                ax.plot([row["dt"], row["dt"]], [row["low"], row["high"]],
                        color=color, linewidth=0.7, zorder=2)
                body_lo = min(row["open"], row["close"])
                body_hi = max(row["open"], row["close"])
                height  = max(body_hi - body_lo, cur * 0.00003)
                ax.bar(row["dt"], height, bottom=body_lo,
                       width=pd.Timedelta(minutes={"1H":55,"15m":13,"5m":4}[label]),
                       color=color, zorder=3)

            xmin = df["dt"].iloc[0]
            xmax = df["dt"].iloc[-1] + pd.Timedelta(minutes={"1H":60,"15m":15,"5m":5}[label])

            # ── OB zones ─────────────────────────────────────────────────
            for ob in obs:
                ts = pd.to_datetime(ob.timestamp, unit="ms")
                if ts < xmin or ts > xmax:
                    continue
                fc = "#ef535033" if ob.ob_type == "bearish" else "#26a69a33"
                ec = "#ef5350"   if ob.ob_type == "bearish" else "#26a69a"
                ax.axhspan(ob.ob_low, ob.ob_high, alpha=0.25, color=fc, zorder=1)
                ax.axhline(ob.ob_high, color=ec, linewidth=0.8, linestyle="--", alpha=0.7, zorder=4)
                ax.axhline(ob.ob_low,  color=ec, linewidth=0.8, linestyle="--", alpha=0.7, zorder=4)
                tag = "Bearish OB" if ob.ob_type == "bearish" else "Bullish OB"
                ax.text(xmax, (ob.ob_high + ob.ob_low) / 2,
                        f" {tag} [{label}]", color=ec,
                        fontsize=7, va="center", zorder=5)

            # ── FVG zones ─────────────────────────────────────────────────
            for flo, fhi in fvgs:
                if flo > df["high"].max() * 1.01 or fhi < df["low"].min() * 0.99:
                    continue
                ax.axhspan(flo, fhi, alpha=0.18, color="#ff9800", zorder=1)
                ax.axhline(flo, color="#ff9800", linewidth=0.6, linestyle=":", alpha=0.8, zorder=4)
                ax.axhline(fhi, color="#ff9800", linewidth=0.6, linestyle=":", alpha=0.8, zorder=4)
                ax.text(xmax, (flo + fhi) / 2,
                        " FVG", color="#ff9800", fontsize=6, va="center", zorder=5)

            # ── Liquidity sweep level ─────────────────────────────────────
            if liq_level and df["low"].min() < liq_level < df["high"].max() * 1.02:
                ax.axhline(liq_level, color="#e040fb", linewidth=1.0,
                           linestyle="-.", alpha=0.85, zorder=4)
                ax.text(xmax, liq_level, " BSL Swept", color="#e040fb",
                        fontsize=7, va="bottom", zorder=5)

            # ── OTE zone ─────────────────────────────────────────────────
            if label in ("15m", "1H"):
                ax.axhspan(ote_lo, ote_hi, alpha=0.15, color="#00bcd4", zorder=1)
                ax.text(xmax, (ote_lo + ote_hi) / 2,
                        " OTE 61.8–79%", color="#00bcd4",
                        fontsize=6, va="center", zorder=5)

            # ── Entry / SL / TP ───────────────────────────────────────────
            price_range = df["high"].max() - df["low"].min()
            if abs(entry - df["close"].mean()) < price_range * 2:
                # Entry
                ax.axhline(entry, color="#ffeb3b", linewidth=1.2,
                           linestyle="-", alpha=0.9, zorder=5)
                ax.text(xmin, entry, f"ENTRY {entry:.8f} ",
                        color="#ffeb3b", fontsize=7, va="bottom",
                        ha="left", fontweight="bold", zorder=6)

                # SL
                ax.axhline(sl, color="#f44336", linewidth=1.2,
                           linestyle="-", alpha=0.9, zorder=5)
                ax.text(xmin, sl, f"SL {sl:.8f} ",
                        color="#f44336", fontsize=7, va="bottom",
                        ha="left", fontweight="bold", zorder=6)

                # TP1
                ax.axhline(tp1, color="#4caf50", linewidth=1.0,
                           linestyle="--", alpha=0.9, zorder=5)
                ax.text(xmin, tp1, f"TP1 {tp1:.8f} ",
                        color="#4caf50", fontsize=7, va="bottom",
                        ha="left", zorder=6)

                # TP2
                ax.axhline(tp2, color="#8bc34a", linewidth=1.0,
                           linestyle="--", alpha=0.9, zorder=5)
                ax.text(xmin, tp2, f"TP2 {tp2:.8f} ",
                        color="#8bc34a", fontsize=7, va="bottom",
                        ha="left", zorder=6)

                # Entry-SL shaded zone
                ax.axhspan(entry, sl, alpha=0.08, color="#f44336", zorder=1)
                ax.axhspan(tp1, entry, alpha=0.06, color="#4caf50", zorder=1)

            # Current price line
            ax.axhline(cur, color="#ffffff", linewidth=0.6,
                       linestyle=":", alpha=0.5, zorder=4)
            ax.text(xmax, cur, f" {cur:.8f}", color="#ffffff",
                    fontsize=6, va="center", zorder=5)

            ax.set_xlim(xmin, xmax + pd.Timedelta(hours={"1H":8,"15m":2,"5m":1}[label]))
            ax.xaxis.set_major_formatter(
                matplotlib.dates.DateFormatter("%m/%d %H:%M")
            )
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")

        # ── Legend ───────────────────────────────────────────────────────
        legend_items = [
            mpatches.Patch(color="#ef5350", alpha=0.6, label="Bearish OB"),
            mpatches.Patch(color="#26a69a", alpha=0.6, label="Bullish OB"),
            mpatches.Patch(color="#ff9800", alpha=0.5, label="FVG"),
            mpatches.Patch(color="#00bcd4", alpha=0.4, label="OTE Zone (61.8–79%)"),
            mpatches.Patch(color="#e040fb", alpha=0.7, label="BSL Swept"),
            mpatches.Patch(color="#ffeb3b", alpha=0.9, label="Entry"),
            mpatches.Patch(color="#f44336", alpha=0.9, label="Stop Loss"),
            mpatches.Patch(color="#4caf50", alpha=0.9, label="TP1 (2:1)"),
            mpatches.Patch(color="#8bc34a", alpha=0.9, label="TP2 (3.5:1)"),
        ]
        axes[0].legend(handles=legend_items, loc="upper left",
                       facecolor="#1e222d", edgecolor="#2a2e39",
                       labelcolor="white", fontsize=8, ncol=3)

        out = "/tmp/spell_ict_chart.png"
        plt.savefig(out, dpi=150, bbox_inches="tight",
                    facecolor="#131722", edgecolor="none")
        plt.close()
        print(f"✅ Chart saved: {out}")
        return out


if __name__ == "__main__":
    asyncio.run(main())
