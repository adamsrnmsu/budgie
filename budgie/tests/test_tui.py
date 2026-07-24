"""TUI behaviour: tabs, workspace awareness, and appending plan rows."""

from datetime import date

import pytest

from budgie.core.plan import load_plan
from budgie.core.scaffold import init_workspace
from budgie.core.workspace import forget_workspaces
from budgie.tui import BudgieTUI, append_plan_row, open_in_editor


@pytest.fixture(autouse=True)
def _clear_workspace_cache():
    forget_workspaces()
    yield
    forget_workspaces()


def test_append_plan_row_creates_the_file_with_a_header(tmp_path):
    path = tmp_path / "plan.csv"
    append_plan_row(path, "Alice", date(2026, 9, 1), 0.5)

    plan = load_plan(path)
    assert plan.names == ["Alice"]
    assert plan.fte_on("Alice", date(2026, 9, 2)) == 0.5
    assert plan.fte_on("Alice", date(2026, 8, 1)) == 0.0


def test_append_plan_row_keeps_history(tmp_path):
    path = tmp_path / "plan.csv"
    append_plan_row(path, "Bob", date(2026, 1, 1), 0.5)
    append_plan_row(path, "Bob", date(2026, 9, 1), 0.0)

    plan = load_plan(path)
    # Both rows survive: the earlier allocation is still on the record.
    assert len(plan.changes_for("Bob")) == 2
    assert plan.fte_on("Bob", date(2026, 6, 1)) == 0.5
    assert plan.fte_on("Bob", date(2026, 10, 1)) == 0.0


def test_append_plan_row_handles_a_file_with_no_trailing_newline(tmp_path):
    path = tmp_path / "plan.csv"
    path.write_text("name,effective_date,fte\nAlice,2026-01-01,0.25")

    append_plan_row(path, "Alice", date(2026, 7, 1), 0.75)

    assert len(load_plan(path).changes_for("Alice")) == 2


def test_open_in_editor_without_an_editor_set(tmp_path, monkeypatch):
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)
    path = tmp_path / "people.csv"
    path.write_text("name\n")

    message = open_in_editor(path)

    assert "$EDITOR" in message
    assert str(path) in message  # still tells you where the file is


def test_open_in_editor_reports_a_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("EDITOR", "true")
    message = open_in_editor(tmp_path / "nope.csv")
    assert "doesn't exist" in message


async def test_tui_shows_every_tab_and_the_project_root(tmp_path, monkeypatch):
    init_workspace(tmp_path, year=2026)
    monkeypatch.chdir(tmp_path)
    forget_workspaces()

    app = BudgieTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.sub_title == str(tmp_path.resolve())
        # The forecast table is populated from the project's people.csv.
        assert app.query_one("#forecast").row_count > 0
        # The plan tab reflects the project's plan.csv.
        assert app.query_one("#plan_table").row_count > 0
        # Every known input is listed.
        assert app.query_one("#inputs_table").row_count == 8


async def test_tui_adds_a_plan_row_from_the_form(tmp_path, monkeypatch):
    init_workspace(tmp_path, year=2026)
    monkeypatch.chdir(tmp_path)
    forget_workspaces()

    app = BudgieTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#plan_name").value = "Trillian"
        app.query_one("#plan_date").value = "2026-07-01"
        app.query_one("#plan_fte").value = "0.5"
        app.add_plan_row()
        await pilot.pause()

        assert "Trillian" in load_plan(tmp_path / "plan.csv").names
        # And the form clears, so the same row can't be added twice by accident.
        assert app.query_one("#plan_name").value == ""


async def test_tui_rejects_a_bad_plan_date(tmp_path, monkeypatch):
    init_workspace(tmp_path, year=2026)
    monkeypatch.chdir(tmp_path)
    forget_workspaces()
    before = (tmp_path / "plan.csv").read_text()

    app = BudgieTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#plan_name").value = "Zaphod"
        app.query_one("#plan_date").value = "next tuesday"
        app.query_one("#plan_fte").value = "0.5"
        message = app.add_plan_row()
        await pilot.pause()

        assert (tmp_path / "plan.csv").read_text() == before
        assert "YYYY-MM-DD" in message


async def test_tui_works_without_a_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    forget_workspaces()

    app = BudgieTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        # Falls back to the bundled sample rather than failing.
        assert app.sub_title == "no project"
        assert app.query_one("#forecast").row_count > 0
