"""
Date-resolution allocation planning.

An allocation is not one number for the year -- people join, leave, and get
re-planned. A plan records *when* each change takes effect:

    name,effective_date,fte
    Alice,2026-01-01,0.25
    Bob,2026-01-01,0.50
    Bob,2026-09-01,0.00      # left the project
    Carol,2026-07-15,0.50    # joined mid-July
    Dave,2026-01-01,0.25
    Dave,2026-04-01,0.75     # bumped up

Each row applies **from that date until the next row for that person**; before
someone's first row they are simply not on the project (0 FTE). So "add a
member", "zero someone out", and "re-plan an allocation" are all the same
operation -- append a row. History is never edited, so you keep the record of
what changed and when.

Hours are counted day by day over real working days, so a mid-month start is
charged from the actual day rather than rounded to a whole month.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import holidays
import pandas as pd

from budgie.core.calendar import hours_per_workday

logger = logging.getLogger(__name__)


_REQUIRED_COLS = {"name", "effective_date", "fte"}


@dataclass(frozen=True)
class PlanEntry:
    """One change to a person's allocation, effective from ``effective_date``."""

    name: str
    effective_date: date
    fte: float


@dataclass(frozen=True)
class AllocationPlan:
    """A team's allocation changes over time, keyed by person."""

    entries: tuple[PlanEntry, ...]

    @property
    def names(self) -> list[str]:
        seen: dict[str, None] = {}
        for e in self.entries:
            seen.setdefault(e.name, None)
        return list(seen)

    def _for(self, name: str) -> list[PlanEntry]:
        return sorted(
            (e for e in self.entries if e.name == name), key=lambda e: e.effective_date
        )

    def fte_on(self, name: str, day: date) -> float:
        """The person's FTE in effect on ``day`` (0 before their first entry)."""
        current = 0.0
        for entry in self._for(name):
            if entry.effective_date <= day:
                current = entry.fte
            else:
                break
        return current

    def allocated_hours(self, name: str, year: int, pto_days: float = 0.0) -> float:
        """Hours this person's plan buys them across ``year``.

        Sums each working day at the FTE in effect that day, so someone starting
        2026-07-15 at 0.50 FTE is charged only for the working days from July 15
        onward -- not a full-month or full-year approximation.
        """
        per_day = hours_per_workday(year, pto_days=pto_days)
        schedule = self._for(name)
        if not schedule:
            return 0.0

        us_holidays = holidays.UnitedStates(years=year)
        start, end = date(year, 1, 1), date(year, 12, 31)
        # Never start before the person's first effective date.
        day = max(start, schedule[0].effective_date)
        total = 0.0
        while day <= end:
            if day.weekday() < 5 and day not in us_holidays:
                total += self.fte_on(name, day) * per_day
            day += timedelta(days=1)
        return total

    def team_hours(self, year: int, pto_days: float = 0.0) -> dict[str, float]:
        """Allocated hours for everyone in the plan."""
        return {n: self.allocated_hours(n, year, pto_days) for n in self.names}


def load_plan(csv_path: str | Path) -> AllocationPlan:
    """Load an allocation plan from a ``name,effective_date,fte`` CSV.

    ``effective_date`` is any format pandas can parse (ISO ``YYYY-MM-DD`` is
    recommended). A person may have any number of rows.
    """
    frame = pd.read_csv(csv_path)
    missing = _REQUIRED_COLS - set(frame.columns)
    if missing:
        raise ValueError(f"plan CSV missing columns: {sorted(missing)}")

    entries = []
    for row in frame.itertuples(index=False):
        fte = float(row.fte)
        if fte < 0:
            raise ValueError(f"fte cannot be negative, got {fte} for {row.name}")
        entries.append(
            PlanEntry(
                name=str(row.name),
                effective_date=pd.to_datetime(row.effective_date).date(),
                fte=fte,
            )
        )
    plan = AllocationPlan(entries=tuple(entries))
    logger.info(
        "Loaded plan: %d entries across %d people from %s",
        len(entries),
        len(plan.names),
        csv_path,
    )
    for name in plan.names:
        changes = plan._for(name)
        logger.debug(
            "  %s: %s",
            name,
            ", ".join(f"{e.effective_date}->{e.fte:g}" for e in changes),
        )
    return plan
