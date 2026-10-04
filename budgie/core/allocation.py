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
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from budgie.core.calendar import ProductiveHours, resolve_ceiling
from budgie.core.csvio import (
    as_float,
    as_required_float,
    as_str,
    read_rows,
    row_error,
)

if TYPE_CHECKING:
    from budgie.core.plan import AllocationPlan

logger = logging.getLogger(__name__)


# ``fte`` and ``hours_spent`` are optional: the plan supersedes one and dated
# readings the other. A column that is present must still be filled in.
_REQUIRED_COLS = {"name"}


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
    csv_path: str | Path,
    available_hours: float | ProductiveHours,
    plan: AllocationPlan | None = None,
) -> list[Allocation]:
    """Load allocations from CSV, resolving FTE against ``available_hours``.

    Columns: ``name``, and optionally ``fte``, ``hours_spent``, ``email`` and
    ``pto_days``. A missing ``fte`` or ``hours_spent`` column means 0: the
    plan supplies hours and dated readings supply spend.

    Args:
        csv_path: Path to the allocations CSV.
        available_hours: The full-time hours ceiling. Pass a
            :class:`~budgie.core.calendar.ProductiveHours` breakdown to let a
            per-row ``pto_days`` column override the team default; a plain
            number applies one ceiling to everyone.
        plan: A dated :class:`~budgie.core.plan.AllocationPlan`. When given it,
            not the flat ``fte`` column, decides each planned person's hours;
            the ``fte`` reported is the **year average** (planned hours over
            the ceiling), so ``allocated_hours == fte * available_hours`` still
            holds. Someone the plan doesn't mention keeps their flat ``fte``;
            someone only in the plan is appended with nothing spent.
    """
    if plan is not None and not isinstance(available_hours, ProductiveHours):
        raise ValueError(
            "a plan needs a ProductiveHours ceiling, not a plain number (the "
            "plan is walked day by day, which needs the year and the PTO figure)"
        )
    rows = read_rows(csv_path, required=_REQUIRED_COLS)
    logger.info("Loaded %d allocations from %s", len(rows), csv_path)

    def number(row, key: str) -> float:
        return as_required_float(row, key) if key in rows.columns else 0.0

    def fte_of(row) -> float:
        fte = number(row, "fte")
        if not 0 <= fte <= 1:
            raise row_error(
                row,
                f"fte must be 0 to 1, got {fte:g} (FTE is a share of full time: 0 to 1)",
            )
        return fte

    allocations = [
        Allocation(
            name=as_str(row, "name"),
            fte=fte_of(row),
            hours_spent=number(row, "hours_spent"),
            available_hours=resolve_ceiling(available_hours, as_float(row, "pto_days")),
            email=as_str(row, "email") or None,
        )
        for row in rows
    ]
    if plan is not None:
        allocations = _apply_plan(allocations, rows, available_hours, plan)
    for alloc in allocations:
        logger.debug(
            "  %s: %.2f FTE x %.0f h ceiling = %.0f h allocated",
            alloc.name,
            alloc.fte,
            alloc.available_hours,
            alloc.allocated_hours,
        )
    return allocations


def pto_overrides(csv_path: str | Path) -> dict[str, float]:
    """Each person's own ``pto_days`` from an allocations CSV.

    People without a figure are left out, so ``.get(name, team_pto)`` is the
    whole lookup. The plan view needs this to agree with ``hours``: both walk
    the same plan, and a person's PTO has to be the same number in each.
    """
    return {
        as_str(row, "name"): days
        for row in read_rows(csv_path, required={"name"})
        if (days := as_float(row, "pto_days")) is not None
    }


def _planned_fte(
    plan: AllocationPlan, name: str, ph: ProductiveHours, pto_days: float | None
) -> float:
    """Year-average FTE: the plan's day-by-day hours over the full-time ceiling."""
    ceiling = ph.available_for(pto_days)
    if ceiling == 0:
        return 0.0
    days = ph.pto_days if pto_days is None else pto_days
    return plan.allocated_hours(name, ph.span, pto_days=days) / ceiling


def _apply_plan(
    allocations: list[Allocation],
    rows: list[dict],
    ph: ProductiveHours,
    plan: AllocationPlan,
) -> list[Allocation]:
    """Replace flat FTEs with the plan's, and add people only the plan knows."""
    planned = set(plan.names)
    out = []
    for alloc, row in zip(allocations, rows, strict=True):
        if alloc.name in planned:
            fte = _planned_fte(plan, alloc.name, ph, as_float(row, "pto_days"))
            alloc = replace(alloc, fte=fte)
        else:
            logger.warning(
                "%s is not in the plan -- keeping their flat %.2f FTE from the "
                "allocations file",
                alloc.name,
                alloc.fte,
            )
        out.append(alloc)

    listed = {a.name for a in allocations}
    for name in plan.names:
        if name in listed:
            continue
        logger.warning(
            "%s is in the plan but not the allocations file -- no spend recorded "
            "for them",
            name,
        )
        out.append(
            Allocation(
                name=name,
                fte=_planned_fte(plan, name, ph, None),
                hours_spent=0.0,
                available_hours=ph.available_hours,
            )
        )
    return out
