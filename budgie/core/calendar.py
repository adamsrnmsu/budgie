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

    @property
    def productive_hours(self) -> float:
        """Gross hours minus federal holidays (the user's core definition)."""
        return self.gross_hours - self.holiday_hours

    @property
    def available_hours(self) -> float:
        """Productive hours minus PTO/sick -- what's left to actually bill/work."""
        return self.productive_hours - self.pto_hours


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
    )
