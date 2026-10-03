"""
Productive-hours calculation.

"Productive hours" is the number of paid hours a person is actually available to
work in a year: a full 40-hour week baseline, minus US federal holidays, and
optionally minus paid time off / sick leave to reach "available hours" (the
productivity-factor model common in government contracting).

All calculations are anchored to a real calendar year via the ``holidays``
package, so weekend-observed holidays and leap years are handled correctly
rather than assuming a flat 2080-hour year.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

import holidays

logger = logging.getLogger(__name__)


HOURS_PER_DAY = 8.0
HOURS_PER_WEEK = 40.0
WEEKS_PER_YEAR = 52.0

# Gross paid hours in a standard year before any holidays/PTO are removed.
GROSS_ANNUAL_HOURS = HOURS_PER_WEEK * WEEKS_PER_YEAR  # 2080.0


def federal_holiday_workdays(year: int) -> int:
    """Number of US federal holidays that fall on a workday (Mon-Fri) in ``year``.

    Holidays observed on a weekend are shifted by the federal government to an
    adjacent weekday; the ``holidays`` package already encodes those observed
    dates, so counting weekday holidays here reflects days genuinely lost from a
    Mon-Fri schedule.
    """
    us_holidays = holidays.UnitedStates(years=year)
    return sum(1 for day in us_holidays if day.weekday() < 5)


def workdays_between(start: date, end: date) -> int:
    """Count Mon-Fri days in ``[start, end]`` that are not federal holidays."""
    if end < start:
        return 0
    years = range(start.year, end.year + 1)
    us_holidays = holidays.UnitedStates(years=list(years))
    count = 0
    day = start
    while day <= end:
        if day.weekday() < 5 and day not in us_holidays:
            count += 1
        day += timedelta(days=1)
    return count


def workdays_in_year(year: int) -> int:
    """Working days in the whole calendar year."""
    return workdays_between(date(year, 1, 1), date(year, 12, 31))


def hours_per_workday(year: int, pto_days: float = 0.0) -> float:
    """Available hours spread evenly across the year's real working days.

    The year's available-hours figure comes from the 52-week model (2080 gross),
    while a real calendar has its own working-day count. Dividing one by the
    other keeps day-level math reconciling exactly to the annual total instead
    of drifting by the difference.
    """
    workdays = workdays_in_year(year)
    if workdays == 0:
        return 0.0
    return productive_hours(year, pto_days=pto_days).available_hours / workdays


@dataclass(frozen=True)
class ProductiveHours:
    """Breakdown of how gross annual hours reduce to productive/available hours."""

    year: int
    gross_hours: float
    holiday_hours: float
    pto_hours: float
    hours_per_day: float = HOURS_PER_DAY

    @property
    def productive_hours(self) -> float:
        """Gross hours minus federal holidays (the user's core definition)."""
        return self.gross_hours - self.holiday_hours

    @property
    def available_hours(self) -> float:
        """Productive hours minus PTO/sick -- what's left to actually bill/work."""
        return self.productive_hours - self.pto_hours

    @property
    def pto_days(self) -> float:
        """The PTO figure this breakdown was built with, back in days."""
        return self.pto_hours / self.hours_per_day if self.hours_per_day else 0.0

    def available_for(self, pto_days: float | None = None) -> float:
        """Available hours for one person, honouring their own PTO figure.

        ``None`` means "this person didn't state their own PTO", so the team
        default baked into this breakdown applies.

        Note this is a **full-time** ceiling. Scaling by FTE happens afterwards
        (:class:`budgie.core.allocation.Allocation`), which is what makes PTO
        pro-rated: a 0.25 FTE person gives the project a quarter of their PTO,
        not all of it. See :func:`explain_pto`.
        """
        if pto_days is None:
            return self.available_hours
        return self.productive_hours - pto_days * self.hours_per_day


def resolve_ceiling(ceiling: float | ProductiveHours, pto_days: float | None) -> float:
    """The hours ceiling for one person, from either kind of ceiling argument.

    Loaders accept a plain number (one ceiling for the whole team) or a
    :class:`ProductiveHours` breakdown (which additionally lets a person's own
    ``pto_days`` column give them their own ceiling). A per-person PTO figure
    needs the breakdown -- a bare number has already had PTO subtracted and
    can't be un-subtracted.
    """
    if isinstance(ceiling, ProductiveHours):
        return ceiling.available_for(pto_days)
    if pto_days is not None:
        raise ValueError(
            "a per-person pto_days column needs a ProductiveHours ceiling, not a "
            "plain number (the number has already had the team's PTO taken off)"
        )
    return float(ceiling)


def productive_hours(
    year: int,
    pto_days: float = 0.0,
    hours_per_day: float = HOURS_PER_DAY,
) -> ProductiveHours:
    """Compute productive/available hours for a given calendar ``year``.

    Args:
        year: Calendar year to anchor federal holidays to.
        pto_days: Paid time off + sick days to additionally subtract. Defaults
            to 0, which yields pure "productive hours" (holidays only).
        hours_per_day: Length of a workday, used to convert holiday/PTO days to
            hours. Defaults to 8.

    Returns:
        A :class:`ProductiveHours` breakdown.
    """
    holiday_days = federal_holiday_workdays(year)
    return ProductiveHours(
        year=year,
        gross_hours=GROSS_ANNUAL_HOURS,
        holiday_hours=holiday_days * hours_per_day,
        pto_hours=pto_days * hours_per_day,
        hours_per_day=hours_per_day,
    )


# The single most-asked question about this model, answered in one place so the
# CLI, the README and the docstrings can't drift apart.
PTO_RULE = (
    "PTO is pro-rated by FTE. A person's ceiling is computed full-time "
    "(2080 gross - holidays - their PTO), and *then* multiplied by their FTE. "
    "So someone 25% on the project gives up 25% of their PTO to it, not all of "
    "it -- the other 75% comes out of whatever else they work on."
)


def explain_pto(ph: ProductiveHours, fte: float = 0.25) -> str:
    """Worked example of the PTO/FTE rule at a given FTE, for `budgie assumptions`."""
    if not ph.pto_hours:
        # With no PTO there is nothing to pro-rate, and the two ways of
        # counting it agree -- so showing them side by side would just confuse.
        return (
            f"No PTO is set, so there is nothing to pro-rate: {fte:g} FTE is "
            f"{fte:g} x {ph.productive_hours:,.0f} = "
            f"{fte * ph.productive_hours:,.0f} h. Set pto in budgie.yaml or --pto (or a "
            f"pto_days column in people.csv) to see the difference this rule makes."
        )
    full_time = ph.available_hours
    prorated = fte * full_time
    all_pto = fte * ph.productive_hours - ph.pto_hours
    return (
        f"At {fte:g} FTE with {ph.pto_days:g} PTO days: "
        f"{fte:g} x {full_time:,.0f} = {prorated:,.0f} h "
        f"(charging all their PTO to the project would give {all_pto:,.0f} h)"
    )
