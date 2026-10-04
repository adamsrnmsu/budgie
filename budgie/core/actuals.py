"""
Observed spend to date.

Real timesheet exports rarely give a clean week-by-week series. Far more often
you get a *cumulative* reading: "as of week 20, this person has booked 660
hours." This module models exactly that and nothing more -- a sparse list of
``(date, cumulative_hours)`` observations.

    name,week,hours_to_date
    Alice,12,430
    Alice,20,660

One observation is enough (it fixes the endpoint precisely). Several give a real
burn-down curve without ever needing per-week detail you don't have.

Crucially the values are **cumulative, not per-period**, so nothing is inferred
about how the hours were distributed between two readings.
"""

from __future__ import annotations

import logging
from datetime import date
from itertools import pairwise
from pathlib import Path

from budgie.core.calendar import YearSpan
from budgie.core.csvio import (
    as_int,
    as_required_float,
    as_str,
    last_day_of_month,
    read_rows,
    row_error,
)

logger = logging.getLogger(__name__)

# (observation date, cumulative hours booked through that date)
Observation = tuple[date, float]

_WEEKLY_COLS = {"name", "week", "hours_to_date"}


def week_ending(span: YearSpan, week: int) -> date:
    """The date ISO ``week`` ends (its Sunday) in the year ``span`` covers.

    "Hours up to week N" means through the end of that week, so this is the
    correct as-of date for such a reading. In a fiscal year a week numbered at
    or above the ISO week holding the first day belongs to that day's ISO year,
    a lower one to the last day's: in FY27 weeks 40-53 are 2026, 1-39 are 2027.
    A calendar year keeps every number in that year, as it always has.
    """
    iso_year = span.year
    if span.fiscal:
        first_year, first_week, _ = span.first.isocalendar()
        iso_year = first_year if week >= first_week else span.last.isocalendar()[0]
    try:
        return date.fromisocalendar(iso_year, week, 7)
    except ValueError as exc:  # week 53 in a 52-week year, week 0, etc.
        raise ValueError(f"{iso_year} has no ISO week {week}") from exc


def load_weekly_actuals(
    csv_path: str | Path, span: YearSpan
) -> dict[str, list[Observation]]:
    """Load cumulative hours-to-date readings keyed by ISO week number.

    Expected columns ``name,week,hours_to_date``. Returns each person's
    observations sorted by date.
    """
    wheres: dict[tuple[str, date, float], str] = {}
    out: dict[str, list[Observation]] = {}
    for row in read_rows(csv_path, required=_WEEKLY_COLS):
        try:
            when = week_ending(span, as_int(row, "week"))
        except ValueError as exc:
            if str(exc).startswith(row.where):  # as_int already named the line
                raise
            raise row_error(row, str(exc)) from exc
        name, hours = as_str(row, "name"), as_required_float(row, "hours_to_date")
        wheres[name, when, hours] = row.where
        out.setdefault(name, []).append((when, hours))

    for name, obs in out.items():
        obs.sort(key=lambda o: o[0])
        _check_non_decreasing(name, obs, wheres)
    logger.info(
        "Loaded weekly actuals for %d people from %s (latest: %s)",
        len(out),
        csv_path,
        max((o[-1][0] for o in out.values()), default="n/a"),
    )
    return out


def monthly_to_observations(
    span: YearSpan, monthly_hours: list[float]
) -> list[Observation]:
    """Convert per-month hours (index 0 = January) into cumulative month-end
    observations, in the order the year runs (October first in FY27).

    Stops after the last month that has hours. A trailing empty month is a
    month nobody has reported yet, not a reading of zero -- emitting it would
    date the latest observation on the year's last day and leave no year to
    pace against. An empty month *between* two reported ones is a real reading
    and is kept.
    """
    ordered = [monthly_hours[month - 1] for _, month in span.months]
    reported = max((i + 1 for i, h in enumerate(ordered) if h), default=0)
    out: list[Observation] = []
    running = 0.0
    for (year, month), hours in zip(span.months[:reported], ordered):
        running += hours
        out.append((last_day_of_month(year, month), running))
    return out


def _check_non_decreasing(
    name: str, obs: list[Observation], wheres: dict[tuple[str, date, float], str]
) -> None:
    """Cumulative totals can't shrink -- catch per-period values pasted by mistake."""
    for (d1, h1), (d2, h2) in pairwise(obs):
        if h2 < h1:
            where = wheres.get((name, d2, h2))
            raise ValueError(
                f"{where + ': ' if where else ''}{name}: hours_to_date fell from {h1:g} ({d1}) to {h2:g} ({d2}). "
                "These readings must be cumulative, not per-week."
            )
