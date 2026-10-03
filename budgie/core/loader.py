"""
Load a team from CSV into core objects.

The plain form gives only what an hour costs, plus how far real hours may stray
from the plan (percent under / over; both optional, missing means 0)::

    name,hourly_cost,under,over
    Alice,95,10,5

Its hours come from plan.csv (see :func:`budgie.core.project.people_on_plan`);
on its own each person has 0 hours. Two older shapes still load:

  Utilization form (fractions of the productive-hours ceiling)::

      name,hourly_cost,util_low,util_mode,util_high
      Alice,95,0.80,0.90,0.98

  Absolute-hours form (explicit three-point hours estimate)::

      name,hourly_cost,hours_low,hours_mode,hours_high
      Alice,95,1600,1800,1950

For the utilization form, ``productive_hours`` (the ceiling, e.g. from
:func:`budgie.core.calendar.productive_hours`) must be provided so fractions can
be resolved to hours. With a plan, either one becomes a spread around the plan
(low/likely and high/likely), which every form records on ``Person.spread``.
Any form may carry ``pto_days``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from budgie.core.calendar import ProductiveHours, resolve_ceiling
from budgie.core.csvio import as_float, as_required_float, as_str, read_rows, row_error
from budgie.core.person import HoursEstimate, Person

logger = logging.getLogger(__name__)


_UTIL_COLS = ("util_low", "util_mode", "util_high")
_HOURS_COLS = ("hours_low", "hours_mode", "hours_high")


def load_people(
    csv_path: str | Path, productive_hours: float | ProductiveHours | None = None
) -> list[Person]:
    """Load a list of :class:`Person` from a CSV file.

    Args:
        csv_path: Path to the team CSV.
        productive_hours: Ceiling used to resolve the utilization form. Required
            if the CSV uses ``util_*`` columns. Pass a
            :class:`~budgie.core.calendar.ProductiveHours` breakdown to let a
            per-row ``pto_days`` column give someone their own ceiling.

    Raises:
        ValueError: If required columns are missing, the utilization form is
            used without a ``productive_hours`` ceiling, the file has no people,
            or a row holds an impossible value (named by file and line).
    """
    rows = read_rows(csv_path, required={"name", "hourly_cost"})
    cols = rows.columns
    filename = Path(csv_path).name

    if set(_UTIL_COLS) <= cols:
        if productive_hours is None:
            raise ValueError(
                "CSV uses utilization columns; a productive_hours ceiling is "
                "required (pass --year/--pto or compute productive_hours)"
            )
        shape = "utilization"
        build = lambda row: HoursEstimate.from_utilization(
            resolve_ceiling(productive_hours, as_float(row, "pto_days")),
            *_three_points(row, _UTIL_COLS, share=True),
        )
        spread = lambda row: _ratios(*_three_points(row, _UTIL_COLS, share=True))
    elif set(_HOURS_COLS) <= cols:
        shape = "absolute-hours"
        build = lambda row: HoursEstimate(*_three_points(row, _HOURS_COLS))
        spread = lambda row: _ratios(*_three_points(row, _HOURS_COLS))
    elif not cols & {*_UTIL_COLS, *_HOURS_COLS}:
        shape = "plain"
        build = lambda row: HoursEstimate.constant(0.0)
        spread = _percent_spread
    else:
        raise ValueError(
            f"{filename}: team CSV must have all three utilization columns "
            f"{_UTIL_COLS}, all three absolute-hours columns {_HOURS_COLS}, "
            "or neither (the plain form: hours come from plan.csv)"
        )

    seen: dict[str, int] = {}  # casefolded name -> line it was first on
    people = [
        Person(
            name=_unique_name(row, seen),
            hourly_cost=_rate(row),
            hours=build(row),
            spread=spread(row),
            pto_days=as_float(row, "pto_days"),
        )
        for row in rows
    ]
    if not people:
        raise ValueError(f"{filename} has no people")
    logger.info("Loaded %d people from %s (%s form)", len(people), csv_path, shape)
    return people


def _unique_name(row, seen: dict[str, int]) -> str:
    """The row's name, refusing a blank one or a repeat ("alice" repeats "Alice")."""
    name = as_str(row, "name")
    if not name:
        raise row_error(row, "name is blank")
    first = seen.setdefault(name.casefold(), getattr(row, "line", 0))
    if first != getattr(row, "line", 0):
        raise row_error(row, f"{name} is already on line {first}; one row per person")
    return name


def _rate(row) -> float:
    cost = as_required_float(row, "hourly_cost")
    if cost < 0:
        raise row_error(row, f"hourly_cost cannot be negative, got {cost:g}")
    return cost


def _three_points(row, cols: tuple[str, str, str], share: bool = False) -> list[float]:
    """``low, mode, high`` from ``cols``: in order, not negative, and ``<= 1`` if a share."""
    values = [as_required_float(row, c) for c in cols]
    for col, value in zip(cols, values):
        if share and not 0 <= value <= 1:
            hint = " (looks like a percentage -- use 0.80 for 80%)" if value > 1 else ""
            raise row_error(row, f"{col} must be 0 to 1, got {value:g}{hint}")
        if value < 0:
            raise row_error(row, f"{col} cannot be negative, got {value:g}")
    if not values[0] <= values[1] <= values[2]:
        got = ", ".join(f"{v:g}" for v in values)
        raise row_error(row, f"need {' <= '.join(cols)}, got {got}")
    return values


def _ratios(low: float, mode: float, high: float) -> tuple[float, float] | None:
    """``(low/mode, high/mode)``, or None when ``mode`` is 0."""
    return (low / mode, high / mode) if mode else None


def _percent_spread(row) -> tuple[float, float]:
    """The plain form's ``under`` / ``over`` percentages as ratios of the plan."""
    under = as_float(row, "under") or 0.0
    over = as_float(row, "over") or 0.0
    if not 0 <= under <= 100 or over < 0:
        raise row_error(
            row,
            "under must be 0-100 and over at least 0 "
            f"(percent of planned hours), got under={under:g}, over={over:g}",
        )
    return 1 - under / 100, 1 + over / 100
