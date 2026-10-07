"""
The Plan tab's month grid: people down the side, months across, FTE in each cell.

Edits are *scratch*: they reprice the plan and write nothing until ``s``
(or ``c``) saves them as dated rows (appended, never edited -- see
:mod:`budgie.core.plan`); ``x`` discards them. ``v`` asks the solver
(:mod:`budgie.core.solve`) to scale the selected cells so the plan cost lands
on the ``t`` target; ``V`` adds the same FTE to each instead of scaling in
proportion. ``i`` seeds scratch edits from a
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
from textual.widgets import DataTable, Input, Static, TabbedContent, Tabs

from budgie.core.booked import (
    completed_months,
    full_time_month_hours,
    full_time_week_hours,
    trailing_hours,
)
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


def parse_fte(text: str) -> float:
    """``"0.5"``, ``"50"`` or ``"50%"`` as an FTE; above 1 reads as a percent."""
    raw = text.strip()
    try:
        x = float(raw.rstrip("%"))
    except ValueError:
        raise ValueError(f"not a percentage: {text!r} (try 50 or 0.5)") from None
    return x / 100 if raw.endswith("%") or x > 1 else x


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
    undone: list[dict[Cell, float]] = field(default_factory=list)
    redone: list[dict[Cell, float]] = field(default_factory=list)

    def checkpoint(self) -> None:
        """Remember the edits before a change, so ``undo`` can bring them back."""
        self.undone.append(dict(self.edits))
        self.redone.clear()

    def undo(self) -> bool:
        if not self.undone:
            return False
        self.redone.append(dict(self.edits))
        self.edits = self.undone.pop()
        return True

    def redo(self) -> bool:
        if not self.redone:
            return False
        self.undone.append(dict(self.edits))
        self.edits = self.redone.pop()
        return True

    def current(self, cell: Cell) -> float:
        return self.scratch.grid(cell[0])[cell[1] - 1]

    def nudge(self, cells, delta: float) -> int:
        """Move each cell by ``delta`` FTE (clamped to 0-1); the number that moved.

        A cell already at the limit is left alone, so it adds no edit and no undo step.
        """
        self._check_open(cells)
        new = {c: round(min(1.0, max(0.0, self.current(c) + delta)), 4) for c in cells}
        new = {c: v for c, v in new.items() if v != self.current(c)}
        if new:
            self.checkpoint()
            self.edits.update(new)
        return len(new)

    def _check_open(self, cells) -> None:
        booked = sorted({m for _, m in cells if not self.base.editable(m)})
        if booked:
            raise ValueError(
                f"{', '.join(self.months[m - 1] for m in booked)} already booked"
            )

    @cached_property
    def base(self) -> PlanCosting:
        return costing_for(self.snap)

    @cached_property
    def booked(self) -> dict[str, list[float | None]]:
        """Hours booked per completed month, per person with readings."""
        return completed_months(self.snap)

    @cached_property
    def full_month(self) -> list[float]:
        return full_time_month_hours(self.snap)

    @cached_property
    def full_week(self) -> float:
        return full_time_week_hours(self.snap)

    @cached_property
    def trends(self) -> list[dict[str, float | None]]:
        """Average hours a week over the trailing 2, 4 and 8 weeks, per person."""
        return [trailing_hours(self.snap, w) for w in TREND_WEEKS]

    def actual(self, cell: Cell) -> float | None:
        """Hours the person booked in this month, None unless it is complete."""
        row = self.booked.get(cell[0])
        return row[cell[1] - 1] if row else None

    def set_hours(self, cells, hours: float) -> bool:
        """Set each cell to ``hours`` of its month's full-time hours (clamped to
        0-100%) as one undo step; True if any cell was clamped."""
        self._check_open(cells)
        raw = {c: hours / self.full_month[c[1] - 1] for c in cells}
        self.checkpoint()
        self.edits.update({c: round(min(1.0, max(0.0, v)), 4) for c, v in raw.items()})
        return any(not 0 <= v <= 1 for v in raw.values())

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
            raise ValueError(f"FTE runs 0-100%, got {fte:.0%}")
        self._check_open(cells)
        self.checkpoint()
        self.edits.update(dict.fromkeys(cells, fte))

    def seed(self, path: str | Path) -> str:
        """Scratch edits from a month sheet; returns what happened, in words.

        Cells in booked months are left as they are, and a name with no rate
        in people.csv is seeded but not costed, as anywhere else in the plan.
        """
        cells = read_month_sheet(path, self.snap.span)
        open_ = {c: v for c, v in cells.items() if self.base.editable(c[1])}
        self.checkpoint()
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
        self.checkpoint()
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


TREND_WEEKS = (2, 4, 8)


def parse_hours(text: str) -> float:
    """``"80"`` or ``"80h"`` as hours."""
    raw = text.strip().lower().rstrip("h").strip()
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"not an hours figure: {text!r} (try 80)") from None


LEGEND = (
    "[b]type[/b] 0-100 or [b]Enter[/b] edit   [b]+ -[/b] nudge 5%   "
    "[b]space[/b] select   [b]u[/b]/[b]U[/b] undo/redo   [b]s[/b] save   "
    "[b]x[/b] discard   [b]esc[/b] leave grid (then 1-5 switch tabs)\n"
    "[b yellow]yellow[/b yellow] edited, not saved   [reverse]reversed[/reverse] selected"
    "\n[cyan]cyan[/cyan] booked actual (completed months) · 2w 4w 8w average booked"
    "   [dim]v solve to target   t set target   i import sheet   "
    "a add by name/date   g list[/dim]"
)


def mode_line(hours: bool) -> str:
    return "showing hours · h FTE %" if hours else "showing FTE % · h hours"


class PlanGrid(Vertical):
    """People × months of FTE, with scratch edits and a cost solver."""

    DEFAULT_CSS = """
    PlanGrid { height: 1fr; }
    PlanGrid #grid_readout { height: auto; padding: 0 2; }
    PlanGrid #grid_table { height: auto; max-height: 1fr; }
    PlanGrid #grid_input { height: 1; border: none; margin: 0 2; }
    PlanGrid #grid_changes { height: 1; padding: 0 2; }
    PlanGrid #grid_legend { height: auto; padding: 0 2; color: $text-muted; }
    PlanGrid #grid_status { height: auto; padding: 0 2; color: $success; }
    PlanGrid #grid_status.error { color: $error; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        # Footer order: the edit keys a newcomer needs first; aliases stay hidden
        # so the footer shows the primary key, not the last of a comma list.
        Binding("s", "commit", "Save"),
        Binding("u", "undo", "Undo"),
        Binding("U", "redo", "Redo"),
        Binding("x", "discard", "Discard"),
        Binding("plus", "nudge(0.05)", "+5%"),
        Binding("minus", "nudge(-0.05)", "-5%"),
        Binding("space", "toggle_cell", "Select"),
        Binding("c", "commit", show=False),
        Binding("ctrl+z", "undo", show=False),
        Binding("ctrl+y", "redo", show=False),
        Binding("equals_sign", "nudge(0.05)", show=False),
        Binding("underscore", "nudge(-0.05)", show=False),
        Binding("shift+right", "extend(0, 1)", show=False),
        Binding("shift+left", "extend(0, -1)", show=False),
        Binding("shift+down", "extend(1, 0)", show=False),
        Binding("shift+up", "extend(-1, 0)", show=False),
        Binding("v", "solve('proportional')", "Solve"),
        Binding("V", "solve('even')", "Solve even"),
        Binding("t", "ask('target')", "Target"),
        Binding("i", "ask('sheet')", "Import"),
        Binding("h", "toggle_units", "Hours/FTE %"),
        # Typing a number starts an edit (these win over the app's 1-5 tab keys
        # while the grid has focus).
        *[Binding(k, f"type('{k}')", show=False) for k in "0123456789."],
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
        self.hours = False  # FTE % or hours; lives as long as the tab is open

    def compose(self) -> ComposeResult:
        yield Static(id="grid_readout")
        yield DataTable(id="grid_table", cursor_type="cell", zebra_stripes=True)
        yield Input(id="grid_input")
        yield Static(id="grid_cost")
        yield Static(id="grid_changes")
        yield Static(self._legend(), id="grid_legend")
        yield Static(id="grid_status")

    def on_mount(self) -> None:
        self.query_one("#grid_input", Input).display = False

    def _legend(self) -> str:
        return f"{LEGEND}\n[b]{mode_line(self.hours)}[/b]"

    # -- loading -----------------------------------------------------------

    def load(self, snap: Snapshot | None) -> None:
        """Start over on ``snap`` (None: no project); scratch edits are dropped."""
        self.selected.clear()
        if snap is None:
            self.model = None
            self.query_one("#grid_table", DataTable).clear(columns=True)
            self.query_one("#grid_changes", Static).update("")
            self.query_one("#grid_cost", Static).update("")
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
        for w in TREND_WEEKS:
            table.add_column(f"{w}w")
        scratch = model.scratch
        for name in model.names:
            cells = [name]
            for m, fte in enumerate(scratch.grid(name), 1):
                if (booked := model.actual((name, m))) is not None:
                    text = f"[cyan]{self._show(booked, model.full_month[m - 1])}[/cyan]"
                else:
                    text = self._show(
                        fte * model.full_month[m - 1], model.full_month[m - 1]
                    )
                    if (name, m) in model.edits:
                        text = f"[b yellow]{text}[/b yellow]"
                    elif not model.base.editable(m):
                        text = f"[dim]{text}[/dim]"
                if (name, m) in self.selected:
                    text = f"[reverse]{text}[/reverse]"
                cells.append(text)
            for trend in model.trends:
                avg = trend.get(name)
                cells.append(
                    "[dim]—[/dim]"
                    if avg is None
                    else f"[cyan]{self._show(avg, model.full_week)}[/cyan]"
                )
            table.add_row(*cells)
        if table.row_count:
            table.move_cursor(
                row=min(cursor.row, table.row_count - 1), column=max(cursor.column, 1)
            )
        self._readout()

    def _show(self, hours: float, full: float) -> str:
        """``hours`` as hours, or as a share of ``full`` (full-time hours)."""
        return f"{hours:,.0f}" if self.hours else f"{hours / full if full else 0:.0%}"

    def _readout(self) -> None:
        r = self.model.readout()
        parts = [f"plan cost [b]{_money(r['cost'])}[/b]"]
        if r["target"] is None:
            parts.append("[dim]no target (t sets one)[/dim]")
        else:
            parts += [f"target {_money(r['target'])}", f"gap {_signed(r['gap'])}"]
        parts += [f"P50 {_money(r['p50'])}", f"P80 {_money(r['p80'])}"]
        line = "   ·   ".join(parts)
        self.query_one("#grid_readout", Static).update(line)
        saved = self.model.base.cost()
        delta = r["cost"] - saved
        self.query_one("#grid_cost", Static).update(
            f"unsaved: plan cost {_money(saved)} → {_money(r['cost'])} "
            f"({_signed(delta)})"
            if self.model.edits
            else ""
        )
        m, n = self.model, len(self.model.edits)
        head = (
            f"[b yellow]{n} change{'s' * (n != 1)}[/b yellow]"
            if n
            else "[dim]no changes[/dim]"
        )
        self.query_one("#grid_changes", Static).update(
            f"{head} [dim]·[/dim] "
            + ("u undo" if m.undone else "[dim]u undo[/dim]")
            + " [dim]·[/dim] "
            + ("U redo" if m.redone else "[dim]U redo[/dim]")
            + " [dim]·[/dim] "
            + ("[b]s save[/b]" if n else "[dim]s save[/dim]")
        )

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
            or coord.column > len(self.model.months)
            or coord.row >= len(self.model.names)
        ):
            return None
        return (self.model.names[coord.row], coord.column)

    def _blocked(self) -> bool:
        """Say why and return True when the cursor is on a cell no edit may touch.

        A selection is checked by the model instead (booked months refuse there).
        """
        if self.model is None or self.selected:
            return False
        coord = self.query_one("#grid_table", DataTable).cursor_coordinate
        if coord.column > len(self.model.months) and coord.row < len(self.model.names):
            self.say("averages are read-only", error=True)
            return True
        cell = self._cursor_cell()
        if cell and (booked := self.model.actual(cell)) is not None:
            full = self.model.full_month[cell[1] - 1]
            self.say(
                f"booked: {self._show(booked, full)} is what was booked", error=True
            )
            return True
        return False

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
        # Enter on a cell: edit its FTE (applied to the whole selection).
        event.stop()
        if self._blocked():
            return
        if cell := self._cursor_cell():
            self.action_ask("cell", self._prefill(cell))

    def _prefill(self, cell: Cell) -> str:
        fte = self.model.current(cell)
        if self.hours:
            return f"{round(fte * self.model.full_month[cell[1] - 1], 1):g}"
        return f"{fte * 100:g}"

    def action_toggle_units(self) -> None:
        if self._asking:
            return
        self.hours = not self.hours
        self.query_one("#grid_legend", Static).update(self._legend())
        if self.model:
            self._redraw()
        said = mode_line(self.hours)
        self.say(f"{said[0].upper()}{said[1:]}.")

    def action_type(self, key: str) -> None:
        """A digit on a cell starts an edit with that digit typed."""
        if self.model is None or self._asking or self._blocked():
            return
        if self._cursor_cell():
            self.action_ask("cell", key)
            # Focus selects the prefill; collapse it so the next digit appends.
            self.call_after_refresh(self.query_one("#grid_input", Input).action_end)

    def action_nudge(self, delta: float) -> None:
        cells = self._targets()
        if self.model is None or not cells or self._blocked():
            return
        try:
            moved = self.model.nudge(cells, delta)
        except ValueError as exc:
            self.say(str(exc), error=True)
            return
        if not moved:
            self.say(f"Already at {'100' if delta > 0 else '0'}%.")
            return
        self._redraw()
        self.say(
            f"{moved} cell(s) {'+' if delta > 0 else '-'}{abs(delta):.0%}"
            + (" FTE" if self.hours else "")
            + "."
        )

    def action_undo(self) -> None:
        if self.model and self.model.undo():
            self._redraw()
            self.say("Undone. U redoes.")
        else:
            self.say("Nothing to undo.")

    def action_redo(self) -> None:
        if self.model and self.model.redo():
            self._redraw()
            self.say("Redone.")
        else:
            self.say("Nothing to redo.")

    def action_ask(self, what: str, value: str = "") -> None:
        if self.model is None:
            return
        if what == "target" and self.model.target is not None:
            value = f"{self.model.target:,.0f}"
        box = self.query_one("#grid_input", Input)
        first, *_, last = self.model.months
        box.placeholder = {
            "cell": (
                "hours for the cursor/selected cells (80), enter applies, esc cancels"
                if self.hours
                else "% FTE for the cursor/selected cells (50 or 0.5), enter applies, esc cancels"
            ),
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
        else:
            # Out of the grid onto the tab bar, where the 1-5 keys switch tabs.
            self.app.query_one("#tabs", TabbedContent).query_one(Tabs).focus()

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
                if self.hours:
                    hours = parse_hours(event.value)
                    clamped = self.model.set_hours(cells, hours)
                    said = f"Set {len(cells)} cell(s) to {hours:g} h"
                    if clamped:
                        said += " (clamped to 0-100% of a full-time month)"
                    self.say(said + ".", error=clamped)
                else:
                    fte = parse_fte(event.value)
                    self.model.set(cells, fte)
                    self.say(f"Set {len(cells)} cell(s) to {fte:.0%}.")
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
            self.say("Nothing to save: no edits yet.")
            return
        self.post_message(self.Commit(self.model.rows()))

    def action_discard(self) -> None:
        if self.model and self.model.edits:
            self.model.checkpoint()
            self.model.edits.clear()
            self.selected.clear()
            self._redraw()
            self.say("Edits discarded. u brings them back.")
