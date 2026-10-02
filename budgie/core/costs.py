"""
Non-labor costs.

Budgets are not only people. Materials, licences, hardware, travel and other
direct costs sit alongside the labor forecast and belong in the same totals and
the same Monte Carlo -- a $40k equipment line with a $10k range moves the
budget just as surely as an uncertain utilization does.

    name,category,date,amount,low,high,recurring
    Laptops,materials,2026-03-15,12000,11000,14000,no
    Cloud hosting,services,2026-01-01,2000,,,yes
    Travel,travel,2026-06-01,8000,6000,11000,no

``amount`` is the most-likely figure. ``low``/``high`` are optional; supply them
and the item is sampled triangularly like an hours estimate, leave them blank
and it is treated as known exactly.

``recurring`` marks a per-month charge: the amount is booked every month from
its own month through the year's last month, so one row covers a monthly subscription.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from budgie.core.csvio import as_float, as_required_float, as_str, parse_date, read_rows

if TYPE_CHECKING:
    from budgie.core.calendar import YearSpan

logger = logging.getLogger(__name__)

_REQUIRED_COLS = {"name", "amount", "date"}
_TRUTHY = {"yes", "y", "true", "1", "monthly", "recurring"}


@dataclass(frozen=True)
class CostItem:
    """A single non-labor cost line, optionally uncertain and/or recurring."""

    name: str
    amount: float
    when: date
    category: str = "other"
    low: float | None = None
    high: float | None = None
    recurring: bool = False
    #: Last day a recurring line is booked; None means December 31 of ``when.year``.
    through: date | None = None

    def __post_init__(self) -> None:
        if (
            self.low is not None
            and self.high is not None
            and not (self.low <= self.amount <= self.high)
        ):
            raise ValueError(
                f"{self.name}: need low <= amount <= high, got "
                f"({self.low}, {self.amount}, {self.high})"
            )
        if self.amount < 0:
            raise ValueError(f"{self.name}: amount cannot be negative")

    @property
    def months_charged(self) -> int:
        """How many months this line is booked in (1 unless recurring)."""
        if not self.recurring:
            return 1
        if self.through is None:
            return 13 - self.when.month
        t, w = self.through, self.when
        return max(0, (t.year - w.year) * 12 + t.month - w.month + 1)

    @property
    def total(self) -> float:
        """Deterministic total across the year (recurring charges multiply)."""
        return self.amount * self.months_charged

    @property
    def is_uncertain(self) -> bool:
        return self.low is not None and self.high is not None

    def sample(self, rng: np.random.Generator, size: int) -> np.ndarray:
        """Draw ``size`` totals for this line."""
        if not self.is_uncertain or self.low == self.high:
            return np.full(size, self.total, dtype=float)
        draws = rng.triangular(self.low, self.amount, self.high, size=size)
        return draws * self.months_charged


def total_cost(items: Sequence[CostItem]) -> float:
    """Deterministic sum of all non-labor lines."""
    return sum(item.total for item in items)


def sample_total(
    items: Sequence[CostItem], rng: np.random.Generator, size: int
) -> np.ndarray:
    """Draw ``size`` simulated totals across all non-labor lines."""
    totals = np.zeros(size, dtype=float)
    for item in items:
        totals += item.sample(rng, size)
    return totals


def monthly_totals(items: Sequence[CostItem], span: YearSpan) -> list[float]:
    """Non-labor cost booked in each month of ``span``, in the year's order.

    A one-off lands in its own month; a recurring line is booked in every month
    from its own through the year's last. Lines dated outside the span are left
    out.
    """
    months = [0.0] * 12
    index = {ym: i for i, ym in enumerate(span.months)}
    for item in items:
        start = index.get((item.when.year, item.when.month))
        if start is None:
            continue
        if item.recurring:
            for m in range(start, 12):
                months[m] += item.amount
        else:
            months[start] += item.amount
    return months


def by_category(items: Sequence[CostItem]) -> dict[str, float]:
    """Deterministic totals grouped by category."""
    out: dict[str, float] = {}
    for item in items:
        out[item.category] = out.get(item.category, 0.0) + item.total
    return out


def load_costs(csv_path: str | Path, through: date | None = None) -> list[CostItem]:
    """Load non-labor cost lines from CSV.

    Required columns ``name,amount,date``; optional ``category,low,high,recurring``.
    ``through`` is the year's last day, where recurring lines stop being booked.
    """
    items = []
    for row in read_rows(csv_path, required=_REQUIRED_COLS):
        items.append(
            CostItem(
                name=as_str(row, "name"),
                amount=as_required_float(row, "amount"),
                when=parse_date(row["date"]),
                category=as_str(row, "category", "other"),
                low=as_float(row, "low"),
                high=as_float(row, "high"),
                recurring=as_str(row, "recurring").lower() in _TRUTHY,
                through=through,
            )
        )
    logger.info(
        "Loaded %d non-labor cost lines from %s (total %s)",
        len(items),
        csv_path,
        f"${total_cost(items):,.0f}",
    )
    return items
