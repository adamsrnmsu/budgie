"""
Monte Carlo cost simulation.

Each person's expected hours is uncertain (see
:class:`budgie.core.person.HoursEstimate`). Rather than reporting a single
fake-precise number, we draw many simulated futures, sum the team cost in each,
and summarise the resulting distribution with percentiles (P10 / P50 / P90).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from budgie.core.costs import CostItem, sample_total
from budgie.core.person import Person

logger = logging.getLogger(__name__)


DEFAULT_ITERATIONS = 10_000
DEFAULT_PERCENTILES = (10, 50, 90)


@dataclass(frozen=True)
class SimulationResult:
    """Outcome of a Monte Carlo run.

    ``total_costs`` holds one simulated team-total per iteration and is what
    downstream code histograms.
    """

    total_costs: np.ndarray
    iterations: int

    def percentile(self, p: float) -> float:
        return float(np.percentile(self.total_costs, p))

    def percentiles(
        self, ps: Sequence[float] = DEFAULT_PERCENTILES
    ) -> dict[float, float]:
        return {p: self.percentile(p) for p in ps}

    @property
    def mean(self) -> float:
        return float(np.mean(self.total_costs))

    @property
    def std(self) -> float:
        return float(np.std(self.total_costs))


def simulate(
    people: Sequence[Person],
    iterations: int = DEFAULT_ITERATIONS,
    seed: int | None = None,
    costs: Sequence[CostItem] = (),
) -> SimulationResult:
    """Run a Monte Carlo simulation of total team cost.

    Args:
        people: Team members, each carrying an hours estimate.
        iterations: Number of simulated futures to draw.
        seed: Optional RNG seed for reproducible runs.

    Returns:
        A :class:`SimulationResult` whose ``total_costs`` has one entry per
        iteration.
    """
    if not people:
        raise ValueError("simulate() requires at least one person")

    logger.info(
        "Simulating %d iterations over %d people (seed=%s)",
        iterations,
        len(people),
        seed,
    )
    rng = np.random.default_rng(seed)
    totals = np.zeros(iterations, dtype=float)
    for person in people:
        totals += person.sample_cost(rng, iterations)
    if costs:
        # Non-labor lines carry their own uncertainty and belong in the same
        # distribution -- a wide equipment estimate moves the budget too.
        totals += sample_total(costs, rng, iterations)
    return SimulationResult(total_costs=totals, iterations=iterations)
