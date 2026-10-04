"""The Plan tab's month grid: scratch edits, the solver, and committing rows."""

from datetime import date

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


def test_a_fiscal_year_grid_runs_in_the_spans_order(tmp_path):
    init_workspace(tmp_path, year=2027, year_start="10-01")
    model = GridModel(load_snapshot(tmp_path))
    assert model.months[:3] == ["Oct", "Nov", "Dec"] and model.months[-1] == "Sep"
    cost = model.readout()["cost"]
    model.set({("Bob", m) for m in range(10, 13)}, 0.0)  # Jul..Sep, the span's end
    assert model.readout()["cost"] < cost


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


SHEET = "name,Jan,Feb,Mar,Apr,May,Jun,Jul,Aug,Sep,Oct,Nov,Dec\n"


def test_a_month_sheet_seeds_scratch_edits(project):
    before = (project / "plan.csv").read_text()
    sheet = project / "sheet.csv"
    sheet.write_text(SHEET + "Alice,1,1,1,1,1,1,,,,,,0.5\nDan,,,,,,,0.5,,,,,\n")
    model = GridModel(load_snapshot(project))

    said = model.seed(sheet)

    # Jan..Apr are booked by the scaffold's readings, so they stay as they are.
    assert said.startswith("Seeded 4 cell(s) from sheet.csv; 4 in booked months")
    assert "not costed (not in people.csv): Dan" in said
    assert model.edits == {
        ("Alice", 5): 1,
        ("Alice", 6): 1,
        ("Alice", 12): 0.5,
        ("Dan", 7): 0.5,
    }
    assert "Dan" in model.names and model.readout()["cost"] > 0
    assert (project / "plan.csv").read_text() == before


async def test_import_a_sheet_in_the_tui_then_commit(project, monkeypatch):
    monkeypatch.chdir(project)
    forget_workspaces()
    (project / "sheet.csv").write_text(SHEET + "Bob,,,,,,,,,,0.25,0.25,0.25\n")
    before = (project / "plan.csv").read_text()
    app = BudgieTUI()
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.press("3")
        await pilot.pause()
        grid = app.query_one("#plan_grid")
        app.query_one("#grid_table").focus()
        await pilot.press("i")
        app.query_one("#grid_input").value = "sheet.csv"
        await pilot.press("enter")
        await pilot.pause()

        assert grid.model.scratch.grid("Bob")[9:] == [0.25] * 3
        assert "Seeded 3 cell(s)" in str(grid.query_one("#grid_status").render())
        assert (project / "plan.csv").read_text() == before

        await pilot.press("c")
        await pilot.pause()

    assert load_plan(project / "plan.csv").fte_on("Bob", date(2026, 11, 15)) == 0.25


async def test_a_sheet_path_is_relative_to_the_project_not_the_cwd(
    tmp_path, monkeypatch
):
    project = tmp_path / "fy26"
    project.mkdir()
    init_workspace(project, year=2026)
    (project / "sheet.csv").write_text(SHEET + "Bob,,,,,,,,,,0.25,0.25,0.25\n")
    monkeypatch.chdir(tmp_path)  # launched from above the project
    forget_workspaces()
    app = BudgieTUI()
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.press("3")
        await pilot.pause()
        grid = app.query_one("#plan_grid")
        app.query_one("#grid_table").focus()
        await pilot.press("i")
        app.query_one("#grid_input").value = "sheet.csv"
        await pilot.press("enter")
        await pilot.pause()

        assert "Seeded 3 cell(s)" in str(grid.query_one("#grid_status").render())
