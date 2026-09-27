"""Input precedence: every rule in core/project.py, and the commands that use it."""

from datetime import date

import pytest
from click.testing import CliRunner

from budgie.budgie import cli
from budgie.core.allocation import Allocation
from budgie.core.project import (budget_source, load_observations, load_snapshot,
                                 readings_files, spent_to_date, with_readings)
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
    both = load_observations(2026, project / "actuals.csv", project / "weekly.csv")
    monthly = load_observations(2026, project / "actuals.csv")

    # The scaffold's weekly Alice ends at 180 in week 20; monthly at 60 in Feb.
    assert both["Alice"][-1] == (date(2026, 5, 17), 180)
    assert monthly["Alice"][-1] == (date(2026, 2, 28), 60)
    assert load_observations(2026) == {}


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
    # The scaffold pins `budget: 720000` and also writes a budget.csv.
    assert budget_source(load_workspace(config)) == 720000

    config.write_text(config.read_text().replace("budget: 720000", ""))
    assert budget_source(load_workspace(config)).endswith("budget.csv")
    assert budget_source(None) is None


def test_snapshot_applies_every_rule(project):
    snap = load_snapshot(project)

    assert snap.year == 2026
    # Weekly readings are the spent figure (they match the scaffold's scalar).
    assert snap.spent == {"Alice": 180, "Bob": 540}
    assert {"Alice", "Bob"} <= set(snap.allocated)
    assert snap.budget is not None and snap.budget.latest > 0


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
    # A reading that disagrees with allocations.csv's 180: both commands use it.
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
    assert "300" in alice_row and "180" not in alice_row
    draft = next((project / "out").glob("alice*"))
    assert "300" in draft.read_text()
