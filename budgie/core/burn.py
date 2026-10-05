"""The monthly burn a chart needs, in labor dollars.

Measured spend at each month-end, the plan's dollars, the budget in force
(minus the cost lines) and a P10, P50 and P90 fan to the year's end. This is
the same estimate-at-completion plus monthly simulation that `budgie
monthly` runs, so a front end reads one function instead of re-deriving it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from budgie.core.csvio import last_day_of_month
from budgie.core.eac import at_completion
from budgie.core.monthly import Actuals, monthly_simulation, spent_at

if TYPE_CHECKING:
    from budgie.core.project import Snapshot


@dataclass(frozen=True)
class BurnSeries:
    """Twelve month-ends of labor dollars; a None is "no figure", never zero."""

    months: tuple[date, ...]
    spent: tuple[float | None, ...]  # booked by each month-end; None after as_of
    spent_as_of: tuple[date, float] | None  # the latest reading day and dollars then
    plan: tuple[float | None, ...]  # planned through each month-end
    budget: tuple[float | None, ...]  # budget in force at month-end, less cost lines
    p10: tuple[float, ...]  # empty when there is no fan
    p50: tuple[float, ...]
    p90: tuple[float, ...]
    reading_dates: tuple[date, ...]  # distinct reading days, sorted
    as_of: date | None
    note: str = ""  # "" or why a part is missing


def burn_series(snap: Snapshot) -> BurnSeries:
    span = snap.span
    ends = tuple(last_day_of_month(y, m) for y, m in span.months)
    rate = {p.name: p.hourly_cost for p in snap.people}
    days = sorted({d for series in snap.readings.values() for d, _ in series})
    as_of = days[-1] if days else None

    def booked(day: date) -> float:
        return sum(
            spent_at(series, day, span) * rate[name]
            for name, series in snap.readings.items()
            if name in rate
        )

    spent = tuple(booked(d) if as_of and d <= as_of else None for d in ends)
    spent_as_of = (as_of, booked(as_of)) if as_of else None

    allocated = snap.allocated

    def planned(day: date) -> float:
        total = 0.0
        for name in allocated:
            hours = snap.planned_through(name, day)
            if hours is not None and name in rate:
                total += hours * rate[name]
        return total

    plan = tuple(planned(d) for d in ends) if allocated else (None,) * 12
    book = snap.budget_revisions or snap.budget
    budget = (
        tuple(a - snap.non_labor for a in book.monthly_amounts(span))
        if book
        else (None,) * 12
    )

    note, fan = "", ((), (), ())
    if as_of is None:
        note = "no hours readings yet"
    elif not snap.people:
        note = "no people"
    else:
        eac = at_completion(
            snap.people, snap.readings, span, as_of=as_of, plan=snap.plan
        )
        sim = monthly_simulation(
            eac.people,
            span,
            pto_days=snap.pto,
            iterations=snap.iterations,
            seed=snap.seed,
            actuals=Actuals(eac.readings, snap.readings, snap.plan),
        )
        fan = tuple(tuple(sim.band(q)) for q in (10, 50, 90))
    return BurnSeries(
        months=ends,
        spent=spent,
        spent_as_of=spent_as_of,
        plan=plan,
        budget=budget,
        p10=fan[0],
        p50=fan[1],
        p90=fan[2],
        reading_dates=tuple(days),
        as_of=as_of,
        note=note,
    )
