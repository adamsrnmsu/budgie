"""
Burn-down analysis for a person's hours allocation.

Answers the two questions an hours email actually needs to answer:

    "Am I ahead of or behind pace right now?"
    "If I keep going at this rate, when do I run out?"

Pace is the straight line from 0 hours on Jan 1 to the full allocation on Dec 31.
Actual burn rate is derived from hours spent over the days elapsed so far, and
projected forward to find the exhaustion date.

Note: with only a spent-to-date total we know the *endpoint*, not the shape of
the curve. Pass ``monthly_spent`` (cumulative hours at each month end) when real
month-by-month data is available and the chart will use it instead.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from budgie.core.actuals import Observation
from budgie.core.allocation import Allocation

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BurndownStatus:
    """Where a person stands against an even-pace burn of their allocation."""

    allocation: Allocation
    year: int
    as_of: date
    days_in_year: int
    days_elapsed: int
    observations: tuple[Observation, ...] = ()

    @property
    def hours_spent(self) -> float:
        """Hours booked to date.

        The latest observation wins when there is one: it is a dated reading,
        whereas the allocation's scalar has no as-of date attached.
        """
        if self.observations:
            return self.observations[-1][1]
        return self.allocation.hours_spent

    @property
    def elapsed_fraction(self) -> float:
        return self.days_elapsed / self.days_in_year

    @property
    def expected_by_now(self) -> float:
        """Hours they'd have spent if burning evenly across the year."""
        return self.allocation.allocated_hours * self.elapsed_fraction

    @property
    def variance(self) -> float:
        """Spent minus expected. Positive = burning faster than pace."""
        return self.hours_spent - self.expected_by_now

    @property
    def is_over_pace(self) -> bool:
        return self.variance > 0

    @property
    def burn_rate_per_day(self) -> float:
        if self.days_elapsed <= 0:
            return 0.0
        return self.hours_spent / self.days_elapsed

    @property
    def projected_total(self) -> float:
        """Hours they'd finish the year on at the current burn rate."""
        return self.burn_rate_per_day * self.days_in_year

    @property
    def projected_over(self) -> bool:
        return self.projected_total > self.allocation.allocated_hours

    @property
    def exhaustion_date(self) -> date | None:
        """Date the allocation runs out at the current rate, if within the year."""
        rate = self.burn_rate_per_day
        if rate <= 0:
            return None
        day = self.allocation.allocated_hours / rate
        if day > self.days_in_year:
            return None
        return date(self.year, 1, 1) + timedelta(days=day)


def burndown(
    allocation: Allocation,
    year: int,
    as_of: date | None = None,
    observations: Sequence[Observation] | None = None,
) -> BurndownStatus:
    """Build a :class:`BurndownStatus` for ``allocation`` as of a date.

    Args:
        allocation: The person's FTE allocation and hours spent.
        year: The budget year.
        as_of: Date to measure against. Defaults to the date of the latest
            observation when there is one (a dated reading beats "today", which
            would otherwise stretch the elapsed window and understate the burn
            rate), else today. Always clamped into the year.
        observations: Cumulative ``(date, hours_to_date)`` readings. One is
            enough; several give a real curve. See :mod:`budgie.core.actuals`.
    """
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    days_in_year = (end - start).days + 1

    obs = tuple(sorted(observations, key=lambda o: o[0])) if observations else ()

    if as_of is None:
        if obs:
            as_of = obs[-1][0]
        else:
            # Local calendar date is what a budget year is measured in; a
            # UTC-aware timestamp would be wrong for users west of UTC late
            # in the day.
            as_of = date.today()  # noqa: DTZ011
    # Clamp so a past/future year still yields a sane elapsed figure.
    as_of = min(max(as_of, start), end)

    logger.debug(
        "burndown %s: as_of=%s observations=%d", allocation.name, as_of, len(obs)
    )
    return BurndownStatus(
        allocation=allocation,
        year=year,
        as_of=as_of,
        days_in_year=days_in_year,
        days_elapsed=(as_of - start).days + 1,
        observations=obs,
    )
