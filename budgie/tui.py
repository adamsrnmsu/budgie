"""
Budgie Textual TUI.

An interactive front-end over ``budgie.core``: edit the planning assumptions
(year, PTO, Monte Carlo iterations, seed) and the deterministic forecast and the
Monte Carlo distribution recompute live. Like every other front-end, this file
contains no budgeting math -- it only wires widgets to the engine.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import numpy as np
from textual.app import App, ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Static

from budgie.core.calendar import productive_hours
from budgie.core.forecast import forecast as run_forecast
from budgie.core.loader import load_people
from budgie.core.montecarlo import simulate

_BLOCKS = " ▁▂▃▄▅▆▇█"


def ascii_histogram(values: np.ndarray, bins: int = 42, height: int = 8) -> str:
    """Render a compact vertical block histogram of ``values`` as text."""
    counts, _ = np.histogram(values, bins=bins)
    peak = counts.max() or 1
    # Each column is `height` block-rows tall; fill from the bottom up.
    scaled = counts / peak * height
    rows = []
    for row in range(height, 0, -1):
        line = []
        for col in scaled:
            filled = col - (row - 1)
            if filled >= 1:
                line.append(_BLOCKS[-1])
            elif filled <= 0:
                line.append(" ")
            else:
                line.append(_BLOCKS[int(filled * (len(_BLOCKS) - 1))])
        rows.append("".join(line))
    return "\n".join(rows)


def _money(x: float) -> str:
    return f"${x:,.0f}"


class BudgieTUI(App):
    """Interactive forecast + Monte Carlo explorer."""

    CSS = """
    #assumptions { height: auto; padding: 1; background: $panel; }
    #assumptions Input { width: 12; }
    #assumptions Label { padding: 1 1 0 2; }
    #body { height: 1fr; }
    #table_pane { width: 3fr; padding: 1; }
    #mc_pane { width: 2fr; padding: 1; background: $panel; }
    .pct { text-style: bold; }
    #hist { color: $success; height: auto; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        ("r", "recalculate", "Recalculate"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, csv_path: str | Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self.csv_path = str(csv_path)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="assumptions"):
            yield Label("Year")
            yield Input(value="2026", id="year", type="integer")
            yield Label("PTO days")
            yield Input(value="0", id="pto", type="number")
            yield Label("Iterations")
            yield Input(value="10000", id="iterations", type="integer")
            yield Label("Seed")
            yield Input(value="42", id="seed", type="integer")
            yield Button("Recalculate", id="recalc", variant="primary")
        with Horizontal(id="body"):
            with Vertical(id="table_pane"):
                yield DataTable(id="forecast")
            with Vertical(id="mc_pane"):
                yield Label("Monte Carlo", classes="pct")
                yield Static(id="mc_summary")
                yield Static(id="hist")
                yield Static(id="mc_stats")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#forecast", DataTable)
        table.add_columns("Name", "$/hr", "Hours", "Cost")
        table.zebra_stripes = True
        self.recalculate()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "recalc":
            self.recalculate()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.recalculate()

    def _read_int(self, widget_id: str, default: int) -> int:
        try:
            return int(self.query_one(f"#{widget_id}", Input).value)
        except (ValueError, TypeError):
            return default

    def _read_float(self, widget_id: str, default: float) -> float:
        try:
            return float(self.query_one(f"#{widget_id}", Input).value)
        except (ValueError, TypeError):
            return default

    def action_recalculate(self) -> None:
        self.recalculate()

    def recalculate(self) -> None:
        year = self._read_int("year", 2026)
        pto = self._read_float("pto", 0.0)
        iterations = max(self._read_int("iterations", 10_000), 100)
        seed = self._read_int("seed", 42)

        ph = productive_hours(year, pto_days=pto)
        people = load_people(self.csv_path, productive_hours=ph.available_hours)
        det = run_forecast(people)
        sim = simulate(people, iterations=iterations, seed=seed)
        pct = sim.percentiles()

        table = self.query_one("#forecast", DataTable)
        table.clear()
        for item in det.line_items:
            table.add_row(
                item.name,
                _money(item.hourly_cost),
                f"{item.hours:,.0f}",
                _money(item.cost),
            )
        table.add_row(
            "[b]Total[/b]",
            "",
            f"[b]{det.total_hours:,.0f}[/b]",
            f"[b]{_money(det.total_cost)}[/b]",
        )

        self.query_one("#mc_summary", Static).update(
            f"Productive hrs {year}: [b]{ph.productive_hours:,.0f}[/b]"
            + (f"  |  available: [b]{ph.available_hours:,.0f}[/b]" if pto else "")
            + f"\n\n[b green]P10[/b green] {_money(pct[10])}    "
            f"[b]P50[/b] {_money(pct[50])}    "
            f"[b green]P90[/b green] {_money(pct[90])}"
        )
        self.query_one("#hist", Static).update(ascii_histogram(sim.total_costs))
        self.query_one("#mc_stats", Static).update(
            f"{sim.iterations:,} sims   mean {_money(sim.mean)}   std {_money(sim.std)}"
        )


def run(csv_path: str | Path) -> None:
    BudgieTUI(csv_path).run()
