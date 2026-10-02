"""Input precedence: every rule in core/project.py, and the commands that use it."""

from dataclasses import replace
from datetime import date

import pytest
from click.testing import CliRunner

from budgie.budgie import cli
from budgie.core.allocation import Allocation
from budgie.core.budget import Budget
from budgie.core.calendar import productive_hours, year_span
from budgie.core.plan import AllocationPlan, PlanEntry
from budgie.core.project import (
    Snapshot,
    budget_source,
    load_observations,
    load_snapshot,
    readings_files,
    spent_to_date,
    with_readings,
)
from budgie.core.scaffold import init_workspace
from budgie.core.workspace import CONFIG_NAME, forget_workspaces, load_workspace


@pytest.fixture(autouse=True)
def _clear_workspace_cache():
    forget_workspaces()
    yield
    forget_workspaces()


@pytest.fixture
def project(tmp_path):
    init_workspace(tmp_path, year=2026)
    return tmp_path


def test_a_named_readings_file_beats_the_projects(project):
    workspace = load_workspace(project / CONFIG_NAME)

    assert readings_files(workspace, actuals="mine.csv") == ("mine.csv", None)
    actuals, weekly = readings_files(workspace)
    assert actuals.endswith("actuals.csv") and weekly.endswith("weekly.csv")
    assert readings_files(None) == (None, None)


def test_weekly_beats_monthly(project):
    both = load_observations(
        year_span(2026), project / "actuals.csv", project / "weekly.csv"
    )
    monthly = load_observations(year_span(2026), project / "actuals.csv")

    # The scaffold's weekly Alice ends at 660 in week 20; monthly at 290 in Feb.
    assert both["Alice"][-1] == (date(2026, 5, 17), 660)
    assert monthly["Alice"][-1] == (date(2026, 2, 28), 290)
    assert load_observations(year_span(2026)) == {}


def test_the_latest_reading_on_or_before_as_of_is_the_spent_figure():
    readings = {"Alice": [(date(2026, 3, 1), 50), (date(2026, 6, 1), 90)]}

    assert spent_to_date(readings) == {"Alice": 90}
    assert spent_to_date(readings, as_of=date(2026, 4, 1)) == {"Alice": 50}
    assert spent_to_date(readings, as_of=date(2026, 1, 1)) == {}


def test_a_reading_beats_hours_spent_and_no_reading_keeps_it():
    allocs = [
        Allocation(name="Alice", fte=0.5, hours_spent=10, available_hours=1000),
        Allocation(name="Bob", fte=0.5, hours_spent=20, available_hours=1000),
    ]

    out = with_readings(allocs, {"Alice": 99, "Zed": 5})

    assert [(a.name, a.hours_spent) for a in out] == [("Alice", 99), ("Bob", 20)]


def test_a_pinned_budget_beats_budget_csv(project):
    config = project / CONFIG_NAME
    # The scaffold pins `budget: 425000` and also writes a budget.csv.
    assert budget_source(load_workspace(config)) == 425000

    config.write_text(config.read_text().replace("budget: 425000", ""))
    assert budget_source(load_workspace(config)).endswith("budget.csv")
    assert budget_source(None) is None


def test_snapshot_applies_every_rule(project):
    snap = load_snapshot(project)

    assert snap.year == 2026
    # Weekly readings are the spent figure (they match the scaffold's scalar).
    assert snap.spent == {"Alice": 660, "Bob": 620}
    assert {"Alice", "Bob"} <= set(snap.allocated)
    assert snap.budget is not None and snap.budget.latest > 0


def test_snapshot_carries_the_cost_lines_and_non_labor_is_their_total(project):
    (project / "costs.csv").write_text(
        "name,amount,date,low,high\nLicence,1000,2026-03-01,800,1500\n"
    )

    snap = load_snapshot(project)

    assert [(c.name, c.low, c.high) for c in snap.costs] == [("Licence", 800, 1500)]
    assert snap.non_labor == 1000.0


def test_snapshot_without_allocations_takes_hours_from_the_plan(project):
    (project / "allocations.csv").unlink()

    snap = load_snapshot(project)

    assert snap.allocations == []
    assert snap.allocated and all(h > 0 for h in snap.allocated.values())


def test_snapshot_needs_a_year(tmp_path):
    (tmp_path / CONFIG_NAME).write_text("pto: 0\n")

    with pytest.raises(ValueError, match="year"):
        load_snapshot(tmp_path)


def test_hours_and_emails_quote_the_same_spent_hours(project, monkeypatch):
    # A reading that disagrees with allocations.csv's 660: both commands use it.
    (project / "weekly.csv").write_text("name,week,hours_to_date\nAlice,20,300\n")
    monkeypatch.chdir(project)
    runner = CliRunner()

    hours = runner.invoke(cli, ["hours"])
    emails = runner.invoke(
        cli, ["emails", "--plain", "--out-dir", str(project / "out"), "--no-preview"]
    )

    assert hours.exit_code == 0, hours.output
    assert emails.exit_code == 0, emails.output
    alice_row = next(line for line in hours.output.splitlines() if "Alice" in line)
    assert "300" in alice_row and "660" not in alice_row
    draft = next((project / "out").glob("alice*"))
    assert "300" in draft.read_text()


def test_snapshot_carries_budget_revisions_and_plan(project):
    cfg = project / CONFIG_NAME  # the scaffold pins a number; drop it for budget.csv
    cfg.write_text(cfg.read_text().replace("budget: 425000\n", ""))

    snap = load_snapshot(project)

    assert snap.budget_revisions is snap.budget and snap.budget.has_revisions
    assert snap.plan is not None and "Alice" in snap.plan.names


def test_pinned_budget_has_no_revisions_and_no_plan_csv_means_no_plan(project):
    (project / "plan.csv").unlink()
    snap = load_snapshot(project)

    assert snap.budget.latest == 425000
    assert snap.budget_revisions is None and snap.plan is None


# 2026 with no PTO: a full-time ceiling of 1,992 h over 250 working days
# (7.968 h each), and 126 of those days fall from 1 July to 31 December:
# 126 x 7.968 = 1,003.968 h.
def _alice(plan=None):
    ceiling = productive_hours(year_span(2026), pto_days=0)
    return Snapshot(
        year=2026,
        pto=0.0,
        ceiling=ceiling,
        people=[],
        allocations=[Allocation("Alice", 1.0, 100.0, 1992.0)],
        budget=Budget.flat(1000.0),
        plan=plan,
    )


def test_what_if_budget_only_replaces_the_budget_with_a_flat_one():
    snap = _alice()

    after = snap.what_if(budget=800.0)

    assert after.budget.latest == 800.0 and after.budget_revisions is None
    assert after.allocated == snap.allocated == {"Alice": 1992.0}


def test_what_if_a_leave_entry_removes_the_hours_after_it():
    snap = _alice()

    after = snap.what_if(plan_entries=[
        PlanEntry("Alice", date(2026, 1, 1), 1.0),
        PlanEntry("Alice", date(2026, 7, 1), 0.0),
    ])  # fmt: skip

    assert after.allocated == {"Alice": pytest.approx(1992.0 - 1003.968)}
    assert after.spent == {"Alice": 100.0}
    assert len(after.plan.entries) == 3  # Alice's flat-FTE seed + her two entries


def test_what_if_appends_to_the_existing_plan_and_adds_new_people():
    base = AllocationPlan((PlanEntry("Alice", date(2026, 1, 1), 1.0),))

    after = _alice(base).what_if(plan_entries=[
        PlanEntry("Alice", date(2026, 7, 1), 0.0),
        PlanEntry("Bob", date(2026, 7, 1), 0.5),
    ])  # fmt: skip

    assert after.allocated == {
        "Alice": pytest.approx(988.032),
        "Bob": pytest.approx(501.984),
    }
    assert after.spent["Bob"] == 0.0
    assert len(after.plan.entries) == 3


def test_what_if_without_a_leave_allocations_and_plan_only_snapshots():
    only_plan = replace(_alice(), allocations=[])

    after = only_plan.what_if(plan_entries=[PlanEntry("Bob", date(2026, 7, 1), 1.0)])

    assert after.allocated == {"Bob": pytest.approx(1003.968)}


def _bob(plan=None):
    # Bob is only in allocations.csv: flat 0.5 FTE of the 1,992 h ceiling.
    return replace(
        _alice(plan),
        allocations=[Allocation("Bob", 0.5, 0.0, 1992.0)],
    )


def test_what_if_carries_an_allocation_only_person_at_flat_fte_until_the_change():
    after = _bob().what_if(plan_entries=[PlanEntry("Bob", date(2026, 7, 1), 0.0)])

    # Jan 1 - Jun 30 is 124 working days: 0.5 x 124 x 7.968 = 494.016 h kept.
    assert after.allocated == {"Bob": pytest.approx(494.016)}
    assert len(after.plan.entries) == 2


def test_what_if_does_not_seed_someone_already_in_the_plan():
    base = AllocationPlan((PlanEntry("Bob", date(2026, 3, 1), 1.0),))

    after = _bob(base).what_if(plan_entries=[PlanEntry("Bob", date(2026, 7, 1), 0.0)])

    assert len(after.plan.entries) == 2  # no Jan 1 seed
    # Plan only: nothing before Mar 1, then 1.0 FTE to Jun 30 (85 working days).
    assert after.allocated == {"Bob": pytest.approx(85 * 7.968)}


def test_what_if_a_jan_1_change_overrides_the_seed():
    after = _bob().what_if(plan_entries=[PlanEntry("Bob", date(2026, 1, 1), 1.0)])

    assert after.allocated == {"Bob": pytest.approx(1992.0)}


def test_what_if_leaves_the_original_untouched():
    snap = _alice()

    snap.what_if(budget=1.0, plan_entries=[PlanEntry("Alice", date(2026, 7, 1), 0.0)])

    assert snap.budget.latest == 1000.0 and snap.plan is None
    assert snap.allocated == {"Alice": 1992.0}
    assert snap.allocations[0].fte == 1.0
