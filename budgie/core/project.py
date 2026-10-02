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

from collections.abc import Mapping, Sequence
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
from budgie.core.calendar import ProductiveHours, productive_hours
from budgie.core.costs import CostItem, load_costs, total_cost
from budgie.core.loader import load_people
from budgie.core.monthly import load_monthly_actuals
from budgie.core.person import HoursEstimate, Person
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
    year: int, actuals: str | Path | None = None, weekly: str | Path | None = None
) -> dict[str, list[Observation]]:
    """Spend readings as ``{name: [(date, cumulative hours)]}``; weekly wins.

    Weekly cumulative readings and monthly per-period hours both reduce to the
    same observations, so everything downstream handles one shape.
    """
    if weekly:
        return load_weekly_actuals(weekly, year)
    if actuals:
        return {
            name: monthly_to_observations(year, months)
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


def people_on_plan(
    people: Sequence[Person],
    plan: AllocationPlan | None,
    year: int,
    pto: float = 0.0,
    pto_by_name: Mapping[str, float] | None = None,
) -> tuple[list[Person], list[str]]:
    """The team with each person's hours taken from ``plan``, plus warnings.

    A planned person's likely hours are ``plan.allocated_hours`` and their low
    and high are that figure scaled by ``Person.spread``, so people.csv says
    what an hour costs and how far real hours may stray, and the plan says how
    many there are. Someone in people.csv with no plan rows gets 0 hours;
    someone in the plan with no rate is not costed. Both are warned about,
    because either one quietly changes the total.

    PTO is the person's own ``pto_days`` from people.csv, else ``pto_by_name``
    (allocations.csv), else ``pto``; when both files give one and they differ,
    people.csv wins and that is a warning too. Without a plan the team is
    returned unchanged.

    The warnings are sentences for a person to read, not log records.
    """
    pto_by_name = pto_by_name or {}
    if plan is None:
        return list(people), [
            f"{p.name} has a rate but no hours: people.csv gives none and "
            "there is no plan.csv."
            for p in people
            if p.spread is not None and p.hours.high == 0
        ]

    warnings: list[str] = []
    planned = set(plan.names)
    out = []
    for person in people:
        if person.name not in planned:
            warnings.append(
                f"{person.name} has a rate in people.csv but no rows in "
                "plan.csv, so 0 hours."
            )
            out.append(replace(person, hours=HoursEstimate.constant(0.0)))
            continue
        days, other = person.pto_days, pto_by_name.get(person.name)
        if days is None:
            days = other
        elif other is not None and other != days:
            warnings.append(
                f"{person.name}: pto_days is {days:g} in people.csv but {other:g} "
                "in allocations.csv; using people.csv."
            )
        likely = plan.allocated_hours(person.name, year, pto if days is None else days)
        spread = person.spread
        if spread is None:
            warnings.append(
                f"{person.name}'s likely hours in people.csv are 0, so their "
                "planned hours have no spread."
            )
            spread = (1.0, 1.0)
        out.append(
            replace(
                person,
                hours=HoursEstimate(likely * spread[0], likely, likely * spread[1]),
            )
        )

    rated = {p.name.casefold(): p.name for p in people}
    for name in plan.names:
        if name in {p.name for p in people}:
            continue
        near = rated.get(name.casefold())
        hint = f" (people.csv has {near!r})" if near else ""
        warnings.append(
            f"{name} is in plan.csv but has no rate in people.csv{hint}, so not costed."
        )
    return out, warnings


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
    #: Things a person should be told about how the inputs were combined (see
    #: :func:`people_on_plan`): sentences to show, never only logged.
    warnings: list[str] = field(default_factory=list)

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
            return replace(self.with_plan(plan), **changes)
        return replace(self, **changes)

    def with_plan(self, plan: AllocationPlan) -> Snapshot:
        """A copy with ``plan`` in place of the project's; touches no files.

        Allocated hours, ``people`` (so cost, not just hours) and ``warnings``
        are all re-derived from it, which is how an edited or deleted plan row
        is previewed.
        """
        changes: dict = {"plan": plan}
        if self.allocations:
            changes["allocations"] = self._replanned(plan)
        else:
            changes["planned"] = plan.team_hours(self.year, self.pto)
        return replace(self, **changes)._on_plan()

    def _on_plan(self) -> Snapshot:
        """``people`` and ``warnings`` re-derived from ``plan``.

        Someone in allocations.csv the plan doesn't mention keeps their flat
        ``fte`` from Jan 1 -- the same rule allocated hours follow -- so hours
        and cost agree; that is still worth a warning.
        """
        plan, warnings = self.plan, []
        if plan is not None:
            seeds = [
                PlanEntry(a.name, date(self.year, 1, 1), a.fte)
                for a in self.allocations
                if a.name not in plan.names and a.fte
            ]
            warnings = [
                f"{e.name} has no rows in plan.csv; using allocations.csv fte "
                f"{e.fte:g} from Jan 1."
                for e in seeds
            ]
            if seeds:
                plan = AllocationPlan((*plan.entries, *seeds))
        people, more = people_on_plan(
            self.people, plan, self.year, self.pto, self._allocation_pto()
        )
        return replace(self, people=people, warnings=warnings + more)

    def _allocation_pto(self) -> dict[str, float]:
        """Per-person PTO days allocations.csv gave, recovered from each ceiling."""
        team = self.ceiling.available_hours
        return {
            a.name: (self.ceiling.productive_hours - a.available_hours)
            / self.ceiling.hours_per_day
            for a in self.allocations
            if abs(a.available_hours - team) > 1e-9
        }

    def _replanned(self, plan: AllocationPlan) -> list[Allocation]:
        """``allocations`` with planned people's FTE set to the plan's year average."""

        def fte(name: str, available: float) -> float:
            # Recover this person's PTO from their ceiling (a pto_days override).
            pto = (
                self.ceiling.productive_hours - available
            ) / self.ceiling.hours_per_day
            return (
                plan.allocated_hours(name, self.year, pto) / available
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
    ceiling = productive_hours(year, pto_days=pto)

    people_csv = workspace.resolve("people")
    if people_csv is None:
        raise FileNotFoundError(f"{workspace.root}: no people.csv")
    people = load_people(people_csv, productive_hours=ceiling)

    actuals, weekly = readings_files(workspace)
    readings = {n: s for n, s in load_observations(year, actuals, weekly).items() if s}

    plan_csv = workspace.resolve("plan")
    plan = load_plan(plan_csv) if plan_csv else None
    alloc_csv = workspace.resolve("allocations")
    allocations = load_allocations(alloc_csv, ceiling, plan=plan) if alloc_csv else []
    planned = plan.team_hours(year, pto_days=pto) if plan and not allocations else {}

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
    )._on_plan()
