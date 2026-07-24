"""
FTE allocation and hours-remaining tracking.

A person is allocated some fraction of a full-time schedule (FTE). Against the
year's available hours, that FTE converts to a concrete hours budget; subtracting
the hours they've already spent gives how many they have left.

    allocated_hours  = fte * available_hours(year)
    hours_remaining  = allocated_hours - hours_spent

Note the order: ``available_hours`` is a **full-time** figure that already has
holidays and PTO taken off, and FTE is applied to the result. PTO is therefore
pro-rated -- see :data:`budgie.core.calendar.PTO_RULE`. A person can override
the team's PTO figure with a ``pto_days`` column.

This is separate from forecasting (``forecast.py`` / ``montecarlo.py``): that
projects *future cost*, this tracks *consumption against a fixed allocation*.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from budgie.core.calendar import ProductiveHours, resolve_ceiling
from budgie.core.csvio import as_float, as_required_float, as_str, read_rows

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


def load_allocations(
    csv_path: str | Path, available_hours: float | ProductiveHours
) -> list[Allocation]:
    """Load allocations from CSV, resolving FTE against ``available_hours``.

    Expected columns: ``name, fte, hours_spent`` and optionally ``email`` and
    ``pto_days``.

    Args:
        csv_path: Path to the allocations CSV.
        available_hours: The full-time hours ceiling. Pass a
            :class:`~budgie.core.calendar.ProductiveHours` breakdown to let a
            per-row ``pto_days`` column override the team default; a plain
            number applies one ceiling to everyone.
    """
    rows = read_rows(csv_path, required=_REQUIRED_COLS)
    logger.info("Loaded %d allocations from %s", len(rows), csv_path)
    allocations = [
        Allocation(
            name=as_str(row, "name"),
            fte=as_required_float(row, "fte"),
            hours_spent=as_required_float(row, "hours_spent"),
            available_hours=resolve_ceiling(available_hours, as_float(row, "pto_days")),
            email=as_str(row, "email") or None,
        )
        for row in rows
    ]
    for alloc in allocations:
        logger.debug(
            "  %s: %.2f FTE x %.0f h ceiling = %.0f h allocated",
            alloc.name,
            alloc.fte,
            alloc.available_hours,
            alloc.allocated_hours,
        )
    return allocations
