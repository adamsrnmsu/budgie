"""
The monthly time dimension.

Everything else in the engine produces a single annual number. This module
spreads that year across its twelve months so you get a *trend* instead of a
point: cost per month, cumulative spend, and Monte Carlo bands that widen as the
year progresses.

Months are **not** weighted evenly. A month's share is its count of actual
working days (Mon-Fri, minus federal holidays landing in that month) over the
year's total, so February and holiday-heavy months carry correspondingly less.
Weights sum to 1, so the twelve monthly figures always add back up to the annual
figure produced by :mod:`budgie.core.calendar`.

With :class:`Actuals` (readings of real spend) the months already past are
*booked*, not forecast: each person's cumulative hours follow their readings up
to the latest one, and only the hours still to come -- the estimate at completion
minus what was spent -- are spread over the months from there on, by the plan's
shape when they have one, else by working days.
"""

from __future__ import annotations

import calendar as _calendar
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import holidays
import numpy as np

from budgie.core.actuals import Observation
from budgie.core.calendar import productive_hours, year_span
from budgie.core.costs import CostItem, monthly_totals, sample_total
from budgie.core.csvio import as_int, as_required_float, as_str, read_rows
from budgie.core.eac import elapsed_fraction
from budgie.core.person import Person

if TYPE_CHECKING:
    from budgie.core.plan import AllocationPlan

logger = logging.getLogger(__name__)


MONTH_NAMES = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def workdays_in_month(year: int, month: int) -> int:
    """Mon-Fri days in the month that are not US federal holidays."""
    us_holidays = holidays.UnitedStates(years=year)
    days_in_month = _calendar.monthrange(year, month)[1]
    return sum(
        1
        for day in range(1, days_in_month + 1)
        if (d := date(year, month, day)).weekday() < 5 and d not in us_holidays
    )


def month_weights(year: int) -> list[float]:
    """Each month's share of the year's working days (sums to 1.0)."""
    counts = [workdays_in_month(year, m) for m in range(1, 13)]
    total = sum(counts)
    return [c / total for c in counts]


def monthly_available_hours(year: int, pto_days: float = 0.0) -> list[float]:
    """The year's available hours split across months by working-day share."""
    annual = productive_hours(
        year_span(year), pto_days=pto_days
    ).available_hours  # bridge: budgie-bvd
    return [annual * w for w in month_weights(year)]


def cumulative(values: Sequence[float]) -> list[float]:
    """Running total of ``values``."""
    out, running = [], 0.0
    for v in values:
        running += v
        out.append(running)
    return out


@dataclass(frozen=True)
class Actuals:
    """Real spend to book into the months already past.

    ``readings`` is name -> the latest ``(date, spent)`` reading used for the
    estimate at completion (``Completion.readings``); ``observations`` is the
    full cumulative series, which shapes the booked months; ``plan`` shapes how
    the remaining hours fall across the rest of the year.
    """

    readings: Mapping[str, Observation]
    observations: Mapping[str, Sequence[Observation]] = field(default_factory=dict)
    plan: AllocationPlan | None = None


def spent_at(series: Sequence[Observation], day: date, year: int) -> float:
    """Cumulative hours booked by ``day``, interpolating between readings.

    The curve starts at 0 on Dec 31 of the prior year; between two readings we
    only know the endpoints, so the line between them is an assumption, not
    measured data. After the last reading it stays flat.

    Args:
        series: ``(date, cumulative hours)`` readings, in any order.
        day: The date to read the curve at.
        year: The budget year (fixes where the curve starts).

    Returns:
        Cumulative hours at ``day``.
    """
    prev_day, prev_hours = date(year, 1, 1) - timedelta(days=1), 0.0
    for when, hours in sorted(series):
        if when >= day:
            span = (when - prev_day).days
            return prev_hours + (hours - prev_hours) * (day - prev_day).days / span
        prev_day, prev_hours = when, hours
    return prev_hours


_spent_at = spent_at  # temporary alias until perch imports the public name (budgie-8u1)


def _cum_hours(person: Person, year: int, actuals: Actuals, total):
    """Cumulative hours at each month end for ``total`` hours at completion.

    ``total`` is a float or an array of simulated totals; the result gains a
    trailing month axis of 12.
    """
    total = np.asarray(total, dtype=float)[..., None]
    reading = actuals.readings.get(person.name)
    if reading is None:
        return total * np.cumsum(month_weights(year))
    when, spent = reading
    plan = actuals.plan
    left_by = {}  # share of the year's plan elapsed by a date

    def done(day: date) -> float:
        if day not in left_by:
            frac = plan.fraction_through(person.name, year, day) if plan else None
            left_by[day] = elapsed_fraction(year, day) if frac is None else frac
        return left_by[day]

    series = actuals.observations.get(person.name, ())
    booked, share = [], []
    for m in range(1, 13):
        end = date(year, m, _calendar.monthrange(year, m)[1])
        past = end < when
        booked.append(spent_at(series, end, year) if past else spent)
        left = 1.0 - done(when)
        # Past months hold no forecast. With nothing left of the plan after the
        # reading, whatever remains lands at once rather than dividing by zero.
        if past:
            share.append(0.0)
        elif left <= 1e-9:
            share.append(1.0)
        else:
            share.append(min(1.0, (done(end) - done(when)) / left))
    return np.array(booked) + (total - spent) * np.array(share)


@dataclass(frozen=True)
class MonthlyForecast:
    """Deterministic team cost broken out by month."""

    year: int
    costs: tuple[float, ...]  # per-month cost
    hours: tuple[float, ...]  # per-month hours

    @property
    def cumulative_costs(self) -> list[float]:
        return cumulative(self.costs)

    @property
    def total_cost(self) -> float:
        return sum(self.costs)


def monthly_forecast(
    people: Sequence[Person],
    year: int,
    pto_days: float = 0.0,
    costs: Sequence[CostItem] = (),
    actuals: Actuals | None = None,
) -> MonthlyForecast:
    """Spread the deterministic annual forecast across the months.

    Labor is spread by working-day weight; non-labor lines land in the month
    they are actually incurred rather than being smeared across the year. With
    ``actuals`` (and ``people`` already adjusted to the estimate at completion)
    the past months carry real hours and only the remainder is spread.
    """
    non_labor = monthly_totals(costs, year) if costs else [0.0] * 12
    if actuals is not None:
        cum = [_cum_hours(p, year, actuals, p.hours.point) for p in people]
        hours = np.diff(sum(cum), prepend=0.0)
        cost = np.diff(sum(p.hourly_cost * c for p, c in zip(people, cum)), prepend=0.0)
        return MonthlyForecast(
            year=year,
            costs=tuple(float(c) + n for c, n in zip(cost, non_labor)),
            hours=tuple(float(h) for h in hours),
        )
    weights = month_weights(year)
    total_hours = sum(p.hours.point for p in people)
    total_cost = sum(p.expected_cost() for p in people)
    return MonthlyForecast(
        year=year,
        costs=tuple(total_cost * w + n for w, n in zip(weights, non_labor)),
        hours=tuple(total_hours * w for w in weights),
    )


@dataclass(frozen=True)
class MonthlySimulation:
    """Monte Carlo cumulative cost by month (one row per iteration)."""

    year: int
    cumulative_costs: np.ndarray  # shape (iterations, 12)

    def band(self, p: float) -> list[float]:
        """Percentile ``p`` of cumulative cost at each month end."""
        return [float(x) for x in np.percentile(self.cumulative_costs, p, axis=0)]

    @property
    def iterations(self) -> int:
        return int(self.cumulative_costs.shape[0])


def monthly_simulation(
    people: Sequence[Person],
    year: int,
    pto_days: float = 0.0,
    iterations: int = 10_000,
    seed: int | None = None,
    costs: Sequence[CostItem] = (),
    actuals: Actuals | None = None,
) -> MonthlySimulation:
    """Simulate cumulative team cost month by month.

    Each iteration draws every person's annual hours once, then distributes that
    draw across the months by working-day weight -- so the uncertainty band
    widens through the year rather than resetting each month. With ``actuals``
    the past months are booked hours (no spread) and only what remains after the
    latest reading is simulated.
    """
    if not people:
        raise ValueError("monthly_simulation() requires at least one person")

    rng = np.random.default_rng(seed)
    logger.info("Monthly simulation: %d iterations, %d people", iterations, len(people))
    if actuals is None:
        annual_totals = np.zeros(iterations, dtype=float)
        for person in people:
            annual_totals += person.sample_cost(rng, iterations)
        weights = np.array(month_weights(year))
        # (iterations, 1) * (12,) -> (iterations, 12), accumulated along months.
        monthly = annual_totals[:, None] * weights[None, :]
    else:
        cum = sum(
            p.hourly_cost
            * _cum_hours(p, year, actuals, p.hours.sample(rng, iterations))
            for p in people
        )
        monthly = np.diff(cum, axis=1, prepend=0.0)

    if costs:
        # Non-labor lines are added in the month they fall, at their own
        # simulated scale, so the band steps up where the spend actually lands.
        shape = np.array(monthly_totals(costs, year))
        share = shape / shape.sum() if shape.sum() else shape
        monthly = (
            monthly + sample_total(costs, rng, iterations)[:, None] * share[None, :]
        )

    return MonthlySimulation(year=year, cumulative_costs=np.cumsum(monthly, axis=1))


def load_monthly_actuals(csv_path: str | Path) -> dict[str, list[float]]:
    """Load per-person monthly hours from a tidy CSV.

    Expected columns ``name,month,hours`` with ``month`` as 1-12. Missing months
    count as zero. Returns ``{name: [12 monthly hours]}`` (not cumulative --
    call :func:`cumulative` for a burn-down curve).
    """
    actuals: dict[str, list[float]] = {}
    for row in read_rows(csv_path, required={"name", "month", "hours"}):
        name = as_str(row, "name")
        month = as_int(row, "month")
        if not 1 <= month <= 12:
            raise ValueError(f"month must be 1-12, got {month} for {name}")
        actuals.setdefault(name, [0.0] * 12)[month - 1] += as_required_float(
            row, "hours"
        )
    logger.info("Loaded monthly actuals for %d people from %s", len(actuals), csv_path)
    return actuals
