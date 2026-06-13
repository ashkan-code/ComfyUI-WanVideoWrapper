"""CLI سریع برای دریافت سیگنال از XT Exchange — بدون نیاز به Claude Code."""

from __future__ import annotations

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from signals.engine import SignalEngine


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


def green(t): return _color(t, "92")
def red(t):   return _color(t, "91")
def yellow(t): return _color(t, "93")
def bold(t):  return _color(t, "1")
def cyan(t):  return _color(t, "96")


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


async def _run(symbol: str, strategy: str, interval: str, market: str, lookback: int) -> None:
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
        return

    last_close = df["close"].iloc[-1] if not df.empty else 0.0
    print(f"\n{bold('═' * 44)}")
    print(f"  {bold('نماد:')}    {cyan(symbol.upper())}")
    print(f"  {bold('استراتژی:')} {strategy}")
    print(f"  {bold('تایم‌فریم:')} {interval}  |  بازار: {market}")
    print(f"  {bold('قیمت فعلی:')} {yellow(f'{last_close:,.4f}')}")
    print(f"  {bold('کندل‌ها:')}  {len(df)} عدد")
    print(bold('═' * 44))

    if not signals:
        print(f"\n  {yellow('⚠ سیگنالی یافت نشد')}\n")
        return

    print(f"\n  {bold('آخرین سیگنال‌ها')} ({len(signals)} عدد کل):\n")
    for sig in signals[-10:]:
        d = sig.to_dict()
        sig_type = d.get("signal_type", "?")
        price    = d.get("price", 0.0)
        ts       = d.get("timestamp", 0)
        color    = green if "BUY" in str(sig_type) else red
        icon     = "▲" if "BUY" in str(sig_type) else "▼"
        print(f"  {color(f'{icon} {sig_type:<10}')}  قیمت: {yellow(f'{price:>12,.4f}')}  زمان: {ts}")

    last = signals[-1].to_dict()
    last_type = last.get("signal_type", "")
    print()
    if "BUY" in str(last_type):
        print(f"  {bold(green('✔ آخرین سیگنال: خرید (BUY)'))}")
    elif "SELL" in str(last_type):
        print(f"  {bold(red('✔ آخرین سیگنال: فروش (SELL)'))}")
    print()


def main() -> None:
    print(f"\n{bold(cyan('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'))}")
    print(f"  {bold('XT Exchange — سیگنال‌یاب')}")
    print(f"{bold(cyan('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'))}\n")

    symbol   = _ask("نماد (مثال: btc_usdt)", "btc_usdt")
    strategy = _choose("استراتژی", STRATEGIES, "rsi_reversal")
    interval = _choose("تایم‌فریم", INTERVALS, "1h")
    market   = _choose("بازار", ["spot", "futures"], "spot")
    lookback = int(_ask("تعداد کندل (max 1000)", "200"))

    asyncio.run(_run(symbol, strategy, interval, market, min(lookback, 1000)))

    again = _ask("\nنماد دیگه‌ای بررسی کنی؟ (y/n)", "n")
    if again.lower() == "y":
        main()


if __name__ == "__main__":
    main()
