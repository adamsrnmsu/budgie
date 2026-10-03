"""The Plan tab's month grid: scratch edits, the solver, and committing rows."""

import pytest

from budgie.core.plan import load_plan
from budgie.core.project import load_snapshot
from budgie.core.scaffold import init_workspace
from budgie.core.workspace import forget_workspaces
from budgie.plan_grid import GridModel, costing_for, parse_money
from budgie.tui import BudgieTUI

H2 = range(7, 13)  # Jul..Dec


@pytest.fixture(autouse=True)
def _clear_workspace_cache():
    forget_workspaces()
    yield
    forget_workspaces()


@pytest.fixture
def project(tmp_path):
    init_workspace(tmp_path, year=2026)
    return tmp_path


def test_money_parses_the_ways_people_type_it():
    assert parse_money("425000") == 425_000
    assert parse_money("$425,000") == 425_000
    assert parse_money("850k") == 850_000
    assert parse_money("1.2M") == pytest.approx(1_200_000)
    with pytest.raises(ValueError):
        parse_money("lots")


def test_scratch_edits_reprice_without_writing(project):
    before = (project / "plan.csv").read_text()
    model = GridModel(load_snapshot(project))
    cost = model.readout()["cost"]

    model.set({("Bob", m) for m in H2}, 0.0)

    assert model.readout()["cost"] < cost
    assert model.scratch.grid("Bob")[6:] == [0.0] * 6
    assert (project / "plan.csv").read_text() == before


def test_the_target_defaults_to_the_budget_and_solving_closes_the_gap(project):
    model = GridModel(load_snapshot(project), target=None)
    model.target = model.readout()["cost"] - 20_000

    said = model.solve({("Bob", m) for m in H2}, mode="even")

    assert model.readout()["gap"] == pytest.approx(0, abs=0.01)
    assert said.startswith("Solved 6 cells")


def test_months_up_to_the_latest_reading_are_booked(project):
    # The scaffold's weekly.csv reads to ISO week 20 (May 17).
    model = GridModel(load_snapshot(project))
    assert not model.base.editable(4) and model.base.editable(6)
    with pytest.raises(ValueError, match="Apr already booked"):
        model.set({("Alice", 4)}, 0.5)
    with pytest.raises(ValueError, match="FTE runs 0 to 1"):
        model.set({("Alice", 7)}, 3)


def test_committed_rows_cost_what_the_grid_showed(project):
    model = GridModel(load_snapshot(project))
    model.set({("Alice", m) for m in H2}, 0.5)
    shown = model.readout()["cost"]

    with (project / "plan.csv").open("a") as plan:
        for row in model.rows():
            plan.write(f"{row.name},{row.effective_date},{row.fte}\n")

    assert costing_for(load_snapshot(project)).cost() == pytest.approx(shown)


async def test_select_target_solve_commit_in_the_tui(project, monkeypatch):
    monkeypatch.chdir(project)
    forget_workspaces()
    app = BudgieTUI()
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.press("3")
        await pilot.pause()
        grid = app.query_one("#plan_grid")
        table = app.query_one("#grid_table")
        table.focus()
        bob = grid.model.names.index("Bob")
        table.move_cursor(row=bob, column=7)
        for _ in range(5):
            await pilot.press("shift+right")
        assert grid.selected == {("Bob", m) for m in H2}

        target = round(grid.model.readout()["cost"] - 15_000)
        await pilot.press("t")
        app.query_one("#grid_input").value = str(target)
        await pilot.press("enter")
        await pilot.press("s")
        await pilot.pause()
        assert grid.model.readout()["gap"] == pytest.approx(0, abs=0.01)

        await pilot.press("c")
        await pilot.pause()

    entries = load_plan(project / "plan.csv").changes_for("Bob")
    assert len(entries) > 1  # the solved months were appended
    assert costing_for(load_snapshot(project)).cost() == pytest.approx(target, abs=1)
