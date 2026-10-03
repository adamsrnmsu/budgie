"""
Burn-down analysis for a person's hours allocation.

Answers the two questions an hours email actually needs to answer:

    "Am I ahead of or behind pace right now?"
    "If I keep going at this rate, when do I run out?"

Pace is the straight line from 0 hours on the year's first day to the full allocation on its last --
or, when the person is in a plan.csv, the plan's own hours accumulated through each
date, ending on their last planned working day.
Actual burn rate is derived from hours spent over the days elapsed so far, and
projected forward to find the exhaustion date.

Note: with only a spent-to-date total we know the *endpoint*, not the shape of
the curve. Pass ``monthly_spent`` (cumulative hours at each month end) when real
month-by-month data is available and the chart will use it instead.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import TYPE_CHECKING

from budgie.core.actuals import Observation
from budgie.core.allocation import Allocation
from budgie.core.calendar import HOURS_PER_WEEK, YearSpan, workdays_between

if TYPE_CHECKING:
    from budgie.core.plan import AllocationPlan

logger = logging.getLogger(__name__)

# A full-time week, used to turn an hours-per-week pace back into an FTE.
WORKDAYS_PER_WEEK = 5.0


@dataclass(frozen=True)
class RequiredPace:
    """What finishing the year exactly on allocation would take from here.

    "You have 318 hours left" is a number people can't act on. "That's about 12
    hours a week, or 30% of your time, for the 26 weeks left" is the same fact
    in the unit they actually plan in.
    """

    hours_remaining: float
    workdays_remaining: int

    @property
    def weeks_remaining(self) -> float:
        return self.workdays_remaining / WORKDAYS_PER_WEEK

    @property
    def hours_per_week(self) -> float:
        """Even weekly pace that lands exactly on the allocation."""
        if self.workdays_remaining <= 0 or self.hours_remaining <= 0:
            return 0.0
        return self.hours_remaining / self.weeks_remaining

    @property
    def fte(self) -> float:
        """That weekly pace as a fraction of a full-time week."""
        return self.hours_per_week / HOURS_PER_WEEK

    @property
    def is_exhausted(self) -> bool:
        """Nothing left to spend -- the allocation is used up or overrun."""
        return self.hours_remaining <= 0

    @property
    def is_impossible(self) -> bool:
        """The remaining hours can't be worked in the time left (over 1.0 FTE)."""
        return self.fte > 1.0

    @property
    def out_of_time(self) -> bool:
        """Hours left but no working days left to spend them in."""
        return self.workdays_remaining <= 0 and self.hours_remaining > 0


@dataclass(frozen=True)
class BurndownStatus:
    """Where a person stands against an even-pace burn of their allocation."""

    allocation: Allocation
    span: YearSpan
    as_of: date
    days_in_year: int
    days_elapsed: int
    observations: tuple[Observation, ...] = ()
    plan: AllocationPlan | None = None

    @property
    def planned(self) -> bool:
        """Whether the plan has hours for this person (else pace is an even burn)."""
        return (
            self.plan is not None
            and self.plan.fraction_through(self.allocation.name, self.span, self.as_of)
            is not None
        )

    def expected_on(self, day: date) -> float:
        """Hours they'd have spent by ``day`` on pace.

        The plan's hours accumulated through ``day`` when they have a plan,
        otherwise an even burn across the year.
        """
        day = min(max(day, self.span.first), self.span.last)
        name = self.allocation.name
        fraction = (
            self.plan.fraction_through(name, self.span, day) if self.plan else None
        )
        if fraction is None:
            fraction = ((day - self.span.first).days + 1) / self.days_in_year
        return self.allocation.allocated_hours * fraction

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
        """Hours they'd have spent by ``as_of`` on pace (see :meth:`expected_on`)."""
        return self.expected_on(self.as_of)

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
    def required_pace(self) -> RequiredPace:
        """Weekly hours / FTE needed to finish the year exactly on allocation.

        Counted over the *real working days* left after ``as_of`` -- Mon-Fri
        minus federal holidays -- so a December reading doesn't imply there are
        four more weeks of capacity than there are. With a plan the window ends
        on the person's last planned working day, not the year's last day.
        """
        end = self.span.last
        if self.planned:
            end = self.plan.last_planned_day(self.allocation.name, self.span) or end
        return RequiredPace(
            hours_remaining=self.allocation.allocated_hours - self.hours_spent,
            workdays_remaining=workdays_between(self.as_of + timedelta(days=1), end),
        )

    @property
    def exhaustion_date(self) -> date | None:
        """Date the allocation runs out at the current rate, if within the year."""
        rate = self.burn_rate_per_day
        if rate <= 0:
            return None
        day = self.allocation.allocated_hours / rate
        if day > self.days_in_year:
            return None
        return self.span.first + timedelta(days=day)


def burndown(
    allocation: Allocation,
    span: YearSpan,
    as_of: date | None = None,
    observations: Sequence[Observation] | None = None,
    plan: AllocationPlan | None = None,
) -> BurndownStatus:
    """Build a :class:`BurndownStatus` for ``allocation`` as of a date.

    Args:
        allocation: The person's FTE allocation and hours spent.
        span: The budget year (see :func:`~budgie.core.calendar.year_span`).
        as_of: Date to measure against. Defaults to the date of the latest
            observation when there is one (a dated reading beats "today", which
            would otherwise stretch the elapsed window and understate the burn
            rate), else today. Always clamped into the year.
        observations: Cumulative ``(date, hours_to_date)`` readings. One is
            enough; several give a real curve. See :mod:`budgie.core.actuals`.
        plan: The allocation plan. Someone it has hours for gets a plan-shaped
            pace line and a pace window ending on their last planned day.
    """
    start, end = span.first, span.last
    days_in_year = span.days

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

    if obs:
        # A dated reading beats the allocation's undated scalar -- and the
        # status has to carry ONE spent figure, or a draft quotes the scalar in
        # its table and the reading in its pace sentence.
        allocation = replace(allocation, hours_spent=obs[-1][1])

    logger.debug(
        "burndown %s: as_of=%s observations=%d", allocation.name, as_of, len(obs)
    )
    return BurndownStatus(
        allocation=allocation,
        span=span,
        as_of=as_of,
        days_in_year=days_in_year,
        days_elapsed=(as_of - start).days + 1,
        observations=obs,
        plan=plan,
    )
