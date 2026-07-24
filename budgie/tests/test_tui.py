"""TUI behaviour: tabs, workspace awareness, and appending plan rows."""

from datetime import date

import pytest

from budgie.core.plan import load_plan
from budgie.core.scaffold import init_workspace
from budgie.core.workspace import forget_workspaces
from budgie.tui import BudgieTUI, append_plan_row, open_in_editor, shorten_path


@pytest.fixture(autouse=True)
def _clear_workspace_cache():
    forget_workspaces()
    yield
    forget_workspaces()


def _text(app, selector: str) -> str:
    """The plain text a Static is currently displaying, markup stripped."""
    from rich.text import Text

    return Text.from_markup(str(app.query_one(selector).content)).plain


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
        # The title bar names the project; the context bar says where it is.
        assert tmp_path.name in _text(app, "#titlebar")
        assert tmp_path.name in _text(app, "#contextbar")
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
        assert "no project" in _text(app, "#titlebar")
        assert "budgie init" in _text(app, "#contextbar")
        assert app.query_one("#forecast").row_count > 0


# -- the workflow order, and what happens when an input won't load ----------


async def test_tui_opens_on_forecast_when_it_can_compute_one(tmp_path, monkeypatch):
    init_workspace(tmp_path, year=2026)
    monkeypatch.chdir(tmp_path)
    forget_workspaces()

    app = BudgieTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#tabs").active == "tab_forecast"
        # Nothing is wrong, so the error banner stays out of the way.
        assert app.query_one("#forecast_banner").display is False


async def test_tui_opens_on_inputs_when_people_will_not_load(tmp_path, monkeypatch):
    init_workspace(tmp_path, year=2026)
    (tmp_path / "people.csv").write_text("name,hourly_cost\nAlice,not-a-number\n")
    monkeypatch.chdir(tmp_path)
    forget_workspaces()

    app = BudgieTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        # Land on the tab that can fix it, not the one that can only complain.
        assert app.query_one("#tabs").active == "tab_inputs"
        # And say why you were sent there -- naming the file, since the reason
        # is being read away from the forecast that produced it.
        assert "people.csv" in _text(app, "#inputs_status")
        # The forecast table is emptied rather than left showing stale numbers.
        assert app.query_one("#forecast").row_count == 0
        assert "people.csv" in _text(app, "#forecast_banner")


async def test_number_keys_switch_tabs(tmp_path, monkeypatch):
    init_workspace(tmp_path, year=2026)
    monkeypatch.chdir(tmp_path)
    forget_workspaces()

    app = BudgieTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        for key, expected in (
            ("1", "tab_inputs"),
            ("2", "tab_plan"),
            ("3", "tab_forecast"),
            ("4", "tab_assumptions"),
        ):
            await pilot.press(key)
            await pilot.pause()
            assert app.query_one("#tabs").active == expected


async def test_narrow_terminal_drops_the_percentile_glosses(tmp_path, monkeypatch):
    init_workspace(tmp_path, year=2026)
    monkeypatch.chdir(tmp_path)
    forget_workspaces()

    # The first render runs from on_mount, before layout, so this also pins
    # that the width is derived rather than read off an unsized widget.
    async with BudgieTUI().run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        narrow = _text(pilot.app, "#mc_figures")

    async with BudgieTUI().run_test(size=(140, 30)) as pilot:
        await pilot.pause()
        wide = _text(pilot.app, "#mc_figures")

    # Same three figures either way; only the gloss is negotiable, because a
    # wrapped label costs a row and separates the figure from its explanation.
    assert narrow.count("\n") == wide.count("\n") == 2
    assert "P90" in narrow and "P90" in wide
    assert "reserve this" in wide
    assert "reserve this" not in narrow
    assert max(len(line) for line in narrow.splitlines()) < 34


def test_shorten_path_keeps_the_end_that_identifies_the_file():
    # The end of a path says which file it is; the start says which disk.
    long = "/private/var/folders/hl/04xmlc/T/pytest-of-me/test_0/people.csv"
    short = shorten_path(long, width=24)

    assert len(short) == 24
    assert short.endswith("people.csv")
    assert short.startswith("…")
    # A path that already fits is returned untouched.
    assert shorten_path("people.csv", width=24) == "people.csv"
