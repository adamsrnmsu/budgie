"""One model: plan.csv sets the hours, people.csv the rate and the spread."""

import re
from datetime import date

import pytest
from click.testing import CliRunner

from budgie.budgie import cli
from budgie.core.calendar import productive_hours
from budgie.core.forecast import forecast
from budgie.core.loader import load_people
from budgie.core.person import HoursEstimate, Person
from budgie.core.plan import AllocationPlan, PlanEntry
from budgie.core.project import load_snapshot, people_on_plan
from budgie.core.scaffold import init_workspace
from budgie.core.workspace import forget_workspaces

YEAR = 2026
PH = productive_hours(YEAR)  # 1992 available hours at 1.0 FTE
FULL = AllocationPlan((PlanEntry("Alice", date(YEAR, 1, 1), 1.0),))


@pytest.fixture(autouse=True)
def _clear_workspace_cache():
    forget_workspaces()
    yield
    forget_workspaces()


@pytest.fixture
def project(tmp_path):
    init_workspace(tmp_path, year=YEAR)
    return tmp_path


def _people(tmp_path, text):
    path = tmp_path / "people.csv"
    path.write_text(text)
    return load_people(path, productive_hours=PH)


# --- people.csv forms -----------------------------------------------------


def test_plain_form_is_a_rate_and_a_percent_spread(tmp_path):
    alice, bob = _people(
        tmp_path, "name,hourly_cost,under,over,pto_days\nAlice,95,10,5,3\nBob,110,,,\n"
    )
    assert alice.spread == pytest.approx((0.9, 1.05))
    assert alice.hours == HoursEstimate.constant(0.0)
    assert alice.pto_days == 3
    assert bob.spread == (1.0, 1.0) and bob.pto_days is None


def test_plain_form_rejects_impossible_percentages(tmp_path):
    with pytest.raises(ValueError, match="under must be 0-100"):
        _people(tmp_path, "name,hourly_cost,under\nAlice,95,120\n")


def test_util_form_records_its_spread_and_keeps_its_hours(tmp_path):
    (alice,) = _people(
        tmp_path,
        "name,hourly_cost,util_low,util_mode,util_high\nAlice,95,0.8,0.9,0.98\n",
    )
    assert alice.spread == pytest.approx((0.8 / 0.9, 0.98 / 0.9))
    assert alice.hours.mode == pytest.approx(1992 * 0.9)  # no plan: as before


def test_util_mode_zero_has_no_spread(tmp_path):
    (alice,) = _people(
        tmp_path, "name,hourly_cost,util_low,util_mode,util_high\nAlice,95,0,0,0\n"
    )
    assert alice.spread is None


def test_a_half_written_form_is_still_an_error(tmp_path):
    with pytest.raises(ValueError, match="all three"):
        _people(tmp_path, "name,hourly_cost,util_mode\nAlice,95,0.9\n")


# --- people_on_plan -------------------------------------------------------


def _person(name="Alice", spread=(0.9, 1.1), pto_days=None):
    return Person(name, 100.0, HoursEstimate.constant(0.0), spread, pto_days)


def test_planned_hours_come_from_the_plan_scaled_by_the_spread():
    (alice,), warnings = people_on_plan([_person()], FULL, YEAR)
    assert alice.hours.mode == pytest.approx(1992)
    assert (alice.hours.low, alice.hours.high) == pytest.approx(
        (1992 * 0.9, 1992 * 1.1)
    )
    assert warnings == []


def test_a_rate_with_no_plan_rows_is_zero_hours_and_says_so():
    (_, bob), warnings = people_on_plan([_person(), _person("Bob")], FULL, YEAR)
    assert bob.hours == HoursEstimate.constant(0.0)
    assert warnings == [
        "Bob has a rate in people.csv but no rows in plan.csv, so 0 hours."
    ]


def test_a_plan_name_with_no_rate_is_not_costed_and_a_case_slip_is_named():
    plan = AllocationPlan((*FULL.entries, PlanEntry("alice", date(YEAR, 6, 1), 0.5)))
    _, warnings = people_on_plan([_person()], plan, YEAR)
    expected = (
        "alice is in plan.csv but has no rate in people.csv (people.csv has "
        "'Alice'), so not costed."
    )
    assert warnings == [expected]


def test_zero_spread_falls_back_to_the_plan_alone():
    (alice,), warnings = people_on_plan([_person(spread=None)], FULL, YEAR)
    h = alice.hours
    assert (h.low, h.mode, h.high) == pytest.approx((1992, 1992, 1992))
    assert "no spread" in warnings[0]


def test_pto_comes_from_people_then_allocations_then_the_team():
    ten = productive_hours(YEAR, pto_days=10).available_hours
    (alice,), _ = people_on_plan([_person()], FULL, YEAR, pto_by_name={"Alice": 10})
    assert alice.hours.mode == pytest.approx(ten)

    (alice,), warnings = people_on_plan(
        [_person(pto_days=10)], FULL, YEAR, pto=5, pto_by_name={"Alice": 3}
    )
    assert alice.hours.mode == pytest.approx(ten)
    assert "using people.csv" in warnings[0]


def test_no_plan_leaves_the_team_and_flags_a_plain_rate_with_no_hours():
    util = Person("Bob", 1.0, HoursEstimate(1, 2, 3))
    people, warnings = people_on_plan([_person(), util], None, YEAR)
    assert people == [_person(), util]
    assert warnings == [
        "Alice has a rate but no hours: people.csv gives none and there is no plan.csv."
    ]


# --- the Snapshot ---------------------------------------------------------


def _cost(snap):
    return forecast(snap.people).labor_cost


def test_a_plan_row_moves_the_snapshots_cost(project):
    before = load_snapshot(project)
    with (project / "plan.csv").open("a") as plan:
        plan.write(f"Bob,{YEAR}-07-01,0\n")

    after = load_snapshot(project)

    bob = {p.name: p for p in after.people}["Bob"]
    assert bob.hours.mode == pytest.approx(after.allocated["Bob"])
    assert _cost(after) < _cost(before)
    assert after.warnings == []


def test_a_plan_matching_util_mode_changes_nothing(project):
    # The scaffold's plan says what its util_mode says, so hours agree exactly.
    snap = load_snapshot(project)
    for p in snap.people:
        assert p.hours.mode == pytest.approx(snap.allocated[p.name])


def test_what_if_and_with_plan_move_cost_not_just_hours(project):
    snap = load_snapshot(project)
    leave = PlanEntry("Bob", date(YEAR, 7, 1), 0.0)

    after = snap.what_if(plan_entries=[leave])
    assert _cost(after) < _cost(snap)
    assert snap.with_plan(after.plan).people == after.people

    hired = snap.what_if(plan_entries=[PlanEntry("Zed", date(YEAR, 7, 1), 1.0)])
    assert _cost(hired) == pytest.approx(_cost(snap))
    assert any("Zed is in plan.csv but has no rate" in w for w in hired.warnings)


def test_an_allocation_without_plan_rows_keeps_its_flat_fte(project):
    (project / "plan.csv").write_text(
        f"name,effective_date,fte\nAlice,{YEAR}-01-01,0.9\n"
    )

    snap = load_snapshot(project)

    bob = {p.name: p for p in snap.people}["Bob"]
    assert bob.hours.mode == pytest.approx(snap.allocated["Bob"])
    assert bob.hours.mode > 0
    assert snap.warnings == [
        "Bob has no rows in plan.csv; using allocations.csv fte 0.85 from Jan 1."
    ]


def test_without_a_plan_the_numbers_are_unchanged(project):
    (project / "plan.csv").unlink()
    snap = load_snapshot(project)
    people = load_people(project / "people.csv", productive_hours=PH)
    assert snap.people == people
    assert snap.warnings == []


# --- the CLI follows the plan ---------------------------------------------


def _p50(output):
    return float(re.search(r"P50 \$([\d,]+)", output).group(1).replace(",", ""))


def test_a_plan_row_moves_the_cli_forecast_and_monthly(project, monkeypatch):
    monkeypatch.chdir(project)
    runner = CliRunner()
    args = ["--seed", "1", "--iterations", "2000"]
    before = runner.invoke(cli, ["forecast", *args])
    with (project / "plan.csv").open("a") as plan:
        plan.write(f"Bob,{YEAR}-07-01,0\nZed,{YEAR}-07-01,1\n")

    after = runner.invoke(cli, ["forecast", *args])
    monthly = runner.invoke(cli, ["monthly", *args])

    assert before.exit_code == after.exit_code == monthly.exit_code == 0, after.output
    assert _p50(after.output) < _p50(before.output)
    assert "Zed is in plan.csv but has no rate" in after.output
    assert "Zed is in plan.csv but has no rate" in monthly.output


def test_the_bundled_sample_ignores_plans(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no project: sample team, no plan applied
    result = CliRunner().invoke(cli, ["forecast", "--seed", "1"])
    assert result.exit_code == 0, result.output
    assert "⚠" not in result.output
