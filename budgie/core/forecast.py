"""
Deterministic cost forecasting.

The plain, most-likely-case forecast: each person's cost is ``hourly_cost``
times their most-likely hours, summed across the team. This is the baseline that
the Monte Carlo simulation puts confidence bounds around.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from budgie.core.costs import CostItem, total_cost
from budgie.core.person import Person

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LineItem:
    name: str
    hourly_cost: float
    hours: float
    cost: float


@dataclass(frozen=True)
class Forecast:
    line_items: tuple[LineItem, ...]
    cost_items: tuple[CostItem, ...] = ()

    @property
    def labor_cost(self) -> float:
        return sum(item.cost for item in self.line_items)

    @property
    def non_labor_cost(self) -> float:
        return total_cost(self.cost_items)

    @property
    def total_cost(self) -> float:
        """Labor plus non-labor -- the number the budget is actually measured against."""
        return self.labor_cost + self.non_labor_cost

    @property
    def total_hours(self) -> float:
        return sum(item.hours for item in self.line_items)


def forecast(people: Sequence[Person], costs: Sequence[CostItem] = ()) -> Forecast:
    """Deterministic most-likely-case forecast for a team, plus any non-labor costs."""
    items = tuple(
        LineItem(
            name=p.name,
            hourly_cost=p.hourly_cost,
            hours=p.hours.point,
            cost=p.expected_cost(),
        )
        for p in people
    )
    return Forecast(line_items=items, cost_items=tuple(costs))
