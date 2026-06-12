"""
Rich terminal dashboard — live table that refreshes every N seconds.
"""

import asyncio
import time
from typing import List

from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich import box
from rich.text import Text

import config
from signals import SignalResult

console = Console()


def _color_direction(direction: str) -> str:
    if direction == "LONG":
        return "bold green"
    if direction == "SHORT":
        return "bold red"
    return "dim"


def _color_score(score: float) -> str:
    if score >= 80:
        return "bold magenta"
    if score >= 60:
        return "green"
    if score <= 40:
        return "red"
    return "yellow"


def _color_obi(ratio: float) -> str:
    if ratio >= config.OBI_LONG_THRESHOLD:
        return "green"
    if ratio <= config.OBI_SHORT_THRESHOLD:
        return "red"
    return "white"


def _cvd_arrow(cvd: float) -> str:
    if cvd > 0:
        return f"[green]+{cvd:,.2f}[/green]"
    if cvd < 0:
        return f"[red]{cvd:,.2f}[/red]"
    return f"[dim]{cvd:,.2f}[/dim]"


def build_table(results: List[SignalResult], elapsed: float) -> Table:
    table = Table(
        title=f"[bold cyan]XT.com Scalping Scanner[/bold cyan]  "
              f"[dim]— refreshed {time.strftime('%H:%M:%S')} | "
              f"uptime {int(elapsed)}s[/dim]",
        box=box.SIMPLE_HEAVY,
        border_style="cyan",
        header_style="bold white on dark_blue",
        show_lines=False,
        expand=True,
    )

    table.add_column("Rank", justify="right", style="dim", width=5)
    table.add_column("Symbol", style="bold white", min_width=14)
    table.add_column("Price (USDT)", justify="right", min_width=14)
    table.add_column("CVD", justify="right", min_width=14)
    table.add_column("OBI Ratio", justify="right", width=10)
    table.add_column("Sweep", justify="center", width=8)
    table.add_column("Score", justify="right", width=8)
    table.add_column("Direction", justify="center", width=10)

    for rank, r in enumerate(results, 1):
        # Format price with appropriate precision
        if r.price >= 1:
            price_str = f"{r.price:,.4f}"
        elif r.price >= 0.01:
            price_str = f"{r.price:.6f}"
        else:
            price_str = f"{r.price:.8f}"

        sweep_icon = {1.0: "[green]▲ BULL[/green]", 0.0: "[red]▼ BEAR[/red]"}.get(
            r.sweep_signal, "[dim]  —  [/dim]"
        )

        score_text = Text(f"{r.score:.1f}%", style=_color_score(r.score))
        dir_text = Text(r.direction, style=_color_direction(r.direction))
        obi_text = Text(f"{r.obi_ratio:.3f}", style=_color_obi(r.obi_ratio))

        # Highlight rows with high-confidence signals
        row_style = "on grey7" if r.score >= config.SCORE_ALERT_THRESHOLD else ""

        table.add_row(
            str(rank),
            r.symbol.upper(),
            price_str,
            _cvd_arrow(r.cvd),
            obi_text,
            sweep_icon,
            score_text,
            dir_text,
            style=row_style,
        )

    return table


async def run_dashboard(
    get_results,          # callable → List[SignalResult]
    stop_event: asyncio.Event,
    start_time: float,
) -> None:
    """
    Render a live Rich table.
    `get_results` is called each refresh to obtain the latest signal list.
    """
    with Live(console=console, refresh_per_second=1, screen=False) as live:
        while not stop_event.is_set():
            results = get_results()
            elapsed = time.time() - start_time
            live.update(build_table(results, elapsed))
            await asyncio.sleep(config.DASHBOARD_REFRESH_SEC)
