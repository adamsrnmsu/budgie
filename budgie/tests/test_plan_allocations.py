"""plan.csv feeding allocations: one source of truth for allocated hours."""

import logging
from datetime import date

import pytest
from click.testing import CliRunner

from budgie.budgie import cli
from budgie.core.allocation import load_allocations
from budgie.core.calendar import productive_hours, year_span
from budgie.core.plan import AllocationPlan, PlanEntry
from budgie.core.scaffold import init_workspace
from budgie.core.workspace import forget_workspaces

YEAR = 2026


@pytest.fixture(autouse=True)
def _clear_workspace_cache():
    forget_workspaces()
    yield
    forget_workspaces()


def _plan(*rows):
    return AllocationPlan(
        entries=tuple(PlanEntry(n, date.fromisoformat(d), f) for n, d, f in rows)
    )


def _csv(tmp_path, body):
    path = tmp_path / "allocations.csv"
    path.write_text(body)
    return path


def _by_name(allocs):
    return {a.name: a for a in allocs}


def test_plan_overrides_the_flat_fte(tmp_path):
    path = _csv(tmp_path, "name,fte,hours_spent\nBob,0.50,100\n")
    ph = productive_hours(year_span(YEAR))
    plan = _plan(("Bob", "2026-01-01", 0.5), ("Bob", "2026-09-01", 0.0))

    flat = load_allocations(path, ph)[0]
    planned = load_allocations(path, ph, plan=plan)[0]

    assert flat.allocated_hours == pytest.approx(996)
    assert planned.allocated_hours == pytest.approx(plan.allocated_hours("Bob", YEAR))
    assert round(planned.allocated_hours) == 665
    assert planned.fte < flat.fte
    # The invariant Allocation is built on still holds.
    assert planned.allocated_hours == planned.fte * planned.available_hours
    assert planned.hours_spent == 100


def test_constant_fte_reconciles_to_the_no_plan_number(tmp_path):
    path = _csv(tmp_path, "name,fte,hours_spent\nAlice,0.25,0\n")
    ph = productive_hours(year_span(YEAR))

    flat = load_allocations(path, ph)[0]
    planned = load_allocations(path, ph, plan=_plan(("Alice", "2026-01-01", 0.25)))[0]

    assert flat.allocated_hours == pytest.approx(498)
    assert planned.allocated_hours == pytest.approx(flat.allocated_hours)
    assert planned.fte == pytest.approx(0.25)


def test_per_row_pto_days_is_honoured(tmp_path):
    path = _csv(tmp_path, "name,fte,hours_spent,pto_days\nBob,0.5,0,20\nAl,0.5,0,\n")
    ph = productive_hours(year_span(YEAR), pto_days=5)
    plan = _plan(("Bob", "2026-01-01", 0.5), ("Al", "2026-01-01", 0.5))

    allocs = _by_name(load_allocations(path, ph, plan=plan))

    # Bob's own 20 days, not the team's 5; Al, who left it blank, gets the 5.
    assert allocs["Bob"].available_hours == pytest.approx(ph.available_for(20))
    assert allocs["Bob"].allocated_hours == pytest.approx(0.5 * ph.available_for(20))
    assert allocs["Al"].allocated_hours == pytest.approx(0.5 * ph.available_hours)


def test_person_missing_from_the_plan_keeps_flat_fte(tmp_path, caplog):
    path = _csv(tmp_path, "name,fte,hours_spent\nAlice,0.25,0\nZed,0.40,10\n")
    plan = _plan(("Alice", "2026-01-01", 0.25))

    with caplog.at_level(logging.WARNING, logger="budgie.core.allocation"):
        allocs = _by_name(
            load_allocations(path, productive_hours(year_span(YEAR)), plan=plan)
        )

    assert allocs["Zed"].fte == 0.40
    assert "Zed" in caplog.text
    assert "not in the plan" in caplog.text


def test_person_only_in_the_plan_appears_with_nothing_spent(tmp_path, caplog):
    path = _csv(tmp_path, "name,fte,hours_spent\nAlice,0.25,0\n")
    ph = productive_hours(year_span(YEAR))
    plan = _plan(
        ("Carol", "2026-07-15", 0.5),
        ("Alice", "2026-01-01", 0.25),
        ("Dave", "2026-01-01", 1.0),
    )

    with caplog.at_level(logging.WARNING, logger="budgie.core.allocation"):
        allocs = load_allocations(path, ph, plan=plan)

    # File order first, then the plan's own order for the newcomers.
    assert [a.name for a in allocs] == ["Alice", "Carol", "Dave"]
    carol = allocs[1]
    assert carol.hours_spent == 0.0
    assert carol.email is None
    assert carol.available_hours == ph.available_hours
    assert round(carol.allocated_hours) == 466
    assert "Carol" in caplog.text
    assert "no spend recorded" in caplog.text


def test_a_float_ceiling_with_a_plan_raises(tmp_path):
    path = _csv(tmp_path, "name,fte,hours_spent\nAlice,0.25,0\n")

    with pytest.raises(ValueError, match="ProductiveHours"):
        load_allocations(path, 1992.0, plan=_plan(("Alice", "2026-01-01", 0.25)))


def test_no_plan_is_unchanged(tmp_path):
    path = _csv(tmp_path, "name,fte,hours_spent,email\nAlice,0.25,180,a@x.org\n")

    (from_float,) = load_allocations(path, 1992.0)
    (explicit_none,) = load_allocations(
        path, productive_hours(year_span(YEAR)), plan=None
    )

    assert from_float.fte == 0.25
    assert from_float.allocated_hours == 498
    assert from_float.email == "a@x.org"
    assert explicit_none == from_float


def test_hours_in_a_scaffolded_project_uses_the_plan(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    assert runner.invoke(cli, ["init", "fy26"]).exit_code == 0
    forget_workspaces()

    result = runner.invoke(cli, ["hours"])

    assert result.exit_code == 0, result.output
    # The scaffold plans Alice at 0.90 and Bob at 0.85 for the whole year, so
    # allocated hours are 0.90 x 1992 = 1793 and 0.85 x 1992 = 1693.
    assert "1,793" in result.output
    assert "1,693" in result.output
    assert "plan.csv" in result.output


def test_hours_without_a_project_never_borrows_the_sample_plan(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["hours"])

    assert result.exit_code == 0, result.output
    assert "year average" not in result.output


def test_plan_view_uses_the_same_pto_as_hours(tmp_path, monkeypatch):
    # A person's own pto_days. `plan` used to know only the team figure, so it
    # and `hours` disagreed about the same plan.csv.
    from budgie.core.allocation import pto_overrides

    init_workspace(tmp_path, year=2026)
    alloc = tmp_path / "allocations.csv"
    alloc.write_text(
        alloc.read_text().replace("bob@example.com,", "bob@example.com,20")
    )
    assert pto_overrides(tmp_path / "allocations.csv") == {"Bob": 20.0}

    monkeypatch.chdir(tmp_path)
    forget_workspaces()
    result = CliRunner().invoke(cli, ["plan"])
    assert result.exit_code == 0, result.output
    # Bob at 0.85 with his 20 days: 0.85 x 1832 = 1557 (1693 at the team's 0).
    assert "1,557" in result.output
    assert "1,693" not in result.output
    assert "665" not in result.output
