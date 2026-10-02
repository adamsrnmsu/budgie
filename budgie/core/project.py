"""
Which input wins: the precedence rules for a project's files, in one place.

A project can hold two kinds of spend reading, a flat ``hours_spent`` column,
a plan, and a budget in two places. Every command, and anything reading a
Budgie project from outside (perch), has to settle the same questions the same
way, or two views of one project quote different numbers:

- A readings file named on the command line beats the project's copies,
  whichever kind it is.
- Weekly cumulative readings beat monthly ones.
- A dated reading beats the undated ``hours_spent`` in ``allocations.csv``.
- A plan beats the flat ``fte`` column (see :func:`~budgie.core.allocation.load_allocations`).
- A number pinned in ``budgie.yaml`` beats ``budget.csv``.

The CLI resolves its own options and bundled samples, then calls these;
:func:`load_snapshot` is the whole-project read for callers with no CLI.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

from budgie.core.actuals import (
    Observation,
    load_weekly_actuals,
    monthly_to_observations,
)
from budgie.core.allocation import Allocation, load_allocations
from budgie.core.budget import Budget, coerce_budget
from budgie.core.calendar import ProductiveHours, YearSpan, productive_hours, year_span
from budgie.core.costs import CostItem, load_costs, total_cost
from budgie.core.loader import load_people
from budgie.core.monthly import load_monthly_actuals
from budgie.core.person import Person
from budgie.core.plan import AllocationPlan, PlanEntry, load_plan
from budgie.core.workspace import CONFIG_NAME, Workspace, load_workspace


def readings_files(
    workspace: Workspace | None, actuals: str | None = None, weekly: str | None = None
) -> tuple[str | None, str | None]:
    """``(actuals, weekly)`` to read: named files, else the project's copies.

    Only when neither is named does the project supply them -- otherwise
    ``--actuals mine.csv`` would silently lose to the project's weekly.csv,
    which outranks it.
    """
    if actuals or weekly or workspace is None:
        return actuals, weekly
    return workspace.resolve("actuals"), workspace.resolve("weekly")


def load_observations(
    span: YearSpan,
    actuals: str | Path | None = None,
    weekly: str | Path | None = None,
) -> dict[str, list[Observation]]:
    """Spend readings as ``{name: [(date, cumulative hours)]}``; weekly wins.

    Weekly cumulative readings and monthly per-period hours both reduce to the
    same observations, so everything downstream handles one shape.
    """
    if weekly:
        return load_weekly_actuals(weekly, span)
    if actuals:
        return {
            name: monthly_to_observations(span, months)
            for name, months in load_monthly_actuals(actuals).items()
        }
    return {}


def spent_to_date(
    observations: dict[str, list[Observation]], as_of: date | None = None
) -> dict[str, float]:
    """Each person's latest cumulative reading on or before ``as_of``.

    People with no reading in range are left out, so their undated figure
    stands.
    """
    out = {}
    for name, series in observations.items():
        dated = [o for o in series if as_of is None or o[0] <= as_of]
        if dated:
            out[name] = max(dated)[1]
    return out


def with_readings(
    allocations: list[Allocation], spent: dict[str, float]
) -> list[Allocation]:
    """Allocations whose ``hours_spent`` is the dated reading where one exists."""
    return [
        replace(a, hours_spent=spent[a.name]) if a.name in spent else a
        for a in allocations
    ]


def budget_source(workspace: Workspace | None) -> float | str | None:
    """The project's budget: a number pinned in ``budgie.yaml``, else budget.csv."""
    if workspace is None:
        return None
    pinned = workspace.setting("budget")
    return pinned if pinned is not None else workspace.resolve("budget")


@dataclass(frozen=True)
class Snapshot:
    """A project as it stands: the inputs, with every precedence rule applied."""

    year: int
    pto: float
    ceiling: ProductiveHours
    people: list[Person]
    readings: dict[str, list[Observation]] = field(default_factory=dict)
    allocations: list[Allocation] = field(default_factory=list)
    planned: dict[str, float] = field(default_factory=dict)
    non_labor: float = 0.0
    #: The cost lines behind ``non_labor`` (with any low/high), for ``simulate(costs=)``.
    costs: list[CostItem] = field(default_factory=list)
    budget: Budget | None = None
    iterations: int = 10_000
    seed: int | None = None
    #: The loaded budget.csv with its dated revisions and notes; None when the
    #: budget is a flat number (pinned in budgie.yaml) or absent.
    budget_revisions: Budget | None = None
    #: The project's own plan.csv (never the bundled sample), or None.
    plan: AllocationPlan | None = None

    @property
    def allocated(self) -> dict[str, float]:
        """Allocated hours per person: allocations.csv, else the plan alone."""
        if self.allocations:
            return {a.name: a.allocated_hours for a in self.allocations}
        return dict(self.planned)

    @property
    def spent(self) -> dict[str, float]:
        """Hours spent: the latest reading, else allocations.csv's figure."""
        out = {a.name: a.hours_spent for a in self.allocations}
        out.update(spent_to_date(self.readings))
        return out

    def what_if(
        self, budget: float | None = None, plan_entries: Sequence[PlanEntry] = ()
    ) -> Snapshot:
        """A copy with a different budget and/or extra plan entries; touches no files.

        ``budget`` replaces the budget with a flat number, so ``budget_revisions``
        becomes None (the old dated revisions no longer describe it). Extra
        ``plan_entries`` are appended to the plan (``plan`` is updated to match)
        and allocated hours are recomputed the way :func:`load_snapshot` does:
        a planned person's hours come from the plan, not their flat ``fte``;
        someone only in the new entries is added with nothing spent.

        Someone named in ``plan_entries`` who is in allocations.csv but not the
        plan is first carried at their flat ``fte`` from Jan 1 (seeded ahead of
        the new entries, so a Jan 1 entry of their own still wins); otherwise a
        leave date would zero their whole year.
        """
        changes: dict = {}
        if budget is not None:
            changes.update(budget=Budget.flat(budget), budget_revisions=None)
        if plan_entries:
            planned = self.plan.names if self.plan else ()
            flat = {a.name: a.fte for a in self.allocations}
            seeds = [
                PlanEntry(n, date(self.year, 1, 1), flat[n])
                for n in dict.fromkeys(e.name for e in plan_entries)
                if n in flat and n not in planned
            ]
            plan = AllocationPlan(
                (*(self.plan.entries if self.plan else ()), *seeds, *plan_entries)
            )
            changes["plan"] = plan
            if self.allocations:
                changes["allocations"] = self._replanned(plan)
            else:
                changes["planned"] = plan.team_hours(
                    year_span(self.year), self.pto
                )  # bridge: budgie-bvd
        return replace(self, **changes)

    def _replanned(self, plan: AllocationPlan) -> list[Allocation]:
        """``allocations`` with planned people's FTE set to the plan's year average."""

        def fte(name: str, available: float) -> float:
            # Recover this person's PTO from their ceiling (a pto_days override).
            pto = (
                self.ceiling.productive_hours - available
            ) / self.ceiling.hours_per_day
            return (
                plan.allocated_hours(
                    name, year_span(self.year), pto
                )  # bridge: budgie-bvd
                / available
                if available
                else 0.0
            )

        out = [
            replace(a, fte=fte(a.name, a.available_hours))
            if a.name in plan.names
            else a
            for a in self.allocations
        ]
        listed = {a.name for a in out}
        ceiling = self.ceiling.available_hours
        out += [
            Allocation(n, fte(n, ceiling), 0.0, ceiling)
            for n in plan.names
            if n not in listed
        ]
        return out


def load_snapshot(project: str | Path) -> Snapshot:
    """Read the project in ``project`` (the directory holding budgie.yaml)."""
    workspace = load_workspace(Path(project) / CONFIG_NAME)
    year = workspace.setting("year")
    if year is None:
        raise ValueError(f"{workspace.config_path}: `year` is not set")
    pto = workspace.setting("pto", 0.0)
    ceiling = productive_hours(year_span(year), pto_days=pto)  # bridge: budgie-bvd

    people_csv = workspace.resolve("people")
    if people_csv is None:
        raise FileNotFoundError(f"{workspace.root}: no people.csv")
    people = load_people(people_csv, productive_hours=ceiling)

    actuals, weekly = readings_files(workspace)
    readings = {
        n: s
        for n, s in load_observations(
            year_span(year), actuals, weekly
        ).items()  # bridge: budgie-bvd
        if s
    }

    plan_csv = workspace.resolve("plan")
    plan = load_plan(plan_csv) if plan_csv else None
    alloc_csv = workspace.resolve("allocations")
    allocations = load_allocations(alloc_csv, ceiling, plan=plan) if alloc_csv else []
    planned = (
        plan.team_hours(year_span(year), pto_days=pto)  # bridge: budgie-bvd
        if plan and not allocations
        else {}
    )

    costs_csv = workspace.resolve("costs")
    costs = load_costs(costs_csv) if costs_csv else []
    source = budget_source(workspace)
    budget = None if source is None else coerce_budget(source)
    return Snapshot(
        year=year,
        pto=pto,
        ceiling=ceiling,
        people=people,
        readings=readings,
        allocations=allocations,
        planned=planned,
        non_labor=total_cost(costs),
        costs=costs,
        budget=budget,
        iterations=workspace.setting("iterations", 10_000),
        seed=workspace.setting("seed"),
        budget_revisions=budget if isinstance(source, str) else None,
        plan=plan,
    )
