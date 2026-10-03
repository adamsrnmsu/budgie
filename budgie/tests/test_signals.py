from pathlib import Path

from budgie.core.montecarlo import simulate
from budgie.core.person import HoursEstimate, Person
from budgie.core.scenario import run_scenarios
from budgie.core.signals import Signal, evaluate

TESTS_DIR = Path(__file__).resolve().parent


def _team():
    return [
        Person("A", 100, HoursEstimate(900, 1000, 1100)),
        Person("B", 50, HoursEstimate(1800, 1900, 2000)),
    ]


def test_green_when_budget_well_above():
    sim = simulate(_team(), iterations=5000, seed=1)
    # Budget far above any plausible outcome -> near-zero overrun -> GREEN.
    res = evaluate(sim, budget=sim.percentile(90) + 100_000)
    assert res.signal is Signal.GREEN
    assert res.prob_over_budget < 0.10


def test_red_when_budget_below_median():
    sim = simulate(_team(), iterations=5000, seed=1)
    res = evaluate(sim, budget=sim.percentile(10) - 50_000)
    assert res.signal is Signal.RED
    assert res.prob_over_budget > 0.40


def test_yellow_in_between():
    sim = simulate(_team(), iterations=5000, seed=1)
    res = evaluate(sim, budget=sim.percentile(75))
    assert res.signal is Signal.YELLOW


def test_blue_when_unchanged_from_baseline():
    baseline = simulate(_team(), iterations=5000, seed=1)
    current = simulate(_team(), iterations=5000, seed=2)  # same team, different seed
    res = evaluate(current, budget=1_000_000, baseline=baseline)
    assert res.signal is Signal.BLUE
    assert res.baseline_delta is not None


def test_run_scenarios_from_config():
    results, budget = run_scenarios(TESTS_DIR / "scenarios.yaml")
    assert budget == 800000
    assert results[0].name == "Baseline"
    assert results[0].cost_delta == 0
    # PTO scenario is cheaper than baseline.
    assert results[1].cost_delta < 0


def test_run_scenarios_per_person_pto(tmp_path):
    # A pto_days column needs the ProductiveHours breakdown, not a bare number.
    (tmp_path / "people.csv").write_text(
        "name,hourly_cost,util_low,util_mode,util_high,pto_days\n"
        "A,100,0.8,0.9,0.95,10\n"
        "B,100,0.8,0.9,0.95,30\n"
    )
    (tmp_path / "s.yaml").write_text(
        "budget: 1000000\niterations: 100\nseed: 1\n"
        "scenarios:\n  - name: Base\n    year: 2026\n    people: people.csv\n"
    )
    (res,), _ = run_scenarios(tmp_path / "s.yaml")
    a, b = res.forecast.line_items
    assert a.cost > b.cost  # B's extra PTO shrinks their hours
