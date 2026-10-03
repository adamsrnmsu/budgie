"""Estimate at completion: spent to date plus a forecast of only what's left."""

import logging
from datetime import date
from pathlib import Path

import pytest
from click.testing import CliRunner

from budgie.budgie import cli
from budgie.core.actuals import monthly_to_observations
from budgie.core.allocation import Allocation
from budgie.core.burndown import burndown
from budgie.core.calendar import year_span
from budgie.core.eac import at_completion, elapsed_fraction
from budgie.core.forecast import forecast
from budgie.core.montecarlo import simulate
from budgie.core.monthly import load_monthly_actuals
from budgie.core.person import HoursEstimate, Person
from budgie.core.plan import AllocationPlan, PlanEntry
from budgie.core.workspace import forget_workspaces

TESTS_DIR = Path(__file__).resolve().parent

ALICE = Person("Alice", 100.0, HoursEstimate(800, 1000, 1200))
BOB = Person("Bob", 50.0, HoursEstimate(400, 500, 900))
# 2026 has 250 working days; 124 of them fall on or before Jun 30
# (129 weekdays minus New Year, MLK, Presidents, Memorial and Juneteenth).
JUN30 = date(2026, 6, 30)
F_JUN30 = 124 / 250


@pytest.fixture(autouse=True)
def _clear_workspace_cache():
    forget_workspaces()
    yield
    forget_workspaces()


# --- budgie-azj: trailing empty months are not readings --------------------


def test_monthly_observations_stop_at_the_last_reported_month():
    months = load_monthly_actuals(TESTS_DIR / "actuals.csv")
    obs = monthly_to_observations(year_span(2026), next(iter(months.values())))
    # Data runs through July. Before the fix this was Dec 31.
    assert obs[-1] == (date(2026, 7, 31), 1040.0)


def test_monthly_observations_keep_an_empty_month_in_the_middle():
    obs = monthly_to_observations(year_span(2026), [10, 0, 5] + [0] * 9)
    assert obs == [
        (date(2026, 1, 31), 10),
        (date(2026, 2, 28), 10),
        (date(2026, 3, 31), 15),
    ]
    assert monthly_to_observations(year_span(2026), [0.0] * 12) == []


def test_monthly_actuals_no_longer_pin_the_burndown_to_december():
    months = load_monthly_actuals(TESTS_DIR / "actuals.csv")
    name, hours = next(iter(months.items()))
    alloc = Allocation(name=name, fte=0.25, hours_spent=0, available_hours=1992)
    status = burndown(
        alloc,
        year_span(2026),
        observations=monthly_to_observations(year_span(2026), hours),
    )
    assert status.as_of == date(2026, 7, 31)
    assert status.required_pace.workdays_remaining > 0


# --- elapsed_fraction ------------------------------------------------------


def test_elapsed_fraction_ends_and_a_hand_checked_middle():
    assert elapsed_fraction(year_span(2026), date(2026, 1, 1)) == 0.0  # a holiday
    assert elapsed_fraction(year_span(2026), date(2026, 1, 2)) == 1 / 250
    assert elapsed_fraction(year_span(2026), JUN30) == F_JUN30
    assert elapsed_fraction(year_span(2026), date(2026, 12, 31)) == 1.0


def test_elapsed_fraction_clamps_outside_the_year():
    assert elapsed_fraction(year_span(2026), date(2025, 6, 1)) == 0.0
    assert elapsed_fraction(year_span(2026), date(2027, 6, 1)) == 1.0


# --- at_completion ---------------------------------------------------------


def test_person_without_observations_is_unchanged():
    eac = at_completion([ALICE, BOB], {"Alice": [(JUN30, 300.0)]}, year_span(2026))
    assert eac.people[1] is BOB
    assert eac.readings == {"Alice": (JUN30, 300.0)}


def test_forecast_total_is_spent_plus_the_remaining_share_of_the_mode():
    eac = at_completion([ALICE], {"Alice": [(JUN30, 300.0)]}, year_span(2026))
    left = 1 - F_JUN30
    hours = eac.people[0].hours
    assert (hours.low, hours.mode, hours.high) == pytest.approx(
        (300 + 800 * left, 300 + 1000 * left, 300 + 1200 * left)
    )
    assert forecast(eac.people).total_cost == pytest.approx(100 * (300 + 1000 * left))


def test_year_end_reading_leaves_nothing_to_simulate():
    eac = at_completion(
        [ALICE], {"Alice": [(date(2026, 12, 31), 950.0)]}, year_span(2026)
    )
    sim = simulate(eac.people, iterations=500, seed=1)
    assert sim.std == 0
    assert sim.mean == pytest.approx(95_000)


def test_reading_at_the_start_of_the_year_is_nearly_the_plan():
    eac = at_completion([ALICE], {"Alice": [(date(2026, 1, 1), 0.0)]}, year_span(2026))
    assert eac.people[0].hours == ALICE.hours


def test_as_of_filters_later_readings_but_the_reading_sets_the_date():
    obs = {"Alice": [(date(2026, 3, 31), 200.0), (JUN30, 300.0)]}
    eac = at_completion([ALICE], obs, year_span(2026), as_of=date(2026, 5, 15))
    assert eac.readings["Alice"] == (date(2026, 3, 31), 200.0)
    left = 1 - elapsed_fraction(year_span(2026), date(2026, 3, 31))
    assert eac.people[0].hours.mode == pytest.approx(200 + 1000 * left)
    # Nothing on or before the as-of date: back to the plan.
    early = at_completion([ALICE], obs, year_span(2026), as_of=date(2026, 1, 15))
    assert early.people == [ALICE]
    assert early.readings == {}


def test_unknown_name_warns(caplog):
    with caplog.at_level(logging.WARNING, logger="budgie.core.eac"):
        at_completion([ALICE], {"Zed": [(JUN30, 10.0)]}, year_span(2026))
    assert "Zed" in caplog.text


def test_simulated_spread_narrows_and_percentiles_stay_ordered():
    team = [ALICE, BOB]
    obs = {"Alice": [(JUN30, 480.0)], "Bob": [(JUN30, 260.0)]}
    plan = simulate(team, iterations=5000, seed=7)
    eac = simulate(
        at_completion(team, obs, year_span(2026)).people, iterations=5000, seed=7
    )
    pct = eac.percentiles()
    assert pct[10] <= pct[50] <= pct[90]
    # Same seed, same draws: the spread shrinks by exactly the share left.
    assert eac.std == pytest.approx(plan.std * (1 - F_JUN30))


# --- the share left follows plan.csv (budgie-tzn) ------------------------


def _alice_plan(*rows):
    return AllocationPlan(
        tuple(PlanEntry("Alice", date.fromisoformat(d), f) for d, f in rows)
    )


def test_july_joiner_has_all_of_their_plan_left_on_june_30():
    plan = _alice_plan(("2026-07-01", 1.0))
    eac = at_completion([ALICE], {"Alice": [(JUN30, 0.0)]}, year_span(2026), plan=plan)
    assert eac.people[0].hours == ALICE.hours  # not 1000 x (1 - 124/250)


def test_july_joiner_mid_plan_uses_the_plans_working_days():
    plan = _alice_plan(("2026-07-01", 1.0))
    sep30 = date(2026, 9, 30)
    eac = at_completion(
        [ALICE], {"Alice": [(sep30, 200.0)]}, year_span(2026), plan=plan
    )
    # Jul 1-Sep 30 is 64 of the 126 working days Jul 1-Dec 31.
    assert eac.people[0].hours.mode == pytest.approx(200 + 1000 * 62 / 126)


def test_ended_plan_leaves_only_what_was_spent():
    plan = _alice_plan(("2026-01-01", 1.0), ("2026-09-01", 0.0))
    oct15 = date(2026, 10, 15)
    eac = at_completion(
        [ALICE], {"Alice": [(oct15, 1500.0)]}, year_span(2026), plan=plan
    )
    hours = eac.people[0].hours
    assert (hours.low, hours.mode, hours.high) == pytest.approx((1500, 1500, 1500))


def test_person_the_plan_does_not_mention_keeps_working_days():
    plan = _alice_plan(("2026-07-01", 1.0))
    obs = {"Bob": [(JUN30, 250.0)]}
    with_plan = at_completion([BOB], obs, year_span(2026), plan=plan)
    assert with_plan.people == at_completion([BOB], obs, year_span(2026)).people


# --- CLI -------------------------------------------------------------------


def _forecast(*args):
    people = str(TESTS_DIR / "team.csv")
    result = CliRunner().invoke(
        cli, ["forecast", "--people", people, "--seed", "1", *args]
    )
    assert result.exit_code == 0, result.output
    return result.output


def test_cli_weekly_adds_the_spent_column(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no project: only what's on the command line
    out = _forecast("--weekly", str(TESTS_DIR / "weekly.csv"))
    assert "Estimate at completion" in out
    assert "Spent" in out
    assert "2026-07-19" in out  # ISO week 29 ends on that Sunday
    assert "Deterministic forecast" not in out


def test_cli_ignore_actuals_is_the_plain_forecast(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    plain = _forecast()
    assert "Deterministic forecast" in plain
    assert "Spent" not in plain
    assert (
        _forecast("--weekly", str(TESTS_DIR / "weekly.csv"), "--ignore-actuals")
        == plain
    )


def test_cli_picks_up_the_projects_actuals(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    assert runner.invoke(cli, ["init", "fy26"]).exit_code == 0
    forget_workspaces()
    eac = runner.invoke(cli, ["forecast"])
    assert eac.exit_code == 0, eac.output
    assert "Estimate at completion" in eac.output
    plan = runner.invoke(cli, ["forecast", "--ignore-actuals"])
    assert "Deterministic forecast" in plan.output


def test_cli_forecast_uses_the_projects_plan(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    assert runner.invoke(cli, ["init", "fy26"]).exit_code == 0
    forget_workspaces()
    before = runner.invoke(cli, ["forecast", "--seed", "1"])
    assert before.exit_code == 0, before.output
    # Alice's plan ends May 1, before her week-20 reading: nothing left to forecast.
    (tmp_path / "budget" / "fy26" / "plan.csv").write_text(
        "name,effective_date,fte\n"
        "Alice,2026-01-01,0.90\nAlice,2026-05-01,0.0\nBob,2026-01-01,0.85\n"
    )
    forget_workspaces()
    after = runner.invoke(cli, ["forecast", "--seed", "1"])
    assert after.exit_code == 0, after.output
    assert after.output != before.output
