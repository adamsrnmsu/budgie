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
    with pytest.raises(ValueError, match="FTE runs 0-100%"):
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
        await pilot.press("v")
        await pilot.pause()
        assert grid.model.readout()["gap"] == pytest.approx(0, abs=0.01)

        await pilot.press("s")
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


def test_parse_fte_takes_percent_or_fraction_and_explains_junk():
    from budgie.plan_grid import parse_fte

    assert parse_fte("50") == parse_fte("50%") == parse_fte("0.5") == 0.5
    with pytest.raises(ValueError, match="not a percentage"):
        parse_fte("lots")


def test_undo_redo_cover_set_nudge_and_discard(project):
    model = GridModel(load_snapshot(project))
    cell = ("Bob", 12)
    before = model.current(cell)
    model.set({cell}, 0.5)
    model.nudge({cell}, 0.05)
    assert model.current(cell) == pytest.approx(0.55)
    assert model.undo() and model.current(cell) == pytest.approx(0.5)
    assert model.redo() and model.current(cell) == pytest.approx(0.55)
    model.nudge({cell}, 5)  # clamped to 100%
    assert model.current(cell) == 1.0
    model.undo()
    model.edits.clear()
    assert model.undo() and model.edits  # back
    while model.undo():
        pass
    assert model.current(cell) == before and not model.edits


async def _plan(project, monkeypatch, size=(140, 45)):
    monkeypatch.chdir(project)
    forget_workspaces()
    return BudgieTUI(), size


async def test_plan_tab_focuses_the_grid_and_typing_edits_in_place(
    project, monkeypatch
):
    app, size = await _plan(project, monkeypatch)
    async with app.run_test(size=size) as pilot:
        await pilot.press("3")
        await pilot.pause()
        grid = app.query_one("#plan_grid")
        table = app.query_one("#grid_table")
        assert app.focused is table
        assert not app.query_one("#plan_form").display
        table.move_cursor(row=grid.model.names.index("Bob"), column=12)
        await pilot.press("5", "0", "enter")
        await pilot.pause()
        assert grid.model.current(("Bob", 12)) == 0.5
        assert "1 change" in str(app.query_one("#grid_changes").content)
        assert "→" in str(app.query_one("#grid_cost").content)
        await pilot.press("plus")
        assert grid.model.current(("Bob", 12)) == pytest.approx(0.55)
        await pilot.press("u", "u")
        assert not grid.model.edits
        await pilot.press("U")
        assert grid.model.edits
        # Bad input says what to do, not what float() thought.
        await pilot.press("enter")
        app.query_one("#grid_input").value = "lots"
        await pilot.press("enter")
        status = str(app.query_one("#grid_status").content)
        assert "try 50 or 0.5" in status and "float" not in status
        # Escape leaves the grid, so the tab keys work again.
        await pilot.press("escape", "escape")
        await pilot.press("4")
        await pilot.pause()
        assert app.query_one("#tabs").active == "tab_forecast"


async def test_saving_says_it_is_in_history_and_resets_undo(project, monkeypatch):
    app, size = await _plan(project, monkeypatch)
    async with app.run_test(size=size) as pilot:
        await pilot.press("3")
        await pilot.pause()
        grid = app.query_one("#plan_grid")
        app.query_one("#grid_table").move_cursor(
            row=grid.model.names.index("Bob"), column=12
        )
        await pilot.press("2", "5", "enter", "s")
        await pilot.pause()
        status = str(app.query_one("#grid_status").content)
        assert "history" in status and "undo starts fresh" in status
        assert not grid.model.undone and not grid.model.edits


async def test_help_has_a_plan_section(project, monkeypatch):
    app, size = await _plan(project, monkeypatch)
    async with app.run_test(size=size) as pilot:
        await pilot.press("question_mark")
        await pilot.pause()
        text = app.screen.query_one("#help_text").content
        assert "Plan tab" in str(text) and "undo" in str(text)


def test_fill_right_copies_into_open_months_only_and_undoes_in_one_step(project):
    model = GridModel(load_snapshot(project))
    model.set({("Bob", 6)}, 0.3)
    model.set({("Alice", 8)}, 0.2)
    before = dict(model.edits)
    # Bob: first selected month is Jun. Alice: Apr is booked, a legal source
    # whose value is copied, but nothing booked is ever written.
    n = model.fill_right({("Bob", 6), ("Bob", 9), ("Alice", 4)})
    assert n > 0
    assert [model.current(("Bob", m)) for m in range(7, 13)] == pytest.approx([0.3] * 6)
    assert model.current(("Alice", 12)) == pytest.approx(model.current(("Alice", 4)))
    assert all(model.base.editable(m) for _, m in model.edits)
    assert ("Alice", 4) not in model.edits and ("Bob", 5) not in model.edits
    assert model.fill_right({("Bob", 6)}) == 0  # already filled: no undo step
    assert model.undo() and model.edits == before  # one step back


def test_a_nudge_past_the_limit_changes_nothing_and_leaves_no_undo_step(project):
    model = GridModel(load_snapshot(project))
    cell = ("Bob", 12)
    model.set({cell}, 1.0)
    assert model.nudge({cell}, 0.05) == 0
    # One undo goes straight back past the set: the dead nudge left no step.
    assert model.undo() and cell not in model.edits
    at_zero = GridModel(load_snapshot(project))
    at_zero.set({cell}, 0.0)
    assert at_zero.nudge({cell}, -0.05) == 0
    assert at_zero.nudge({cell}, 0.05) == 1


# -- booked actuals, trends and the FTE % / hours toggle -----------------------
# The scaffold's weekly.csv reads Alice 430 h on Mar 22 and 660 h on May 17 (week
# 20), so Jan-Apr are complete for her and May on are not.


def _row(app, name):
    grid, table = app.query_one("#plan_grid"), app.query_one("#grid_table")
    return [str(c) for c in table.get_row_at(grid.model.names.index(name))]


def _status(app):
    return str(app.query_one("#grid_status").content)


async def test_completed_months_show_booked_cyan_and_the_rest_the_plan(
    project, monkeypatch
):
    from budgie.core.booked import completed_months, full_time_month_hours

    app, size = await _plan(project, monkeypatch)
    async with app.run_test(size=size) as pilot:
        await pilot.press("3")
        await pilot.pause()
        model = app.query_one("#plan_grid").model
        booked = completed_months(model.snap)["Alice"]
        ftm = full_time_month_hours(model.snap)
        row = _row(app, "Alice")
        assert row[1] == f"[cyan]{booked[0] / ftm[0]:.0%}[/cyan]"
        assert row[4] == f"[cyan]{booked[3] / ftm[3]:.0%}[/cyan]"
        assert "cyan" not in row[5] and "cyan" not in row[12]  # May on: the plan
        assert row[5] == "[dim]90%[/dim]" or row[5] == "90%"
        assert row[12] == "90%"
        # Header: 12 months, then the three trend columns.
        labels = [str(c.label) for c in app.query_one("#grid_table").columns.values()]
        assert labels[-3:] == ["2w", "4w", "8w"]


async def test_trend_columns_are_average_hours_a_week_as_a_share_of_full_time(
    project, monkeypatch
):
    from budgie.core.booked import full_time_week_hours, trailing_hours

    app, size = await _plan(project, monkeypatch)
    async with app.run_test(size=size) as pilot:
        await pilot.press("3")
        await pilot.pause()
        snap = app.query_one("#plan_grid").model.snap
        row = _row(app, "Alice")
        for text, w in zip(row[-3:], (2, 4, 8)):
            pct = trailing_hours(snap, w)["Alice"] / full_time_week_hours(snap)
            assert text == f"[cyan]{pct:.0%}[/cyan]"
        # 8 weeks back from May 17 is Mar 22, her other reading: (660-430)/8.
        assert trailing_hours(snap, 8)["Alice"] == pytest.approx(
            (660 - 430) / 8, abs=0.1
        )


async def test_h_flips_the_grid_between_fte_and_hours_and_back(project, monkeypatch):
    from budgie.core.booked import (
        completed_months,
        full_time_month_hours,
        trailing_hours,
    )

    app, size = await _plan(project, monkeypatch)
    async with app.run_test(size=size) as pilot:
        await pilot.press("3")
        await pilot.pause()
        grid = app.query_one("#plan_grid")
        snap = grid.model.snap
        fte_row = _row(app, "Alice")
        assert "showing FTE % · h hours" in str(app.query_one("#grid_legend").content)
        await pilot.press("h")
        await pilot.pause()
        ftm = full_time_month_hours(snap)
        row = _row(app, "Alice")
        assert row[1] == f"[cyan]{completed_months(snap)['Alice'][0]:,.0f}[/cyan]"
        assert row[12] == f"{0.9 * ftm[11]:,.0f}"  # plan: FTE x the month's hours
        assert row[-3] == f"[cyan]{trailing_hours(snap, 2)['Alice']:,.0f}[/cyan]"
        assert "showing hours · h FTE %" in str(app.query_one("#grid_legend").content)
        await pilot.press("h")
        await pilot.pause()
        assert _row(app, "Alice") == fte_row


async def test_typing_hours_sets_the_fte_as_hours_over_the_months_full_time(
    project, monkeypatch
):
    from budgie.core.booked import full_time_month_hours

    app, size = await _plan(project, monkeypatch)
    async with app.run_test(size=size) as pilot:
        await pilot.press("3")
        await pilot.pause()
        grid, table = app.query_one("#plan_grid"), app.query_one("#grid_table")
        ftm = full_time_month_hours(grid.model.snap)
        await pilot.press("h")
        table.move_cursor(row=grid.model.names.index("Bob"), column=12)
        await pilot.press("8", "0", "enter")
        await pilot.pause()
        assert grid.model.current(("Bob", 12)) == pytest.approx(80 / ftm[11], abs=1e-4)
        # More hours than a full-time month clamps to 100% and says so.
        await pilot.press("9", "9", "9", "enter")
        await pilot.pause()
        assert grid.model.current(("Bob", 12)) == 1.0
        assert "100%" in _status(app) and "clamp" in _status(app)
        # + - still move 5 FTE points in hours mode.
        await pilot.press("minus")
        assert grid.model.current(("Bob", 12)) == pytest.approx(0.95)


async def test_actual_and_trend_cells_are_read_only_and_say_so(project, monkeypatch):
    app, size = await _plan(project, monkeypatch)
    async with app.run_test(size=size) as pilot:
        await pilot.press("3")
        await pilot.pause()
        grid, table = app.query_one("#plan_grid"), app.query_one("#grid_table")
        alice = grid.model.names.index("Alice")
        from budgie.core.booked import completed_months, full_time_month_hours

        snap = grid.model.snap
        shown = (
            f"{completed_months(snap)['Alice'][1] / full_time_month_hours(snap)[1]:.0%}"
        )
        table.move_cursor(row=alice, column=2)  # Feb: booked
        for keys in (("5",), ("enter",), ("plus",)):
            await pilot.press(*keys)
            await pilot.pause()
            assert f"booked: {shown} is what was booked" in _status(app)
            assert not app.query_one("#grid_input").display
        table.move_cursor(row=alice, column=14)  # 4w
        for keys in (("5",), ("enter",), ("minus",), ("space",)):
            await pilot.press(*keys)
            await pilot.pause()
        assert "averages are read-only" in _status(app)
        assert not app.query_one("#grid_input").display
        assert not grid.model.edits and not grid.selected


def _budgeted(project):
    """The saved plan's P50 as the budget, so it is over budget about half the time."""
    snap = load_snapshot(project)
    p50 = GridModel(snap).readout()["p50"]
    return snap.what_if(budget=p50)


def test_readout_gives_over_budget_and_stoplight_before_and_after(project):
    model = GridModel(_budgeted(project))
    r = model.readout()
    assert (r["over"], r["signal"]) == (r["over0"], r["signal0"])  # no edits
    assert r["over0"] == pytest.approx(0.5, abs=0.05)
    assert r["signal0"].name == "RED"

    model.set({("Bob", m) for m in H2}, 0.0)
    r = model.readout()
    assert r["over0"] == pytest.approx(0.5, abs=0.05)  # the saved side is unchanged
    assert r["over"] < r["over0"]
    assert model.saved is model.saved  # computed once


def test_readout_omits_the_decision_without_a_budget(project):
    from dataclasses import replace

    model = GridModel(replace(load_snapshot(project), budget=None))
    r = model.readout()
    assert r["over"] is r["over0"] is r["signal"] is r["signal0"] is None


async def test_unsaved_line_shows_over_budget_and_stoplight(project, monkeypatch):
    app, size = await _plan(project, monkeypatch)
    async with app.run_test(size=size) as pilot:
        await pilot.press("3")
        await pilot.pause()
        grid = app.query_one("#plan_grid")
        grid.model.snap = _budgeted(project)
        grid.model.__dict__.pop("saved", None)
        grid.model.set({("Bob", m) for m in H2}, 0.0)
        grid._redraw()
        text = str(app.query_one("#grid_cost").content)
        assert "over budget 5" in text and "RED → " in text


async def test_greater_than_fills_right_from_the_cursor(project, monkeypatch):
    app, size = await _plan(project, monkeypatch)
    async with app.run_test(size=size) as pilot:
        await pilot.press("3")
        await pilot.pause()
        grid = app.query_one("#plan_grid")
        table = app.query_one("#grid_table")
        table.move_cursor(row=grid.model.names.index("Bob"), column=8)
        await pilot.press("5", "0", "enter", "greater_than_sign")
        await pilot.pause()
        assert grid.model.current(("Bob", 12)) == 0.5
        assert grid.model.current(("Bob", 7)) != 0.5
        await pilot.press("u")
        assert grid.model.current(("Bob", 12)) != 0.5
        assert grid.model.current(("Bob", 8)) == 0.5
