"""
Load a team from CSV into core objects.

Two input shapes are supported so utilization and raw hours are both first-class:

  Utilization form (fractions of the productive-hours ceiling)::

      name,hourly_cost,util_low,util_mode,util_high
      Alice,95,0.80,0.90,0.98

  Absolute-hours form (explicit three-point hours estimate)::

      name,hourly_cost,hours_low,hours_mode,hours_high
      Alice,95,1600,1800,1950

For the utilization form, ``productive_hours`` (the ceiling, e.g. from
:func:`budgie.core.calendar.productive_hours`) must be provided so fractions can
be resolved to hours.
"""

from __future__ import annotations

import logging
from pathlib import Path

from budgie.core.csvio import as_required_float, as_str, read_rows
from budgie.core.person import HoursEstimate, Person

logger = logging.getLogger(__name__)


_UTIL_COLS = ("util_low", "util_mode", "util_high")
_HOURS_COLS = ("hours_low", "hours_mode", "hours_high")


def load_people(
    csv_path: str | Path, productive_hours: float | None = None
) -> list[Person]:
    """Load a list of :class:`Person` from a CSV file.

    Args:
        csv_path: Path to the team CSV.
        productive_hours: Ceiling used to resolve the utilization form. Required
            if the CSV uses ``util_*`` columns.

    Raises:
        ValueError: If required columns are missing, or the utilization form is
            used without a ``productive_hours`` ceiling.
    """
    rows = read_rows(csv_path, required={"name", "hourly_cost"})
    cols = rows.columns

    if set(_UTIL_COLS) <= cols:
        if productive_hours is None:
            raise ValueError(
                "CSV uses utilization columns; a productive_hours ceiling is "
                "required (pass --year/--pto or compute productive_hours)"
            )
        shape = "utilization"
        build = lambda row: HoursEstimate.from_utilization(
            productive_hours,
            *(as_required_float(row, c) for c in _UTIL_COLS),
        )
    elif set(_HOURS_COLS) <= cols:
        shape = "absolute-hours"
        build = lambda row: HoursEstimate(
            *(as_required_float(row, c) for c in _HOURS_COLS)
        )
    else:
        raise ValueError(
            "team CSV must have either utilization columns "
            f"{_UTIL_COLS} or absolute-hours columns {_HOURS_COLS}"
        )

    people = [
        Person(
            name=as_str(row, "name"),
            hourly_cost=as_required_float(row, "hourly_cost"),
            hours=build(row),
        )
        for row in rows
    ]
    logger.info("Loaded %d people from %s (%s form)", len(people), csv_path, shape)
    return people
