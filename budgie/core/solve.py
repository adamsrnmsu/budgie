"""
What-if solving: which FTEs make the plan cost a given number?

Scenario planning is mostly "move a few people's FTE until the total lands on
the budget". The plan's cost is linear in FTE -- each working day at FTE *f*
costs ``f x rate x hours per day`` -- so the FTE that closes a gap is a
division, not a search::

    plan cost = sum of rate x (hours up to as_of + plan hours after it) + non-labor

A *cell* is one person in one month. :func:`solve` fills the chosen cells so
the plan cost hits a target, either scaling them all by one factor
(``proportional``, the default) or moving them all by the same FTE
(``even``). :func:`entries_for` turns cells into the dated plan rows that
make them true, so previewing and committing an edit go through the same
rows -- they cannot disagree. Nothing here writes a file.
"""

from __future__ import annotations

import calendar
import csv
import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from functools import cache, cached_property
from pathlib import Path
from typing import Literal

from budgie.core.calendar import YearSpan, federal_holidays, hours_per_workday
from budgie.core.csvio import as_float, last_day_of_month, read_rows, row_error
from budgie.core.plan import AllocationPlan, PlanEntry

logger = logging.getLogger(__name__)

#: One person in one month: 1 is the span's first month, 12 its last.
Cell = tuple[str, int]


def months(span: YearSpan) -> list[tuple[date, date]]:
    """First and last day of each month the grid shows, in the span's order."""
    return [(date(y, m, 1), last_day_of_month(y, m)) for y, m in span.months]


_per_day = cache(hours_per_workday)


@dataclass(frozen=True)
class _Month:
    """One person's plan over one month, split at ``as_of``."""

    past_fte_days: float
    past_days: int
    open_fte_days: float
    open_days: int


@dataclass(frozen=True)
class PlanCosting:
    """Everything that turns a plan into dollars.

    ``spent`` replaces the plan's hours up to ``as_of`` with what was really
    booked; it is ignored without an ``as_of``. A plan name with no entry in
    ``rates`` is not costed (see :attr:`uncosted`).
    """

    plan: AllocationPlan
    rates: Mapping[str, float]
    span: YearSpan
    pto: float = 0.0
    pto_by_name: Mapping[str, float] = field(default_factory=dict)
    non_labor: float = 0.0
    spent: Mapping[str, float] = field(default_factory=dict)
    as_of: date | None = None

    def with_plan(self, plan: AllocationPlan) -> PlanCosting:
        return replace(self, plan=plan)

    @cached_property
    def _workdays(self) -> list[list[date]]:
        off = federal_holidays(self.span)
        out = []
        for start, end in months(self.span):
            days = (start + timedelta(n) for n in range((end - start).days + 1))
            out.append([d for d in days if d.weekday() < 5 and d not in off])
        return out

    def _first_open_day(self, month: int) -> date:
        start = months(self.span)[month - 1][0]
        return max(start, self.as_of + timedelta(1)) if self.as_of else start

    def _months(self, name: str, plan: AllocationPlan) -> list[_Month]:
        changes = plan.changes_for(name)
        i, fte, out = 0, 0.0, []
        for days in self._workdays:
            past = [0.0, 0, 0.0, 0]
            for day in days:
                while i < len(changes) and changes[i].effective_date <= day:
                    fte = changes[i].fte
                    i += 1
                k = 0 if self.as_of and day <= self.as_of else 2
                past[k] += fte
                past[k + 1] += 1
            out.append(_Month(*past))
        return out

    def _hours_per_day(self, name: str) -> float:
        return _per_day(self.span, self.pto_by_name.get(name, self.pto))

    @property
    def uncosted(self) -> list[str]:
        """People in the plan with no rate, so not in :meth:`cost`."""
        return [n for n in self.plan.names if n not in self.rates]

    def editable(self, month: int) -> bool:
        """False once every working day of ``month`` is on or before ``as_of``."""
        return any(not self.as_of or d > self.as_of for d in self._workdays[month - 1])

    def cost(self, plan: AllocationPlan | None = None) -> float:
        """Plan cost of ``plan`` (default: this one), non-labor included."""
        plan = plan or self.plan
        total = self.non_labor
        for name in plan.names:
            if name not in self.rates:
                continue
            ms = self._months(name, plan)
            per_day = self._hours_per_day(name)
            past = per_day * sum(m.past_fte_days for m in ms)
            if self.as_of and name in self.spent:
                past = self.spent[name]
            total += self.rates[name] * (
                past + per_day * sum(m.open_fte_days for m in ms)
            )
        return total

    def grid(self, name: str) -> list[float]:
        """FTE per month, averaged over the month's working days after ``as_of``.

        A booked month shows its planned average instead.
        """
        return [
            m.open_fte_days / m.open_days
            if m.open_days
            else (m.past_fte_days / m.past_days if m.past_days else 0.0)
            for m in self._months(name, self.plan)
        ]

    def month_rates(self, name: str) -> list[float]:
        """Dollars per 1.0 FTE in each month's open working days."""
        per_hour = self.rates.get(name, 0.0) * self._hours_per_day(name)
        return [per_hour * m.open_days for m in self._months(name, self.plan)]


@dataclass(frozen=True)
class Solution:
    """New FTE per cell, the plan cost it gives, and the gap still open."""

    fte: dict[Cell, float]
    cost: float
    gap: float
    note: str = ""


def solve(
    costing: PlanCosting,
    cells: Collection[Cell],
    target: float,
    mode: Literal["proportional", "even"] = "proportional",
    cap: float = 1.0,
) -> Solution:
    """FTEs for ``cells`` that bring the plan cost to ``target``.

    ``proportional`` scales every cell by one factor, so the team keeps its
    shape. ``even`` adds the same FTE to every cell. FTE stays within
    ``[0, cap]`` (or the cell's current value, if that is already above
    ``cap``). A clamped cell keeps its clamped value and the rest are re-solved
    for what is left, so whatever gap remains is the most these cells can close.

    Raises:
        ValueError: a cell's month is already booked (not :meth:`PlanCosting.editable`).
    """
    booked = sorted({m for _, m in cells if not costing.editable(m)})
    if booked:
        raise ValueError(f"Month(s) {booked} are already booked; pick later months.")

    current: dict[Cell, float] = {}
    rate: dict[Cell, float] = {}
    for name in {n for n, _ in cells}:
        grid, rates = costing.grid(name), costing.month_rates(name)
        for n, m in cells:
            if n == name:
                current[(n, m)], rate[(n, m)] = grid[m - 1], rates[m - 1]

    note = ""
    if mode == "proportional" and not any(current[c] * rate[c] for c in cells):
        mode = "even"
        note = "Everyone selected is at 0 FTE, so the gap was split evenly instead."

    new = dict(current)
    free = {c for c in cells if rate[c] > 0}
    left = target - costing.cost()
    while free and left:
        if mode == "proportional":
            k = 1 + left / sum(rate[c] * current[c] for c in free)
            proposal = {c: current[c] * k for c in free}
        else:
            d = left / sum(rate[c] for c in free)
            proposal = {c: current[c] + d for c in free}
        clamped = {
            c: min(max(v, 0.0), max(cap, current[c]))
            for c, v in proposal.items()
            if not 0.0 <= v <= max(cap, current[c])
        }
        if not clamped:
            new.update(proposal)
            left = 0.0
            break
        for c, v in clamped.items():
            new[c] = v
            left -= (v - current[c]) * rate[c]
            free.discard(c)
        if mode == "proportional" and free and not any(current[c] for c in free):
            note = (
                "The rest are at 0 FTE, which scaling can't raise; try the even spread."
            )
            break

    return Solution(fte=new, cost=target - left, gap=left, note=note)


def entries_for(costing: PlanCosting, edits: Mapping[Cell, float]) -> list[PlanEntry]:
    """Dated plan rows that set each edited cell's month to its FTE.

    Each month gets a row at its first open day (skipped when the month before
    carries the same edit), plus one at every existing change date inside it
    -- otherwise that older row would still win from its date on. The month
    after an edit is restored to the old plan unless it is edited too. Append
    these to the plan; never edit history.
    """
    rows: list[PlanEntry] = []
    bounds = months(costing.span)
    for name in dict.fromkeys(n for n, _ in edits):
        mine = {m: v for (n, m), v in edits.items() if n == name}
        changes = costing.plan.changes_for(name)
        for m in sorted(mine):
            first, end = costing._first_open_day(m), bounds[m - 1][1]
            dates = {
                e.effective_date for e in changes if first <= e.effective_date <= end
            }
            if mine.get(m - 1) != mine[m] or first != bounds[m - 1][0]:
                dates.add(first)
            rows += [PlanEntry(name, d, mine[m]) for d in sorted(dates)]
            if m < 12 and m + 1 not in mine:
                nxt = bounds[m][0]
                rows.append(PlanEntry(name, nxt, costing.plan.fte_on(name, nxt)))
    return rows


#: ``jan``/``january`` -> 1, and so on: what a month column may be called.
_MONTH_NUMBERS = {
    name.lower(): m
    for names in (calendar.month_abbr, calendar.month_name)
    for m, name in enumerate(names)
    if name
}


def read_month_sheet(path: str | Path, span: YearSpan) -> dict[Cell, float]:
    """Cell FTEs from a wide sheet: ``name`` then one column per month of ``span``.

    The months must run in the span's order (``name,Oct,...,Sep`` for an
    Oct-start fiscal year), so a calendar sheet can't land a year off. ``Jan``,
    ``January`` and ``JAN`` all work. A blank cell is left out -- the grid keeps
    what it has there.

    Raises:
        ValueError: the header doesn't match the span, or a cell isn't an FTE
            0 to 1 (``sheet.csv line 3: dec: ...``).
    """
    path = Path(path)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        header = [h.strip().lower() for h in next(csv.reader(handle), [])]
    if header[:1] != ["name"] or [_MONTH_NUMBERS.get(h) for h in header[1:]] != [
        m for _, m in span.months
    ]:
        want = ",".join(calendar.month_abbr[m] for _, m in span.months)
        raise ValueError(f"{path.name}: expected columns name,{want}")
    cells: dict[Cell, float] = {}
    seen: dict[str, int] = {}
    for row in read_rows(path):
        name = row["name"]
        if not name:
            raise row_error(row, "name is blank")
        if name in seen:
            raise row_error(row, f"{name} is already on line {seen[name]}")
        seen[name] = row.line
        for m, column in enumerate(header[1:], 1):
            fte = as_float(row, column)
            if fte is None:
                continue
            if not 0 <= fte <= 1:
                raise row_error(row, f"{column}: fte must be 0 to 1, got {fte:g}")
            cells[(name, m)] = fte
    return cells
