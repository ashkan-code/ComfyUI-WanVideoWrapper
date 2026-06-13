"""CLI سریع برای دریافت سیگنال و اسکن بازار از XT Exchange."""

from __future__ import annotations

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from signals.engine import SignalEngine
from scanner.scanner import MarketScanner
from xt_mcp.clients.spot import XTSpotClient
from xt_mcp.clients.futures import XTFuturesClient


STRATEGIES = [
    "rsi_reversal",
    "ema_cross",
    "macd_cross",
    "bb_mean_revert",
    "combined_momentum",
]

INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"]


def _color(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"


def green(t):  return _color(t, "92")
def red(t):    return _color(t, "91")
def yellow(t): return _color(t, "93")
def bold(t):   return _color(t, "1")
def cyan(t):   return _color(t, "96")
def dim(t):    return _color(t, "2")


def _ask(prompt: str, default: str = "") -> str:
    try:
        val = input(f"{cyan('▶')} {prompt} [{default}]: ").strip()
        return val if val else default
    except (KeyboardInterrupt, EOFError):
        print("\nخروج...")
        sys.exit(0)


def _choose(prompt: str, options: list[str], default: str) -> str:
    print(f"\n{bold(prompt)}")
    for i, o in enumerate(options, 1):
        marker = green("●") if o == default else " "
        print(f"  {marker} {i}. {o}")
    raw = _ask("شماره انتخاب کن", str(options.index(default) + 1))
    try:
        idx = int(raw) - 1
        return options[idx] if 0 <= idx < len(options) else default
    except ValueError:
        return default


# ─── سیگنال یک نماد ────────────────────────────────────────────────────────

async def _run_signal(symbol: str, strategy: str, interval: str, market: str, lookback: int) -> None:
    print(f"\n{yellow('⏳ در حال دریافت داده از XT Exchange...')}")
    engine = SignalEngine()
    try:
        signals, df = await engine.run_with_df(
            symbol=symbol,
            interval=interval,
            strategy_name=strategy,
            market=market,
            lookback=lookback,
        )
    except Exception as exc:
        print(red(f"\n✗ خطا: {exc}"))
        print(dim("نکته: مطمئن شو نماد درست باشه و بازار spot رو امتحان کن."))
        return

    last_close = df["close"].iloc[-1] if not df.empty else 0.0
    print(f"\n{bold('═' * 46)}")
    print(f"  {bold('نماد:')}     {cyan(symbol.upper())}")
    print(f"  {bold('استراتژی:')} {strategy}")
    print(f"  {bold('تایم‌فریم:')} {interval}  |  بازار: {market}")
    print(f"  {bold('قیمت فعلی:')} {yellow(f'{last_close:,.6f}')}")
    print(f"  {bold('کندل‌ها:')}  {len(df)} عدد")
    print(bold('═' * 46))

    if not signals:
        print(f"\n  {yellow('⚠ سیگنالی در این بازه یافت نشد')}\n")
        return

    print(f"\n  {bold('آخرین سیگنال‌ها')} ({len(signals)} عدد کل):\n")
    for sig in signals[-10:]:
        d = sig.to_dict()
        sig_type = str(d.get("signal_type", "?"))
        price    = d.get("price", 0.0)
        ts       = d.get("timestamp", 0)
        is_buy   = "BUY" in sig_type
        color    = green if is_buy else red
        icon     = "▲" if is_buy else "▼"
        print(f"  {color(f'{icon} {sig_type:<12}')}  قیمت: {yellow(f'{price:>16,.6f}')}  زمان: {ts}")

    last_type = str(signals[-1].to_dict().get("signal_type", ""))
    print()
    if "BUY" in last_type:
        print(f"  {bold(green('✔ آخرین سیگنال: خرید (BUY)'))}")
    elif "SELL" in last_type:
        print(f"  {bold(red('✔ آخرین سیگنال: فروش (SELL)'))}")
    print()


# ─── اسکن کل بازار ─────────────────────────────────────────────────────────

async def _fetch_symbols(market: str, max_symbols: int) -> list[str]:
    """لیست نمادهای فعال رو از XT می‌گیره."""
    print(yellow("⏳ دریافت لیست نمادها..."))
    try:
        if market == "spot":
            client = XTSpotClient()
            raw = await client.get_symbols()
            # فقط نمادهایی که با usdt تموم می‌شن
            symbols = [
                s.symbol for s in raw
                if hasattr(s, "symbol") and str(s.symbol).endswith("_usdt")
            ]
        else:
            client = XTFuturesClient()
            raw = await client.get_symbols()
            symbols = [
                s.symbol for s in raw
                if hasattr(s, "symbol") and str(s.symbol).endswith("_usdt")
            ]
    except Exception as exc:
        print(red(f"✗ نشد نمادها رو بگیریم: {exc}"))
        # fallback: نمادهای معروف
        symbols = [
            "btc_usdt", "eth_usdt", "bnb_usdt", "sol_usdt", "xrp_usdt",
            "ada_usdt", "doge_usdt", "avax_usdt", "dot_usdt", "matic_usdt",
            "link_usdt", "ltc_usdt", "uni_usdt", "atom_usdt", "xlm_usdt",
            "trx_usdt", "etc_usdt", "near_usdt", "apt_usdt", "op_usdt",
        ]
        print(dim(f"از {len(symbols)} نماد پیش‌فرض استفاده می‌شه."))

    return symbols[:max_symbols]


async def _run_scan(strategy: str, interval: str, market: str, max_symbols: int) -> None:
    symbols = await _fetch_symbols(market, max_symbols)
    print(f"{yellow(f'⏳ اسکن {len(symbols)} نماد — استراتژی: {strategy} — تایم‌فریم: {interval}')}")
    print(dim("(ممکنه چند دقیقه طول بکشه...)\n"))

    scanner = MarketScanner(concurrency=5, lookback=200)
    try:
        scan_result = await scanner.scan(
            symbols=symbols,
            strategy_name=strategy,
            interval=interval,
            market=market,
        )
    except Exception as exc:
        print(red(f"\n✗ خطا در اسکن: {exc}"))
        return

    active = scan_result.with_signals()
    buy_results  = [r for r in active if r.buy_signals  > r.sell_signals]
    sell_results = [r for r in active if r.sell_signals >= r.buy_signals and r.sell_signals > 0]

    print(f"\n{bold('═' * 50)}")
    print(f"  {bold('نتایج اسکن بازار')}")
    print(f"  اسکن شد: {scan_result.scanned}  |  موفق: {scan_result.succeeded}  |  خطا: {scan_result.failed}")
    print(f"  سیگنال‌دار: {len(active)}  |  خرید: {green(str(len(buy_results)))}  |  فروش: {red(str(len(sell_results)))}")
    print(f"  زمان: {scan_result.elapsed_ms/1000:.1f} ثانیه")
    print(bold('═' * 50))

    if buy_results:
        print(f"\n  {bold(green('▲ سیگنال‌های خرید:'))}\n")
        for r in buy_results[:20]:
            latest = r.latest_signal.to_dict() if r.latest_signal else {}
            price  = latest.get("price", 0.0)
            print(f"  {green('●')} {cyan(r.symbol):<18}  سیگنال: {r.buy_signals}  قیمت: {yellow(f'{price:>14,.6f}')}")

    if sell_results:
        print(f"\n  {bold(red('▼ سیگنال‌های فروش:'))}\n")
        for r in sell_results[:20]:
            latest = r.latest_signal.to_dict() if r.latest_signal else {}
            price  = latest.get("price", 0.0)
            print(f"  {red('●')} {cyan(r.symbol):<18}  سیگنال: {r.sell_signals}  قیمت: {yellow(f'{price:>14,.6f}')}")

    if not active:
        print(f"\n  {yellow('⚠ هیچ نمادی سیگنال فعال نداشت')}\n")
    print()


# ─── منوی اصلی ──────────────────────────────────────────────────────────────

def main_menu() -> None:
    print(f"\n{bold(cyan('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'))}")
    print(f"  {bold('XT Exchange — سیگنال‌یاب')}")
    print(f"{bold(cyan('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'))}")
    print(f"\n  {green('1.')} سیگنال یک نماد")
    print(f"  {green('2.')} اسکن کل بازار (همه نمادها)")
    print(f"  {red('0.')} خروج\n")

    choice = _ask("انتخاب کن", "1")

    if choice == "1":
        symbol   = _ask("نماد (مثال: btc_usdt)", "btc_usdt")
        strategy = _choose("استراتژی", STRATEGIES, "rsi_reversal")
        interval = _choose("تایم‌فریم", INTERVALS, "1h")
        market   = _choose("بازار", ["spot", "futures"], "spot")
        lookback = int(_ask("تعداد کندل (max 1000)", "200"))
        asyncio.run(_run_signal(symbol, strategy, interval, market, min(lookback, 1000)))

    elif choice == "2":
        strategy    = _choose("استراتژی", STRATEGIES, "rsi_reversal")
        interval    = _choose("تایم‌فریم", INTERVALS, "1h")
        market      = _choose("بازار", ["spot", "futures"], "spot")
        max_symbols = int(_ask("حداکثر نماد برای اسکن (پیشنهاد: 30)", "30"))
        asyncio.run(_run_scan(strategy, interval, market, max_symbols))

    elif choice == "0":
        print("خداحافظ!")
        sys.exit(0)

    again = _ask("\nدوباره؟ (y/n)", "y")
    if again.lower() == "y":
        main_menu()


if __name__ == "__main__":
    main_menu()
