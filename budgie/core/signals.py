"""
Rules-based stoplight analysis over Monte Carlo results.

Turns a cost distribution + a budget target into a single, explainable signal:

    GREEN   good      -- budget comfortably covers the likely outcomes
    YELLOW  caution   -- a real chance of overrunning the budget
    RED     bad       -- the budget is likely to be exceeded
    BLUE    no change -- essentially unchanged from a baseline run

The rules are deliberately simple and transparent (no black box): the driving
number is the probability of exceeding the budget, estimated directly from the
simulated outcomes. BLUE is only possible when a baseline is supplied.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from budgie.core.montecarlo import SimulationResult

# Default thresholds (probability of exceeding budget).
logger = logging.getLogger(__name__)


GREEN_MAX = 0.10
YELLOW_MAX = 0.40
# Default "no material change" band vs baseline mean.
NO_CHANGE_TOL = 0.02


class Signal(Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    BLUE = "blue"

    @property
    def label(self) -> str:
        return {
            Signal.GREEN: "good",
            Signal.YELLOW: "caution",
            Signal.RED: "bad",
            Signal.BLUE: "no change",
        }[self]


@dataclass(frozen=True)
class SignalResult:
    signal: Signal
    rationale: str
    prob_over_budget: float
    budget: float
    p50: float
    baseline_delta: float | None  # fractional change in mean vs baseline, if any

    @property
    def label(self) -> str:
        return self.signal.label


def probability_over(sim: SimulationResult, budget: float) -> float:
    """Share of simulated outcomes that exceed ``budget``."""
    return float((sim.total_costs > budget).mean())


def evaluate(
    sim: SimulationResult,
    budget: float,
    baseline: SimulationResult | None = None,
    *,
    green_max: float = GREEN_MAX,
    yellow_max: float = YELLOW_MAX,
    no_change_tol: float = NO_CHANGE_TOL,
) -> SignalResult:
    """Classify a Monte Carlo result against a budget into a stoplight signal.

    Args:
        sim: The current simulation.
        budget: The budget target to test against.
        baseline: Optional prior simulation; enables the BLUE "no change" signal.
        green_max: Max probability-over-budget still considered GREEN.
        yellow_max: Max probability-over-budget still considered YELLOW.
        no_change_tol: Fractional mean change (vs baseline) treated as "no change".
    """
    prob = probability_over(sim, budget)
    p50 = sim.percentile(50)
    logger.debug(
        "signal check: budget=%.0f p50=%.0f p(over)=%.3f baseline=%s",
        budget,
        p50,
        prob,
        baseline is not None,
    )

    delta: float | None = None
    if baseline is not None and baseline.mean:
        delta = (sim.mean - baseline.mean) / baseline.mean
        if abs(delta) <= no_change_tol:
            return SignalResult(
                signal=Signal.BLUE,
                rationale=(
                    f"Within {no_change_tol:.0%} of baseline "
                    f"({delta:+.1%} mean cost) -- no material change."
                ),
                prob_over_budget=prob,
                budget=budget,
                p50=p50,
                baseline_delta=delta,
            )

    if prob <= green_max:
        signal = Signal.GREEN
        rationale = (
            f"Only {prob:.0%} chance of exceeding budget -- comfortably covered."
        )
    elif prob <= yellow_max:
        signal = Signal.YELLOW
        rationale = f"{prob:.0%} chance of exceeding budget -- watch this."
    else:
        signal = Signal.RED
        rationale = f"{prob:.0%} chance of exceeding budget -- likely overrun."

    return SignalResult(
        signal=signal,
        rationale=rationale,
        prob_over_budget=prob,
        budget=budget,
        p50=p50,
        baseline_delta=delta,
    )
