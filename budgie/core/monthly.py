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
"""

from __future__ import annotations

import calendar as _calendar
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import holidays
import numpy as np
import pandas as pd

from budgie.core.calendar import productive_hours
from budgie.core.person import Person

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
    annual = productive_hours(year, pto_days=pto_days).available_hours
    return [annual * w for w in month_weights(year)]


def cumulative(values: Sequence[float]) -> list[float]:
    """Running total of ``values``."""
    out, running = [], 0.0
    for v in values:
        running += v
        out.append(running)
    return out


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
    people: Sequence[Person], year: int, pto_days: float = 0.0
) -> MonthlyForecast:
    """Spread the deterministic annual forecast across the months."""
    weights = month_weights(year)
    total_hours = sum(p.hours.point for p in people)
    total_cost = sum(p.expected_cost() for p in people)
    return MonthlyForecast(
        year=year,
        costs=tuple(total_cost * w for w in weights),
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
) -> MonthlySimulation:
    """Simulate cumulative team cost month by month.

    Each iteration draws every person's annual hours once, then distributes that
    draw across the months by working-day weight -- so the uncertainty band
    widens through the year rather than resetting each month.
    """
    if not people:
        raise ValueError("monthly_simulation() requires at least one person")

    rng = np.random.default_rng(seed)
    annual_totals = np.zeros(iterations, dtype=float)
    for person in people:
        annual_totals += person.sample_cost(rng, iterations)

    logger.info("Monthly simulation: %d iterations, %d people", iterations, len(people))
    weights = np.array(month_weights(year))
    # (iterations, 1) * (12,) -> (iterations, 12), then accumulate along months.
    monthly = annual_totals[:, None] * weights[None, :]
    return MonthlySimulation(year=year, cumulative_costs=np.cumsum(monthly, axis=1))


def load_monthly_actuals(csv_path: str | Path) -> dict[str, list[float]]:
    """Load per-person monthly hours from a tidy CSV.

    Expected columns ``name,month,hours`` with ``month`` as 1-12. Missing months
    count as zero. Returns ``{name: [12 monthly hours]}`` (not cumulative --
    call :func:`cumulative` for a burn-down curve).
    """
    frame = pd.read_csv(csv_path)
    missing = {"name", "month", "hours"} - set(frame.columns)
    if missing:
        raise ValueError(f"monthly actuals CSV missing columns: {sorted(missing)}")

    actuals: dict[str, list[float]] = {}
    for row in frame.itertuples(index=False):
        month = int(row.month)
        if not 1 <= month <= 12:
            raise ValueError(f"month must be 1-12, got {month} for {row.name}")
        actuals.setdefault(str(row.name), [0.0] * 12)[month - 1] += float(row.hours)
    logger.info("Loaded monthly actuals for %d people from %s", len(actuals), csv_path)
    return actuals
