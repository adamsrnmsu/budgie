"""
Scenario comparison.

A scenario is a named set of planning assumptions (which team, which year, how
much PTO, how many iterations). Running several lets you compare "what-if"
budgets side by side. The first scenario is treated as the baseline: every other
scenario's cost delta and stoplight signal are measured against it.

Config shape (YAML), consumed by the ``budgie scenario`` command::

    budget: 800000
    iterations: 10000
    seed: 42
    scenarios:
      - name: Baseline
        people: tests/team.csv
        year: 2026
        pto: 0
      - name: With 15 PTO
        people: tests/team.csv
        year: 2026
        pto: 15
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from budgie.core.budget import coerce_budget
from budgie.core.calendar import productive_hours
from budgie.core.costs import load_costs
from budgie.core.forecast import Forecast
from budgie.core.forecast import forecast as run_forecast
from budgie.core.loader import load_people
from budgie.core.montecarlo import SimulationResult, simulate
from budgie.core.signals import SignalResult, evaluate

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    forecast: Forecast
    sim: SimulationResult
    signal: SignalResult
    cost_delta: float  # deterministic total vs the baseline scenario (0 for baseline)


def _resolve(path: str, base_dir: Path) -> Path:
    """Resolve a scenario's people path relative to the config file's dir."""
    p = Path(path)
    return p if p.is_absolute() else base_dir / p


def run_scenarios(config_path: str | Path) -> tuple[list[ScenarioResult], float]:
    """Run every scenario in a config file; return results and the budget.

    The first scenario is the baseline for cost deltas and BLUE "no change"
    signals.
    """
    config_path = Path(config_path)
    config = yaml.safe_load(config_path.read_text())
    base_dir = config_path.parent

    # `budget:` accepts a plain number (as before), a list of dated revisions,
    # or a path to a revisions CSV.
    budget_spec = config["budget"]
    if isinstance(budget_spec, str):
        budget_spec = _resolve(budget_spec, base_dir)
    budget_obj = coerce_budget(budget_spec)
    budget = budget_obj.latest
    iterations = int(config.get("iterations", 10_000))
    seed = config.get("seed")
    cost_spec = config.get("costs")
    costs = load_costs(_resolve(cost_spec, base_dir)) if cost_spec else []
    specs = config["scenarios"]
    if not specs:
        raise ValueError("config must define at least one scenario")

    results: list[ScenarioResult] = []
    baseline_total: float | None = None
    baseline_sim: SimulationResult | None = None

    for spec in specs:
        ph = productive_hours(
            int(spec.get("year", 2026)), pto_days=float(spec.get("pto", 0.0))
        )
        people = load_people(_resolve(spec["people"], base_dir), productive_hours=ph)
        det = run_forecast(people, costs=costs)
        sim = simulate(people, iterations=iterations, seed=seed, costs=costs)
        signal = evaluate(sim, budget, baseline=baseline_sim)
        logger.info(
            "Scenario %r: total=%.0f signal=%s",
            spec.get("name", "?"),
            det.total_cost,
            signal.signal.value,
        )

        if baseline_total is None:
            baseline_total = det.total_cost
            baseline_sim = sim

        results.append(
            ScenarioResult(
                name=str(spec.get("name", f"Scenario {len(results) + 1}")),
                forecast=det,
                sim=sim,
                signal=signal,
                cost_delta=det.total_cost - baseline_total,
            )
        )

    return results, budget
