"""
FTE allocation and hours-remaining tracking.

A person is allocated some fraction of a full-time schedule (FTE). Against the
year's available hours, that FTE converts to a concrete hours budget; subtracting
the hours they've already spent gives how many they have left.

    allocated_hours  = fte * available_hours(year)
    hours_remaining  = allocated_hours - hours_spent

This is separate from forecasting (``forecast.py`` / ``montecarlo.py``): that
projects *future cost*, this tracks *consumption against a fixed allocation*.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


_REQUIRED_COLS = {"name", "fte", "hours_spent"}


@dataclass(frozen=True)
class Allocation:
    """One person's FTE allocation and hours consumed to date."""

    name: str
    fte: float
    hours_spent: float
    available_hours: float
    email: str | None = None

    @property
    def allocated_hours(self) -> float:
        """Total hours this FTE buys against the year's available hours."""
        return self.fte * self.available_hours

    @property
    def hours_remaining(self) -> float:
        """Allocated hours not yet spent (can go negative if over budget)."""
        return self.allocated_hours - self.hours_spent

    @property
    def fraction_used(self) -> float:
        """Share of the allocation consumed (0..1+; 0 if nothing allocated)."""
        if self.allocated_hours == 0:
            return 0.0
        return self.hours_spent / self.allocated_hours

    @property
    def is_over_budget(self) -> bool:
        return self.hours_remaining < 0


def load_allocations(csv_path: str | Path, available_hours: float) -> list[Allocation]:
    """Load allocations from CSV, resolving FTE against ``available_hours``.

    Expected columns: ``name, fte, hours_spent`` and optionally ``email``.
    """
    frame = pd.read_csv(csv_path)
    missing = _REQUIRED_COLS - set(frame.columns)
    if missing:
        raise ValueError(f"allocations CSV missing columns: {sorted(missing)}")

    has_email = "email" in frame.columns
    logger.info("Loaded %d allocations from %s", len(frame), csv_path)
    return [
        Allocation(
            name=str(row.name),
            fte=float(row.fte),
            hours_spent=float(row.hours_spent),
            available_hours=available_hours,
            email=(str(row.email) if has_email else None),
        )
        for row in frame.itertuples(index=False)
    ]
