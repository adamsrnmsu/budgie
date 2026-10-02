"""TUI behaviour: tabs, workspace awareness, and appending plan rows."""

import json
import os
from datetime import date

import pytest

from budgie import tui as tui_mod
from budgie.core.plan import load_plan
from budgie.core.scaffold import init_workspace
from budgie.core.workspace import PROJECTS_DIR, forget_workspaces
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


def test_open_in_editor_falls_back_to_vim(tmp_path, monkeypatch):
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)
    path = tmp_path / "people.csv"
    path.write_text("name\n")
    calls = []
    monkeypatch.setattr(
        "budgie.tui.subprocess.run", lambda cmd, **kw: calls.append(cmd)
    )

    message = open_in_editor(path)

    assert calls == [["vim", str(path)]]
    assert "Edited people.csv" in message


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
            ("1", "tab_projects"),
            ("2", "tab_inputs"),
            ("3", "tab_plan"),
            ("4", "tab_forecast"),
            ("5", "tab_assumptions"),
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


# -- the project browser ------------------------------------------------


def _two_projects(tmp_path):
    """A container with two projects in it, as `budgie init` would leave them."""
    container = tmp_path / PROJECTS_DIR
    init_workspace(container / "fy26", year=2026)
    init_workspace(container / "fy27", year=2027)
    forget_workspaces()
    return container


async def test_browser_lists_every_project_under_budget(tmp_path, monkeypatch):
    _two_projects(tmp_path)
    monkeypatch.chdir(tmp_path)

    async with BudgieTUI().run_test() as pilot:
        await pilot.pause()
        names = pilot.app.project_names()

    assert names == ["fy26", "fy27"]


async def test_browser_opens_first_when_the_project_is_ambiguous(tmp_path, monkeypatch):
    # Two projects: nothing to auto-select, so land on the tab that settles it
    # rather than on a forecast built from bundled sample data.
    _two_projects(tmp_path)
    monkeypatch.chdir(tmp_path)

    async with BudgieTUI().run_test() as pilot:
        await pilot.pause()
        assert pilot.app.workspace is None
        assert pilot.app.query_one("#tabs").active == "tab_projects"


async def test_switching_project_repoints_the_whole_app(tmp_path, monkeypatch):
    container = _two_projects(tmp_path)
    monkeypatch.chdir(tmp_path)

    async with BudgieTUI().run_test() as pilot:
        await pilot.pause()
        message = pilot.app.switch_project("fy27")
        await pilot.pause()

        assert "fy27" in message
        assert pilot.app.workspace is not None
        assert pilot.app.workspace.root == (container / "fy27").resolve()
        # Every other tab follows: the header names it, and settings come from
        # the new budgie.yaml rather than the old one.
        assert "fy27" in _text(pilot.app, "#titlebar")
        assert pilot.app.workspace.setting("year", None) == 2027


async def test_switching_to_an_unknown_project_says_so(tmp_path, monkeypatch):
    _two_projects(tmp_path)
    monkeypatch.chdir(tmp_path)

    async with BudgieTUI().run_test() as pilot:
        await pilot.pause()
        message = pilot.app.switch_project("fy99")

        assert "No project called fy99" in message
        assert pilot.app.workspace is None


async def test_browser_marks_the_project_in_play(tmp_path, monkeypatch):
    _two_projects(tmp_path)
    monkeypatch.chdir(tmp_path)

    async with BudgieTUI().run_test() as pilot:
        await pilot.pause()
        pilot.app.switch_project("fy26")
        await pilot.pause()
        marks = pilot.app.project_marks()

    # Exactly one arrow, against the project actually loaded.
    assert marks == {"fy26": "→", "fy27": ""}


async def test_browser_finds_siblings_from_inside_a_project(tmp_path, monkeypatch):
    # Started from within budget/fy26, the other budgets are still reachable --
    # otherwise you would have to quit and cd to look at next year's.
    container = _two_projects(tmp_path)
    monkeypatch.chdir(container / "fy26")
    forget_workspaces()

    async with BudgieTUI().run_test() as pilot:
        await pilot.pause()
        assert pilot.app.workspace.root == (container / "fy26").resolve()
        assert pilot.app.project_names() == ["fy26", "fy27"]


async def test_switching_drops_an_explicit_people_override(tmp_path, monkeypatch):
    # --people named a file for the project you launched against; choosing a new
    # project is the newer instruction, and keeping the override would make the
    # switch look like it did nothing.
    container = _two_projects(tmp_path)
    monkeypatch.chdir(tmp_path)
    override = tmp_path / "elsewhere.csv"
    override.write_text(
        "name,hourly_cost,hours_low,hours_mode,hours_high\nZed,100,1,2,3\n"
    )

    async with BudgieTUI(csv_path=override).run_test() as pilot:
        await pilot.pause()
        assert pilot.app.people_path == str(override)

        pilot.app.switch_project("fy27")
        await pilot.pause()

        assert pilot.app.people_path == str(container / "fy27" / "people.csv")


# -- deleting a project -------------------------------------------------


async def test_delete_needs_two_presses(tmp_path, monkeypatch):
    container = _two_projects(tmp_path)
    monkeypatch.chdir(tmp_path)

    async with BudgieTUI().run_test() as pilot:
        await pilot.pause()
        first = pilot.app.action_delete_project()
        await pilot.pause()

        # Armed, not done: the files are still there.
        assert "Press d again" in first
        assert (container / "fy26").is_dir()

        second = pilot.app.action_delete_project()
        await pilot.pause()

        assert "Deleted fy26" in second
        assert not (container / "fy26").exists()
        assert (container / "fy27").is_dir()


async def test_another_key_cancels_a_pending_delete(tmp_path, monkeypatch):
    container = _two_projects(tmp_path)
    monkeypatch.chdir(tmp_path)

    async with BudgieTUI().run_test() as pilot:
        await pilot.pause()
        pilot.app.action_delete_project()
        await pilot.press("r")  # anything but d
        await pilot.pause()

        # Disarmed, so the next d only arms again rather than deleting.
        message = pilot.app.action_delete_project()
        assert "Press d again" in message
        assert (container / "fy26").is_dir()


async def test_deleting_the_open_project_falls_back_to_what_is_left(
    tmp_path, monkeypatch
):
    container = _two_projects(tmp_path)
    monkeypatch.chdir(tmp_path)

    async with BudgieTUI().run_test() as pilot:
        await pilot.pause()
        pilot.app.switch_project("fy26")
        await pilot.pause()
        assert pilot.app.workspace.root == (container / "fy26").resolve()

        pilot.app.action_delete_project()
        pilot.app.action_delete_project()
        await pilot.pause()

        # The open project went; the single survivor is picked up rather than
        # leaving the app displaying a directory that no longer exists.
        assert pilot.app.workspace is not None
        assert pilot.app.workspace.root == (container / "fy27").resolve()
        assert pilot.app.project_names() == ["fy27"]


async def test_a_broken_neighbour_is_listed_not_fatal(tmp_path, monkeypatch):
    # The browser loads every project nearby to count its inputs, so one bad
    # budgie.yaml next door used to take the whole app down on mount.
    init_workspace(tmp_path / "budget" / "fy26", year=2026)
    broken = tmp_path / "budget" / "fy27"
    broken.mkdir()
    (broken / "budgie.yaml").write_text("inputs:\n  peeple: people.csv\n")
    monkeypatch.chdir(tmp_path / "budget" / "fy26")
    forget_workspaces()

    app = BudgieTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.project_names() == ["fy26", "fy27"]
        assert "won't load" in app.switch_project("fy27")
        assert app.workspace.root.name == "fy26"  # still on the one that works


# -- switching to perch and gitboard (PI_SUITE, set by perch tui) ------------

SUITE = {
    "perch": {"cwd": "/ws", "argv": ["perch", "tui"]},
    "gitboard": {"cwd": "/gb", "argv": ["gitboard", "tui", "grp/a"]},
}


async def test_p_and_g_exit_with_the_target(tmp_path, monkeypatch):
    init_workspace(tmp_path, year=2026)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PI_SUITE", json.dumps(SUITE))
    for key, target in (("P", "perch"), ("G", "gitboard")):
        app = BudgieTUI()
        async with app.run_test() as pilot:
            await pilot.press(key)
            await pilot.pause()
        assert app.return_value == target


async def test_without_pi_suite_a_switch_key_says_where_to_start(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PI_SUITE", raising=False)
    app = BudgieTUI()
    said = []
    monkeypatch.setattr(app, "notify", lambda msg, **kw: said.append(msg))
    async with app.run_test() as pilot:
        await pilot.press("P")
        await pilot.pause()
        assert app.is_running
    assert said == ["start from perch tui to switch apps"]


def test_a_malformed_map_is_no_entry(monkeypatch):
    for bad in (
        "not json",
        "[]",
        '{"perch": 3}',
        '{"perch": {"cwd": "/", "argv": []}}',
    ):
        monkeypatch.setenv("PI_SUITE", bad)
        assert tui_mod.suite_entry("perch") is None


def test_run_execs_the_target_after_the_app_exits(monkeypatch):
    monkeypatch.setenv("PI_SUITE", json.dumps(SUITE))
    monkeypatch.setattr(BudgieTUI, "run", lambda self: "perch")
    calls = []
    monkeypatch.setattr(os, "chdir", lambda d: calls.append(("chdir", d)))
    monkeypatch.setattr(os, "execvp", lambda f, a: calls.append(("exec", f, a)))
    tui_mod.run()
    assert calls == [("chdir", "/ws"), ("exec", "perch", ["perch", "tui"])]


# -- step A: safety and quick fixes (budgie-vrc, budgie-4oj) ------------------


async def test_d_on_the_plan_tab_deletes_nothing(tmp_path, monkeypatch):
    # The repro: one project under budget/, launched from the parent folder.
    # On the Plan tab `d` reads as "delete this row"; it must not reach the
    # project, and the footer must not offer it there.
    project = tmp_path / PROJECTS_DIR / "fy26"
    init_workspace(project, year=2026)
    monkeypatch.chdir(tmp_path)
    forget_workspaces()

    app = BudgieTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("3")
        await pilot.pause()
        assert "d" not in app.active_bindings
        await pilot.press("d", "d")
        await pilot.pause()
        assert project.is_dir()
        assert app.query_one("#tabs").active == "tab_plan"

        await pilot.press("1")
        await pilot.pause()
        assert "d" in app.active_bindings
        await pilot.press("d")
        await pilot.pause()
        # The arming warning is drawn as an error, not in success green.
        assert app.query_one("#projects_status").has_class("error")
        assert project.is_dir()
