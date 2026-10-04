"""
The Plan tab's month grid: people down the side, months across, FTE in each cell.

Edits are *scratch*: they reprice the plan and write nothing until ``c``
commits them as dated rows (appended, never edited -- see
:mod:`budgie.core.plan`). ``s`` asks the solver (:mod:`budgie.core.solve`) to
fill the selected cells so the plan cost lands on the target; ``S`` spreads
the change evenly instead of in proportion. ``i`` seeds scratch edits from a
wide ``name,<month>,...`` sheet (:func:`budgie.core.solve.read_month_sheet`).

:class:`GridModel` is the UI-free part -- scratch edits, solving, the rows a
commit would append and the readout numbers -- so it can be tested without a
terminal. :class:`PlanGrid` is the Textual widget over it. It never writes a
file itself: a commit is posted as :class:`PlanGrid.Commit` and the app appends
the rows, the same way the Plan form does.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import DataTable, Input, Static

from budgie.core.eac import at_completion
from budgie.core.montecarlo import simulate
from budgie.core.plan import AllocationPlan, PlanEntry
from budgie.core.project import Snapshot
from budgie.core.solve import (
    Cell,
    PlanCosting,
    entries_for,
    read_month_sheet,
    solve,
)

#: Monte Carlo runs behind the readout's P50/P80. Fewer than the Forecast tab
#: so every keystroke stays instant; the Forecast tab has the full figures.
READOUT_RUNS = 2_000


def costing_for(snap: Snapshot) -> PlanCosting:
    """The solver's view of a project: its plan, rates, PTO, costs and spend.

    Months up to the latest spend reading are booked; with no readings the
    whole year is open.
    """
    # ponytail: one as_of for the team (the latest reading); per-person dates
    # if teams report on very different schedules.
    dated = [max(series)[0] for series in snap.readings.values() if series]
    as_of = max(dated) if dated else None
    return PlanCosting(
        plan=snap.plan or AllocationPlan(()),
        rates={p.name: p.hourly_cost for p in snap.people},
        span=snap.span,
        pto=snap.pto,
        pto_by_name=snap._allocation_pto(),
        non_labor=snap.non_labor,
        spent=snap.spent if as_of else {},
        as_of=as_of,
    )


def parse_money(text: str) -> float:
    """``"$1.2M"``, ``"850k"`` or ``"425,000"`` as a number of dollars."""
    match = re.fullmatch(r"\$?\s*([\d,]*\.?\d+)\s*([kKmM]?)", text.strip())
    if not match:
        raise ValueError(f"not an amount: {text!r} (try 425000, 850k or 1.2M)")
    scale = {"": 1, "k": 1e3, "m": 1e6}[match.group(2).lower()]
    return float(match.group(1).replace(",", "")) * scale


@dataclass
class GridModel:
    """Scratch edits over a project's plan, and what they cost."""

    snap: Snapshot
    target: float | None = None
    edits: dict[Cell, float] = field(default_factory=dict)

    @cached_property
    def base(self) -> PlanCosting:
        return costing_for(self.snap)

    @property
    def months(self) -> list[str]:
        """Column labels in the span's order (a fiscal year may start in Oct)."""
        return [calendar.month_abbr[m] for _, m in self.snap.span.months]

    @property
    def names(self) -> list[str]:
        """Everyone with a rate, then anyone only the plan (or an edit) names."""
        names = dict.fromkeys(p.name for p in self.snap.people)
        names.update(dict.fromkeys(self.base.plan.names))
        names.update(dict.fromkeys(n for n, _ in self.edits))
        return list(names)

    def rows(self) -> list[PlanEntry]:
        """The plan rows a commit appends."""
        return entries_for(self.base, self.edits)

    @property
    def plan(self) -> AllocationPlan:
        """The plan with the scratch edits applied."""
        return AllocationPlan((*self.base.plan.entries, *self.rows()))

    @property
    def scratch(self) -> PlanCosting:
        return self.base.with_plan(self.plan)

    def set(self, cells, fte: float) -> None:
        if not 0 <= fte <= 1:
            raise ValueError(f"FTE runs 0 to 1, got {fte:g}")
        booked = sorted({m for _, m in cells if not self.base.editable(m)})
        if booked:
            raise ValueError(
                f"{', '.join(self.months[m - 1] for m in booked)} already booked"
            )
        self.edits.update(dict.fromkeys(cells, fte))

    def seed(self, path: str | Path) -> str:
        """Scratch edits from a month sheet; returns what happened, in words.

        Cells in booked months are left as they are, and a name with no rate
        in people.csv is seeded but not costed, as anywhere else in the plan.
        """
        cells = read_month_sheet(path, self.snap.span)
        open_ = {c: v for c, v in cells.items() if self.base.editable(c[1])}
        self.edits.update(open_)
        said = f"Seeded {len(open_)} cell(s) from {Path(path).name}"
        if booked := len(cells) - len(open_):
            said += f"; {booked} in booked months left as they are"
        if unknown := sorted({n for n, _ in open_} - set(self.base.rates)):
            said += f"; not costed (not in people.csv): {', '.join(unknown)}"
        return said + "."

    def solve(self, cells, mode: str = "proportional") -> str:
        """Fill ``cells`` to hit the target; returns what happened, in words."""
        if self.target is None:
            raise ValueError("No target: press t to set one (there is no budget)")
        sol = solve(self.scratch, cells, self.target, mode=mode)
        self.edits.update(sol.fte)
        said = f"Solved {len(sol.fte)} cells ({mode})"
        if abs(sol.gap) >= 0.5:
            said += (
                f"; {_signed(sol.gap)} still to close -- the 0-1 FTE limit stopped it"
            )
        return f"{said}. {sol.note}".strip()

    def readout(self) -> dict[str, float | None]:
        """Plan cost, target, gap, and the P50/P80 of the scratch plan."""
        cost = self.scratch.cost()
        snap = self.snap.with_plan(self.plan)
        people = snap.people
        if snap.readings:
            people = at_completion(
                people, snap.readings, snap.span, plan=snap.plan
            ).people
        pct = simulate(
            people, iterations=READOUT_RUNS, seed=snap.seed, costs=snap.costs
        ).percentiles((50, 80))
        gap = None if self.target is None else self.target - cost
        return {
            "cost": cost,
            "target": self.target,
            "gap": gap,
            "p50": pct[50],
            "p80": pct[80],
        }


def _money(x: float) -> str:
    return f"${x:,.0f}"


def _signed(x: float) -> str:
    return f"{'+' if x >= 0 else '−'}{_money(abs(x))}"


class PlanGrid(Vertical):
    """People × months of FTE, with scratch edits and a cost solver."""

    DEFAULT_CSS = """
    PlanGrid { height: 1fr; }
    PlanGrid #grid_readout { height: auto; padding: 0 2; }
    PlanGrid #grid_table { height: 1fr; }
    PlanGrid #grid_input { height: 1; border: none; margin: 0 2; }
    PlanGrid #grid_status { height: auto; padding: 0 2; color: $success; }
    PlanGrid #grid_status.error { color: $error; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("space", "toggle_cell", "Select"),
        Binding("shift+right", "extend(0, 1)", show=False),
        Binding("shift+left", "extend(0, -1)", show=False),
        Binding("shift+down", "extend(1, 0)", show=False),
        Binding("shift+up", "extend(-1, 0)", show=False),
        Binding("s", "solve('proportional')", "Solve"),
        Binding("S", "solve('even')", "Solve even"),
        Binding("t", "ask('target')", "Target"),
        Binding("i", "ask('sheet')", "Import"),
        Binding("c", "commit", "Commit"),
        Binding("x", "discard", "Discard"),
        Binding("escape", "close_input", show=False),
    ]

    class Commit(Message):
        """The scratch edits as plan rows, for the app to append."""

        def __init__(self, rows: list[PlanEntry]) -> None:
            self.rows = rows
            super().__init__()

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.model: GridModel | None = None
        self.selected: set[Cell] = set()
        self._asking: str | None = None  # "cell", "target" or "sheet" while asking
        self._target: float | None = None  # a typed target outlives a reload

    def compose(self) -> ComposeResult:
        yield Static(id="grid_readout")
        yield DataTable(id="grid_table", cursor_type="cell", zebra_stripes=True)
        yield Input(id="grid_input")
        yield Static(id="grid_status")

    def on_mount(self) -> None:
        self.query_one("#grid_input", Input).display = False

    # -- loading -----------------------------------------------------------

    def load(self, snap: Snapshot | None) -> None:
        """Start over on ``snap`` (None: no project); scratch edits are dropped."""
        self.selected.clear()
        if snap is None:
            self.model = None
            self.query_one("#grid_table", DataTable).clear(columns=True)
            self.query_one("#grid_readout", Static).update(
                "[dim]Open a project (with a people.csv) to plan in the grid.[/dim]"
            )
            return
        budget = snap.budget.latest if snap.budget else None
        self.model = GridModel(snap, target=self._target or budget)
        self._redraw()

    # -- drawing -----------------------------------------------------------

    def _redraw(self) -> None:
        model = self.model
        table = self.query_one("#grid_table", DataTable)
        cursor = table.cursor_coordinate
        table.clear(columns=True)
        table.add_column("Name", key="name")
        for m, label in enumerate(model.months, 1):
            table.add_column(label if model.base.editable(m) else f"[dim]{label}[/dim]")
        scratch = model.scratch
        for name in model.names:
            cells = [name]
            for m, fte in enumerate(scratch.grid(name), 1):
                text = f"{fte:.2f}"
                if (name, m) in model.edits:
                    text = f"[b yellow]{text}[/b yellow]"
                elif not model.base.editable(m):
                    text = f"[dim]{text}[/dim]"
                if (name, m) in self.selected:
                    text = f"[reverse]{text}[/reverse]"
                cells.append(text)
            table.add_row(*cells)
        if table.row_count:
            table.move_cursor(
                row=min(cursor.row, table.row_count - 1), column=max(cursor.column, 1)
            )
        self._readout()

    def _readout(self) -> None:
        r = self.model.readout()
        parts = [f"plan cost [b]{_money(r['cost'])}[/b]"]
        if r["target"] is None:
            parts.append("[dim]no target (t sets one)[/dim]")
        else:
            parts += [f"target {_money(r['target'])}", f"gap {_signed(r['gap'])}"]
        parts += [f"P50 {_money(r['p50'])}", f"P80 {_money(r['p80'])}"]
        line = "   ·   ".join(parts)
        if self.model.edits:
            line += (
                f"\n[yellow]{len(self.model.edits)} unsaved cell(s)[/yellow]"
                "  [dim]c commits as plan rows, x discards[/dim]"
            )
        self.query_one("#grid_readout", Static).update(line)

    def say(self, message: str, error: bool = False) -> str:
        status = self.query_one("#grid_status", Static)
        status.set_class(error, "error")
        status.update(message)
        return message

    # -- which cells -------------------------------------------------------

    def _cursor_cell(self) -> Cell | None:
        coord = self.query_one("#grid_table", DataTable).cursor_coordinate
        if (
            self.model is None
            or coord.column == 0
            or coord.row >= len(self.model.names)
        ):
            return None
        return (self.model.names[coord.row], coord.column)

    def _targets(self) -> set[Cell]:
        """The selection, else the cell under the cursor."""
        if self.selected:
            return set(self.selected)
        cell = self._cursor_cell()
        return {cell} if cell else set()

    # -- actions -----------------------------------------------------------

    def action_toggle_cell(self) -> None:
        cell = self._cursor_cell()
        if cell:
            self.selected ^= {cell}
            self._redraw()

    def action_extend(self, rows: int, cols: int) -> None:
        table = self.query_one("#grid_table", DataTable)
        if (cell := self._cursor_cell()) is None:
            return
        self.selected.add(cell)
        coord = table.cursor_coordinate
        table.move_cursor(row=coord.row + rows, column=max(coord.column + cols, 1))
        if (cell := self._cursor_cell()) is not None:
            self.selected.add(cell)
        self._redraw()

    def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        # Enter on a cell: type its new FTE (applied to the whole selection).
        event.stop()
        if self._targets():
            cell = self._cursor_cell()
            current = self.model.scratch.grid(cell[0])[cell[1] - 1] if cell else 0
            self.action_ask("cell", f"{current:.2f}")

    def action_ask(self, what: str, value: str = "") -> None:
        if self.model is None:
            return
        if what == "target" and self.model.target is not None:
            value = f"{self.model.target:,.0f}"
        box = self.query_one("#grid_input", Input)
        first, *_, last = self.model.months
        box.placeholder = {
            "cell": "FTE 0-1 for the selected cells, enter to apply",
            "target": "Target cost, e.g. 425000 or 1.2M, enter to set",
            "sheet": f"Path to a name,{first},...,{last} FTE sheet, enter to load",
        }[what]
        box.value = value
        box.display = True
        self._asking = what
        box.focus()

    def action_close_input(self) -> None:
        box = self.query_one("#grid_input", Input)
        if box.display:
            box.display = False
            self._asking = None
            self.query_one("#grid_table", DataTable).focus()

    def _sheet_path(self, typed: str) -> Path:
        """A typed sheet path; a relative one is the project's, not the launch dir's."""
        path = Path(typed.strip()).expanduser()
        workspace = getattr(self.app, "workspace", None)
        if path.is_absolute() or workspace is None:
            return path
        return workspace.root / path

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "grid_input":
            return
        event.stop()
        what = self._asking
        try:
            if what == "target":
                self.model.target = self._target = parse_money(event.value)
                self.say(f"Target set to {_money(self.model.target)}.")
            elif what == "cell":
                cells = self._targets()
                self.model.set(cells, float(event.value))
                self.say(f"Set {len(cells)} cell(s) to {float(event.value):g}.")
            elif what == "sheet":
                self.say(self.model.seed(self._sheet_path(event.value)))
        except (ValueError, OSError) as exc:
            self.say(str(exc), error=True)
            return
        self.action_close_input()
        self._redraw()

    def action_solve(self, mode: str) -> str:
        if self.model is None:
            return ""
        cells = self._targets()
        if not cells:
            return self.say("Put the cursor on a month (or select some) first.", True)
        try:
            message = self.model.solve(cells, mode)
        except ValueError as exc:
            return self.say(str(exc), error=True)
        self._redraw()
        return self.say(message)

    def action_commit(self) -> None:
        if self.model is None or not self.model.edits:
            self.say("Nothing to commit.")
            return
        self.post_message(self.Commit(self.model.rows()))

    def action_discard(self) -> None:
        if self.model and self.model.edits:
            self.model.edits.clear()
            self.selected.clear()
            self._redraw()
            self.say("Scratch edits discarded.")
