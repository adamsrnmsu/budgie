"""
Budgie Textual TUI.

An interactive front-end over ``budgie.core``, organised around the project
workspace rather than a single CSV:

    Forecast     assumptions in, cost + Monte Carlo out, recomputed live
    Plan         the allocation plan, with re-planning as an appended row
    Inputs       every project file, whether it exists, and open-in-$EDITOR
    Assumptions  what the engine assumes, so it isn't folklore

Like every other front-end this file contains no budgeting math -- it wires
widgets to the engine. The one thing it *writes* is a plan row, and it appends
rather than edits, because that is what :mod:`budgie.core.plan` models: history
is a record, not mutable current state.
"""

from __future__ import annotations

import os
import subprocess
from datetime import date
from pathlib import Path
from typing import ClassVar

import numpy as np
from textual.app import App, ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Static,
    TabbedContent,
    TabPane,
)

from budgie.core.calendar import PTO_RULE, explain_pto, productive_hours
from budgie.core.csvio import parse_date
from budgie.core.forecast import forecast as run_forecast
from budgie.core.loader import load_people
from budgie.core.montecarlo import simulate
from budgie.core.plan import load_plan
from budgie.core.workspace import INPUTS, Workspace, find_workspace

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


def open_in_editor(path: Path) -> str:
    """Open ``path`` in the user's editor, returning a status message.

    Uses ``$VISUAL``/``$EDITOR`` when set. This is the "links to the inputs"
    half of the Inputs tab -- seeing that a file exists doesn't help if you
    then have to go hunting for it in another window.
    """
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not editor:
        return f"Set $EDITOR to open files from here. Path: {path}"
    if not path.exists():
        return f"{path.name} doesn't exist yet."
    try:
        subprocess.run([*editor.split(), str(path)], check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        return f"Could not open {path.name} with {editor!r}: {exc}"
    return f"Edited {path.name}."


def append_plan_row(plan_path: Path, name: str, effective: date, fte: float) -> None:
    """Append one allocation change to the plan CSV.

    Appending, never editing: a re-plan is a new dated row, so the record of
    what changed and when survives. Creates the file with a header if needed.
    """
    if not plan_path.exists():
        plan_path.write_text("name,effective_date,fte\n")
    existing = plan_path.read_text()
    # Guard against a file whose last line has no newline.
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    with plan_path.open("a") as handle:
        handle.write(f"{prefix}{name},{effective:%Y-%m-%d},{fte:g}\n")


class BudgieTUI(App):
    """Interactive explorer over a Budgie project."""

    CSS = """
    #assumptions_bar { height: auto; padding: 1; background: $panel; }
    #assumptions_bar Input { width: 12; }
    #assumptions_bar Label { padding: 1 1 0 2; }
    #forecast_body { height: 1fr; }
    #table_pane { width: 3fr; padding: 1; }
    #mc_pane { width: 2fr; padding: 1; background: $panel; }
    .pct { text-style: bold; }
    #hist { color: $success; height: auto; }
    #plan_form { height: auto; padding: 1; background: $panel; }
    #plan_form Input { width: 16; }
    #plan_form Label { padding: 1 1 0 2; }
    .note { padding: 1 2; color: $text-muted; }
    .status { padding: 0 2; color: $success; }
    #inputs_hint { padding: 1 2; color: $text-muted; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        ("r", "recalculate", "Recalculate"),
        ("e", "edit_selected", "Edit input"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, csv_path: str | Path | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.workspace: Workspace | None = find_workspace()
        # An explicit path still wins, exactly like on the command line.
        self._people_override = str(csv_path) if csv_path else None

    # -- paths -------------------------------------------------------------

    @property
    def people_path(self) -> str:
        if self._people_override:
            return self._people_override
        if self.workspace:
            resolved = self.workspace.resolve("people")
            if resolved:
                return resolved
        return str(Path(__file__).parent / "tests" / "team.csv")

    @property
    def plan_path(self) -> Path | None:
        return self.workspace.path_for("plan") if self.workspace else None

    # -- layout ------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="tab_forecast"):
            with TabPane("Forecast", id="tab_forecast"):
                yield from self._compose_forecast()
            with TabPane("Plan", id="tab_plan"):
                yield from self._compose_plan()
            with TabPane("Inputs", id="tab_inputs"):
                yield from self._compose_inputs()
            with TabPane("Assumptions", id="tab_assumptions"):
                yield VerticalScroll(Static(id="assumptions_text"))
        yield Footer()

    def _compose_forecast(self) -> ComposeResult:
        with Horizontal(id="assumptions_bar"):
            yield Label("Year")
            yield Input(
                value=str(self._setting("year", 2026)), id="year", type="integer"
            )
            yield Label("PTO days")
            yield Input(value=str(self._setting("pto", 0)), id="pto", type="number")
            yield Label("Iterations")
            yield Input(
                value=str(self._setting("iterations", 10_000)),
                id="iterations",
                type="integer",
            )
            yield Label("Seed")
            yield Input(value=str(self._setting("seed", 42)), id="seed", type="integer")
            yield Button("Recalculate", id="recalc", variant="primary")
        with Horizontal(id="forecast_body"):
            with Vertical(id="table_pane"):
                yield DataTable(id="forecast")
            with Vertical(id="mc_pane"):
                yield Label("Monte Carlo", classes="pct")
                yield Static(id="mc_summary")
                yield Static(id="hist")
                yield Static(id="mc_stats")

    def _compose_plan(self) -> ComposeResult:
        yield Static(
            "Re-planning appends a dated row -- it never edits history. "
            "Add a row below to move someone's FTE from a date onward; "
            "0 FTE takes them off the project.",
            classes="note",
        )
        with Horizontal(id="plan_form"):
            yield Label("Name")
            yield Input(placeholder="Alice", id="plan_name")
            yield Label("From")
            yield Input(placeholder="2026-09-01", id="plan_date")
            yield Label("FTE")
            yield Input(placeholder="0.5", id="plan_fte", type="number")
            yield Button("Add row", id="add_plan_row", variant="primary")
        yield Static(id="plan_status", classes="status")
        yield DataTable(id="plan_table")

    def _compose_inputs(self) -> ComposeResult:
        yield Static(
            "Select a row and press [b]e[/b] to open it in $EDITOR, "
            "then [b]r[/b] to recalculate.",
            id="inputs_hint",
        )
        yield DataTable(id="inputs_table")
        yield Static(id="inputs_status", classes="status")

    # -- lifecycle ---------------------------------------------------------

    def on_mount(self) -> None:
        self.title = "Budgie"
        self.sub_title = str(self.workspace.root) if self.workspace else "no project"

        forecast_table = self.query_one("#forecast", DataTable)
        forecast_table.add_columns("Name", "$/hr", "Hours", "Cost")
        forecast_table.zebra_stripes = True

        plan_table = self.query_one("#plan_table", DataTable)
        plan_table.add_columns("Name", "Changes", "Allocated hours")
        plan_table.zebra_stripes = True

        inputs_table = self.query_one("#inputs_table", DataTable)
        inputs_table.add_columns("", "File", "Rows", "What it is", "Used by")
        inputs_table.cursor_type = "row"
        inputs_table.zebra_stripes = True

        self.recalculate()

    def _setting(self, key: str, default):
        if self.workspace:
            return self.workspace.setting(key, default)
        return default

    # -- events ------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "recalc":
            self.recalculate()
        elif event.button.id == "add_plan_row":
            self.add_plan_row()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id and event.input.id.startswith("plan_"):
            self.add_plan_row()
        else:
            self.recalculate()

    def action_recalculate(self) -> None:
        self.recalculate()

    def action_edit_selected(self) -> None:
        """Open the highlighted input file in $EDITOR."""
        table = self.query_one("#inputs_table", DataTable)
        status = self.query_one("#inputs_status", Static)
        if self.workspace is None:
            status.update("No project here -- run `budgie init` to create one.")
            return
        items = self.workspace.inputs()
        row = table.cursor_row
        if not 0 <= row < len(items):
            status.update("Select a file on the Inputs tab first.")
            return
        with self.suspend():
            message = open_in_editor(items[row].path)
        status.update(message)
        self.recalculate()

    # -- reading the form --------------------------------------------------

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

    # -- actions -----------------------------------------------------------

    def add_plan_row(self) -> str:
        """Append the form's row to the plan CSV and refresh the plan table.

        Returns the status message it displayed, so the outcome is observable
        without reaching into the widget.
        """
        path = self.plan_path
        if path is None:
            return self._plan_status("No project here -- run `budgie init` first.")

        name = self.query_one("#plan_name", Input).value.strip()
        raw_date = self.query_one("#plan_date", Input).value.strip()
        raw_fte = self.query_one("#plan_fte", Input).value.strip()
        if not (name and raw_date and raw_fte):
            return self._plan_status("Name, from-date and FTE are all needed.")

        try:
            effective = parse_date(raw_date)
            fte = float(raw_fte)
        except ValueError as exc:
            return self._plan_status(str(exc))
        if fte < 0:
            return self._plan_status("FTE cannot be negative.")

        append_plan_row(path, name, effective, fte)
        # Clear the form so the same row can't be added twice by a stray Enter.
        for widget_id in ("plan_name", "plan_date", "plan_fte"):
            self.query_one(f"#{widget_id}", Input).value = ""
        self.recalculate()
        return self._plan_status(
            f"Added {name} → {fte:g} FTE from {effective} ({path.name})"
        )

    def _plan_status(self, message: str) -> str:
        self.query_one("#plan_status", Static).update(message)
        return message

    def recalculate(self) -> None:
        year = self._read_int("year", 2026)
        pto = self._read_float("pto", 0.0)
        iterations = max(self._read_int("iterations", 10_000), 100)
        seed = self._read_int("seed", 42)

        ph = productive_hours(year, pto_days=pto)
        self._refresh_forecast(ph, year, pto, iterations, seed)
        self._refresh_plan(year, pto)
        self._refresh_inputs()
        self._refresh_assumptions(ph, year)

    # -- rendering ---------------------------------------------------------

    def _refresh_forecast(self, ph, year, pto, iterations, seed) -> None:
        people = load_people(self.people_path, productive_hours=ph)
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
            f"\n\n[dim]people: {self.people_path}[/dim]"
        )

    def _refresh_plan(self, year: int, pto: float) -> None:
        table = self.query_one("#plan_table", DataTable)
        table.clear()
        path = self.plan_path
        if path is None or not path.exists():
            table.add_row("[dim]no plan.csv in this project[/dim]", "", "")
            return

        plan = load_plan(path)
        total = 0.0
        for name in plan.names:
            hours = plan.allocated_hours(name, year, pto_days=pto)
            total += hours
            changes = ", ".join(
                f"{e.effective_date:%b %-d}→{e.fte:g}" for e in plan.changes_for(name)
            )
            table.add_row(name, changes, f"{hours:,.0f}")
        table.add_row("[b]Total[/b]", "", f"[b]{total:,.0f}[/b]")

    def _refresh_inputs(self) -> None:
        table = self.query_one("#inputs_table", DataTable)
        table.clear()
        if self.workspace is None:
            table.add_row(
                "", "[dim]no budgie.yaml[/dim]", "", "Run `budgie init` to start", ""
            )
            return
        for item in self.workspace.inputs():
            table.add_row(
                "[green]✓[/green]" if item.exists else "[dim]·[/dim]",
                item.path.name if item.exists else f"[dim]{item.path.name}[/dim]",
                "" if item.rows is None else str(item.rows),
                item.description,
                " ".join(item.used_by),
            )

    def _refresh_assumptions(self, ph, year: int) -> None:
        lines = [
            f"[b]Assumptions in force for {year}[/b]\n",
            f"Gross hours          {ph.gross_hours:,.0f}  (40 h x 52 weeks)",
            f"Federal holidays    -{ph.holiday_hours:,.0f}",
            f"Productive hours     {ph.productive_hours:,.0f}",
            f"PTO                 -{ph.pto_hours:,.0f}  ({ph.pto_days:g} days)",
            f"Available hours      {ph.available_hours:,.0f}  (1.0 FTE)\n",
            f"[b]PTO and part-time[/b]\n{PTO_RULE}\n",
            f"  {explain_pto(ph)}\n",
            "[b]Uncertainty[/b]",
            "  Hours are a triangular low/mode/high draw; the table above uses",
            "  the mode. The Monte Carlo redraws every person each iteration.\n",
            "[b]Inputs[/b]",
            *(
                f"  {default:<16} {description}"
                for default, description, _used in INPUTS.values()
            ),
        ]
        self.query_one("#assumptions_text", Static).update("\n".join(lines))


def run(csv_path: str | Path | None = None) -> None:
    BudgieTUI(csv_path).run()
