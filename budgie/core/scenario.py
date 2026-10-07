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
from budgie.core.calendar import productive_hours, year_span, year_start_month
from budgie.core.costs import load_costs
from budgie.core.eac import at_completion
from budgie.core.forecast import Forecast
from budgie.core.forecast import forecast as run_forecast
from budgie.core.loader import load_people
from budgie.core.montecarlo import SimulationResult, simulate
from budgie.core.project import load_snapshot
from budgie.core.signals import SignalResult, evaluate
from budgie.core.workspace import CONFIG_NAME, load_workspace

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


def _project_snapshot(workspace, spec, config, base_dir):
    """The project's Snapshot for one scenario, or a one-line error.

    ``year`` and ``pto`` vary the project's own settings. A different people,
    costs or year_start file/value has no counterpart on the project's
    Snapshot, so it is refused instead of silently ignored.
    """
    name = spec.get("name", "?")

    def same(key: str, given, theirs) -> None:
        if given and Path(given).resolve() != theirs:
            raise ValueError(
                f"scenario {name!r}: {key} {given} is not this project's "
                f"{key} file; inside a project a scenario can only change "
                "year and pto."
            )

    def theirs(key: str) -> Path | None:
        found = workspace.resolve(key)
        return Path(found).resolve() if found else None

    same(
        "people",
        spec["people"] and _resolve(spec["people"], base_dir),
        theirs("people"),
    )
    same(
        "costs",
        config.get("costs") and _resolve(config["costs"], base_dir),
        theirs("costs"),
    )
    given = spec.get("year_start", config.get("year_start"))
    if given and given != workspace.setting("year_start", "01-01"):
        raise ValueError(
            f"scenario {name!r}: year_start {given} is not this project's; "
            "inside a project a scenario can only change year and pto."
        )
    return load_snapshot(
        workspace.root,
        year=int(spec["year"]),
        pto=float(spec["pto"]) if "pto" in spec else None,
    )


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
    year_start = str(config.get("year_start", "01-01"))
    try:
        year_start_month(year_start)
    except ValueError as exc:
        raise ValueError(f"{config_path.name}: {exc}") from None
    specs = config["scenarios"]
    if not specs:
        raise ValueError("config must define at least one scenario")

    # A budgie.yaml beside the config makes each scenario a variant of that
    # project, with its plan.csv and readings; without one there is only people.
    workspace = (
        load_workspace(base_dir / CONFIG_NAME)
        if (base_dir / CONFIG_NAME).is_file()
        else None
    )

    results: list[ScenarioResult] = []
    baseline_total: float | None = None
    baseline_sim: SimulationResult | None = None

    for spec in specs:
        if "year" not in spec:
            raise ValueError(
                f"{config_path}: scenario {spec.get('name', '?')!r} has no year"
            )
        try:
            span = year_span(int(spec["year"]), str(spec.get("year_start", year_start)))
        except ValueError as exc:
            raise ValueError(
                f"{config_path.name}: scenario {spec.get('name', '?')!r}: {exc}"
            ) from None
        if workspace is not None:
            snap = _project_snapshot(workspace, spec, config, base_dir)
            # Same steps as `budgie forecast`: plan hours, then readings.
            people = at_completion(
                snap.people, snap.readings, snap.span, plan=snap.plan
            ).people
            costs = snap.costs
            it = int(config.get("iterations", snap.iterations))
            sd = config.get("seed", snap.seed)
        else:
            ph = productive_hours(span, pto_days=float(spec.get("pto", 0.0)))
            costs = (
                load_costs(_resolve(cost_spec, base_dir), span=span)
                if cost_spec
                else []
            )
            people = load_people(
                _resolve(spec["people"], base_dir), productive_hours=ph
            )
            it, sd = iterations, seed
        det = run_forecast(people, costs=costs)
        sim = simulate(people, iterations=it, seed=sd, costs=costs)
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
