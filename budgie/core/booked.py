"""What people actually booked: completed months and trailing weekly averages.

Read-only arithmetic over a Snapshot's readings, using Budgie's own curve
(:func:`budgie.core.monthly.spent_at`, which starts at 0 on ``span.zero`` and
interpolates between readings). Nothing here writes or forecasts.
"""

from __future__ import annotations

import calendar
from datetime import timedelta

from budgie.core.calendar import hours_per_workday
from budgie.core.monthly import monthly_available_hours, spent_at
from budgie.core.project import Snapshot


def full_time_month_hours(snap: Snapshot) -> list[float]:
    """A full-time person's available hours in each month of the span."""
    return monthly_available_hours(snap.span, snap.pto)


def full_time_week_hours(snap: Snapshot) -> float:
    """A full-time person's available hours in a five-day week."""
    return hours_per_workday(snap.span, snap.pto) * 5


def completed_months(snap: Snapshot) -> dict[str, list[float | None]]:
    """Per person, hours booked in each span month; None until the month is done.

    A month is complete when its last day is on or before the person's latest
    reading. People with no readings are left out.
    """
    out: dict[str, list[float | None]] = {}
    for name, series in snap.readings.items():
        if not series:
            continue
        latest = max(series)[0]
        prev, row = 0.0, []
        for year, month in snap.span.months:
            end = snap.span.first.replace(year=year, month=month, day=1).replace(
                day=calendar.monthrange(year, month)[1]
            )
            booked = spent_at(series, end, snap.span)
            row.append(booked - prev if end <= latest else None)
            prev = booked
        out[name] = row
    return out


def trailing_hours(snap: Snapshot, weeks: int) -> dict[str, float | None]:
    """Per person, average hours a week over the ``weeks`` ending at the latest reading.

    None when there are no readings or the window starts before the span.
    """
    out: dict[str, float | None] = {}
    for name, series in snap.readings.items():
        if not series:
            out[name] = None
            continue
        end = max(series)[0]
        start = end - timedelta(days=7 * weeks)
        out[name] = (
            None
            if start < snap.span.first
            else (spent_at(series, end, snap.span) - spent_at(series, start, snap.span))
            / weeks
        )
    return out
