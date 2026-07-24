"""
Observed spend to date.

Real timesheet exports rarely give a clean week-by-week series. Far more often
you get a *cumulative* reading: "as of week 20, this person has booked 480
hours." This module models exactly that and nothing more -- a sparse list of
``(date, cumulative_hours)`` observations.

    name,week,hours_to_date
    Alice,12,300
    Alice,20,480

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

import pandas as pd

logger = logging.getLogger(__name__)

# (observation date, cumulative hours booked through that date)
Observation = tuple[date, float]

_WEEKLY_COLS = {"name", "week", "hours_to_date"}


def week_ending(year: int, week: int) -> date:
    """The date that ISO ``week`` of ``year`` ends (its Sunday).

    "Hours up to week N" means through the end of that week, so this is the
    correct as-of date for such a reading.
    """
    try:
        return date.fromisocalendar(year, week, 7)
    except ValueError as exc:  # week 53 in a 52-week year, week 0, etc.
        raise ValueError(f"{year} has no ISO week {week}") from exc


def load_weekly_actuals(
    csv_path: str | Path, year: int
) -> dict[str, list[Observation]]:
    """Load cumulative hours-to-date readings keyed by ISO week number.

    Expected columns ``name,week,hours_to_date``. Returns each person's
    observations sorted by date.
    """
    frame = pd.read_csv(csv_path)
    missing = _WEEKLY_COLS - set(frame.columns)
    if missing:
        raise ValueError(f"weekly actuals CSV missing columns: {sorted(missing)}")

    out: dict[str, list[Observation]] = {}
    for row in frame.itertuples(index=False):
        when = week_ending(year, int(row.week))
        out.setdefault(str(row.name), []).append((when, float(row.hours_to_date)))

    for name, obs in out.items():
        obs.sort(key=lambda o: o[0])
        _check_non_decreasing(name, obs)
    logger.info(
        "Loaded weekly actuals for %d people from %s (latest: %s)",
        len(out),
        csv_path,
        max((o[-1][0] for o in out.values()), default="n/a"),
    )
    return out


def monthly_to_observations(year: int, monthly_hours: list[float]) -> list[Observation]:
    """Convert per-month hours into cumulative month-end observations."""
    out: list[Observation] = []
    running = 0.0
    for index, hours in enumerate(monthly_hours):
        month = index + 1
        running += hours
        last_day = (
            date(year, 12, 31)
            if month == 12
            else date(year, month + 1, 1) - pd.Timedelta(days=1).to_pytimedelta()
        )
        out.append((last_day, running))
    return out


def _check_non_decreasing(name: str, obs: list[Observation]) -> None:
    """Cumulative totals can't shrink -- catch per-period values pasted by mistake."""
    for (d1, h1), (d2, h2) in pairwise(obs):
        if h2 < h1:
            raise ValueError(
                f"{name}: hours_to_date fell from {h1:g} ({d1}) to {h2:g} ({d2}). "
                "These readings must be cumulative, not per-week."
            )
