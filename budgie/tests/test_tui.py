"""TUI behaviour: tabs, workspace awareness, and appending plan rows."""

import contextlib
import json
import os
import subprocess
import time
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
        # Every known input is listed, plus budgie.yaml itself.
        assert app.query_one("#inputs_table").row_count == 9


async def test_tui_adds_a_plan_row_from_the_form(tmp_path, monkeypatch):
    init_workspace(tmp_path, year=2026)
    monkeypatch.chdir(tmp_path)
    forget_workspaces()

    app = BudgieTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#plan_name").value = "Alice"
        app.query_one("#plan_date").value = "2026-07-01"
        app.query_one("#plan_fte").value = "0.5"
        app.add_plan_row()
        await pilot.pause()

        assert len(load_plan(tmp_path / "plan.csv").changes_for("Alice")) == 2
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
    assert "Reserve" in wide
    assert "Reserve" not in narrow
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
    monkeypatch.delenv("TMUX", raising=False)
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


SUITE_TMUX = "/private/tmp/tmux-501/pi,123,0"
TMUX = ["tmux", "-L", "pi"]
G_KEY = json.dumps(SUITE["gitboard"], sort_keys=True)


@pytest.fixture
def hops(monkeypatch):
    """In perch suite; records tmux argv; list-windows answers .listing."""
    calls = []

    class Fake:
        listing = ""
        stderr = ""

    def run(argv, **kw):
        calls.append(list(argv))
        if "list-windows" in argv:
            return subprocess.CompletedProcess(argv, 0, Fake.listing, "")
        return subprocess.CompletedProcess(
            argv, 1 if Fake.stderr else 0, "", Fake.stderr
        )

    Fake.calls = calls
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setenv("TMUX", SUITE_TMUX)
    monkeypatch.setenv("PI_SUITE", json.dumps(SUITE))
    return Fake


def test_in_suite_only_on_the_pi_socket(monkeypatch):
    monkeypatch.setenv("TMUX", SUITE_TMUX)
    assert tui_mod.in_suite()
    monkeypatch.setenv("TMUX", "/private/tmp/tmux-501/default,1,0")
    assert not tui_mod.in_suite()
    monkeypatch.delenv("TMUX")
    assert not tui_mod.in_suite()


def test_hop_to_the_same_entry_only_selects(hops):
    hops.listing = f"perch\t{{}}\ngitboard\t{G_KEY}\n"
    assert tui_mod.hop("gitboard", SUITE["gitboard"]) is None
    assert hops.calls[-1] == [*TMUX, "select-window", "-t", "pi:=gitboard"]


def test_hop_to_a_missing_window_opens_it(hops):
    hops.listing = "perch\t{}\n"
    tui_mod.hop("gitboard", SUITE["gitboard"])
    assert hops.calls == [
        [*TMUX, "list-windows", "-t", "pi", "-F", "#{window_name}\t#{@entry}"],
        [
            *TMUX,
            "new-window",
            "-t",
            "pi:",
            "-n",
            "gitboard",
            "-c",
            "/gb",
            "-e",
            f"PI_SUITE={json.dumps(SUITE)}",
            "gitboard",
            "tui",
            "grp/a",
            ";",
            "set-option",
            "-w",
            "-t",
            "pi:=gitboard",
            "@entry",
            G_KEY,
        ],
    ]


def test_hop_to_another_entry_respawns_only_that_window(hops):
    hops.listing = 'gitboard\t{"argv": ["gitboard", "tui", "grp/b"], "cwd": "/gb"}\n'
    tui_mod.hop("gitboard", SUITE["gitboard"])
    assert hops.calls[-1] == [
        *TMUX,
        "respawn-window",
        "-k",
        "-t",
        "pi:=gitboard",
        "-c",
        "/gb",
        "-e",
        f"PI_SUITE={json.dumps(SUITE)}",
        "gitboard",
        "tui",
        "grp/a",
        ";",
        "set-option",
        "-w",
        "-t",
        "pi:=gitboard",
        "@entry",
        G_KEY,
        ";",
        "select-window",
        "-t",
        "pi:=gitboard",
    ]


def test_hop_without_a_recorded_entry_respawns(hops):
    hops.listing = "gitboard\t\n"
    tui_mod.hop("gitboard", SUITE["gitboard"])
    assert hops.calls[-1][3:5] == ["respawn-window", "-k"]


def test_hop_that_tmux_refuses_says_why(hops):
    hops.stderr = "no server running"
    assert tui_mod.hop("perch", SUITE["perch"]) == "no server running"


async def test_in_the_suite_p_hops_and_budgie_keeps_running(
    tmp_path, monkeypatch, hops
):
    init_workspace(tmp_path, year=2026)
    monkeypatch.chdir(tmp_path)
    app = BudgieTUI()
    async with app.run_test() as pilot:
        await pilot.press("P")
        await pilot.pause()
        assert app.is_running
    assert hops.calls[-1][3] == "new-window"


async def test_in_the_suite_a_failed_hop_says_why(tmp_path, monkeypatch, hops):
    hops.stderr = "no server running"
    monkeypatch.chdir(tmp_path)
    app = BudgieTUI()
    said = []
    monkeypatch.setattr(app, "notify", lambda msg, **kw: said.append(msg))
    async with app.run_test() as pilot:
        await pilot.press("G")
        await pilot.pause()
        assert app.is_running
    assert said == ["switch failed: no server running"]


async def test_in_the_suite_a_bad_map_still_says_where_to_start(
    tmp_path, monkeypatch, hops
):
    monkeypatch.setenv("PI_SUITE", "not json")
    monkeypatch.chdir(tmp_path)
    app = BudgieTUI()
    said = []
    monkeypatch.setattr(app, "notify", lambda msg, **kw: said.append(msg))
    async with app.run_test() as pilot:
        await pilot.press("P")
        await pilot.pause()
    assert said == ["start from perch tui to switch apps"]
    assert hops.calls == []


def test_switch_with_an_empty_program_says_why(tmp_path):
    with pytest.raises(SystemExit) as exc:
        tui_mod.switch({"cwd": str(tmp_path), "argv": [""]})
    assert "switch failed" in str(exc.value.code)


async def test_focus_recalculates_only_after_an_input_changed(tmp_path, monkeypatch):
    from textual import events

    init_workspace(tmp_path, year=2026)
    monkeypatch.chdir(tmp_path)
    app = BudgieTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        ran = []
        monkeypatch.setattr(app, "recalculate", lambda: ran.append(1))
        app.post_message(events.AppFocus())
        await pilot.pause()
        assert ran == []  # nothing touched since the last calculation
        touched = next(i.path for i in app.workspace.inputs() if i.exists)
        later = time.time() + 10
        os.utime(touched, (later, later))
        app.post_message(events.AppFocus())
        await pilot.pause()
        assert ran == [1]


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


def _record_edits(monkeypatch):
    """Stand in for the editor: record what `e` would open."""
    opened = []

    def fake_open(path):
        opened.append(path)
        return f"Edited {path.name}."

    monkeypatch.setattr(tui_mod, "open_in_editor", fake_open)
    # The headless test driver can't suspend.
    monkeypatch.setattr(BudgieTUI, "suspend", lambda self: contextlib.nullcontext())
    return opened


async def test_e_opens_the_file_the_tab_shows(tmp_path, monkeypatch):
    init_workspace(tmp_path, year=2026)
    monkeypatch.chdir(tmp_path)
    forget_workspaces()
    opened = _record_edits(monkeypatch)

    app = BudgieTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("3", "e")
        await pilot.pause()
        await pilot.press("4", "e")
        await pilot.pause()
        await pilot.press("2")
        app.query_one("#inputs_table").move_cursor(row=3)
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        third = app.workspace.inputs()[3].path
        # Editing recalculates; the Inputs cursor stays where it was.
        assert app.query_one("#inputs_table").cursor_row == 3

    assert opened == [tmp_path / "plan.csv", tmp_path / "people.csv", third]


async def test_e_on_projects_edits_the_open_projects_config(tmp_path, monkeypatch):
    container = _two_projects(tmp_path)
    monkeypatch.chdir(tmp_path)
    opened = _record_edits(monkeypatch)

    app = BudgieTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.switch_project("fy26")
        await pilot.pause()
        await pilot.press("e")  # cursor on fy26, the open one
        await pilot.pause()
        app.query_one("#projects_table").move_cursor(row=1)
        await pilot.pause()
        await pilot.press("e")  # fy27 isn't open: nothing, and say so in red
        await pilot.pause()
        assert app.query_one("#projects_status").has_class("error")

    assert opened == [(container / "fy26" / "budgie.yaml").resolve()]


async def test_e_on_forecast_wont_edit_the_bundled_sample(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    opened = _record_edits(monkeypatch)

    app = BudgieTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("4", "e")
        await pilot.pause()

    assert opened == []


async def test_failures_are_red_and_successes_are_not(tmp_path, monkeypatch):
    init_workspace(tmp_path, year=2026)
    monkeypatch.chdir(tmp_path)
    forget_workspaces()

    app = BudgieTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        status = app.query_one("#plan_status")
        app.query_one("#plan_name").value = "Alice"
        app.query_one("#plan_date").value = "next tuesday"
        app.query_one("#plan_fte").value = "0.5"
        app.add_plan_row()
        assert status.has_class("error")

        app.query_one("#plan_date").value = "2026-07-01"
        app.add_plan_row()
        assert not status.has_class("error")


async def test_escape_leaves_the_plan_form(tmp_path, monkeypatch):
    init_workspace(tmp_path, year=2026)
    monkeypatch.chdir(tmp_path)
    forget_workspaces()

    app = BudgieTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("3")
        app.query_one("#plan_name").focus()
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        # The month grid is the Plan tab's default view, so Escape lands there.
        assert app.focused is app.query_one("#grid_table")
        # The digit keys switch tabs again instead of typing into the form.
        await pilot.press("4")
        await pilot.pause()
        assert app.query_one("#tabs").active == "tab_forecast"
        assert app.query_one("#plan_name").value == ""


async def _plan_form(app, pilot, name, fte="0.5"):
    app.query_one("#plan_name").value = name
    app.query_one("#plan_date").value = "2026-07-01"
    app.query_one("#plan_fte").value = fte
    message = app.add_plan_row()
    await pilot.pause()
    return message


async def test_plan_form_rejects_fte_above_one(tmp_path, monkeypatch):
    init_workspace(tmp_path, year=2026)
    monkeypatch.chdir(tmp_path)
    forget_workspaces()
    before = (tmp_path / "plan.csv").read_text()

    app = BudgieTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        message = await _plan_form(app, pilot, "Alice", fte="5")
        assert message == "FTE is a share of full time: 0 to 1"
        assert app.query_one("#plan_status").has_class("error")
    assert (tmp_path / "plan.csv").read_text() == before


async def test_plan_form_rejects_a_mis_cased_name(tmp_path, monkeypatch):
    init_workspace(tmp_path, year=2026)
    monkeypatch.chdir(tmp_path)
    forget_workspaces()
    before = (tmp_path / "plan.csv").read_text()

    app = BudgieTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "Did you mean Alice?" in await _plan_form(app, pilot, "alice")
        # Pressing again doesn't push it through: it's a typo, not a new person.
        assert "Did you mean Alice?" in await _plan_form(app, pilot, "alice")
    assert (tmp_path / "plan.csv").read_text() == before


async def test_plan_form_asks_twice_before_adding_an_unknown_name(
    tmp_path, monkeypatch
):
    init_workspace(tmp_path, year=2026)
    monkeypatch.chdir(tmp_path)
    forget_workspaces()
    plan = tmp_path / "plan.csv"
    before = plan.read_text()

    app = BudgieTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        message = await _plan_form(app, pilot, "Zed")
        assert message == (
            "Zed isn't in people.csv, so they won't be costed. "
            "Press Add again to add them anyway."
        )
        assert app.query_one("#plan_status").has_class("error")
        assert plan.read_text() == before

        await _plan_form(app, pilot, "Zed")
        assert "Zed" in load_plan(plan).names


SAMPLE = "SAMPLE DATA — no project open."


async def test_sample_data_is_labelled_as_such(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    app = BudgieTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#forecast_banner").display is True
        assert SAMPLE in _text(app, "#forecast_banner")
        assert "SAMPLE DATA" in _text(app, "#titlebar")


async def test_with_several_projects_it_says_pick_one_not_init(tmp_path, monkeypatch):
    _two_projects(tmp_path)
    monkeypatch.chdir(tmp_path)

    app = BudgieTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        context = _text(app, "#contextbar")
        inputs_row = " ".join(map(str, app.query_one("#inputs_table").get_row_at(0)))
        assert "pick a project on the Projects tab" in context
        assert "budgie init" not in context
        assert "pick a project on the Projects tab" in inputs_row
        assert "budgie init" not in inputs_row
        assert SAMPLE in _text(app, "#forecast_banner")

        app.switch_project("fy26")
        await pilot.pause()
        # A real project: the banner goes, and so does the label.
        assert app.query_one("#forecast_banner").display is False
        assert "SAMPLE DATA" not in _text(app, "#titlebar")


async def test_a_project_without_people_csv_is_sample_data_too(tmp_path, monkeypatch):
    # people_path falls back to the bundled team when the project has no
    # people.csv: `e` must not open the package's own file, and the numbers
    # must be labelled.
    init_workspace(tmp_path, year=2026)
    (tmp_path / "people.csv").unlink()
    monkeypatch.chdir(tmp_path)
    forget_workspaces()
    opened = _record_edits(monkeypatch)

    app = BudgieTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("4", "e")
        await pilot.pause()
        assert app.query_one("#forecast_banner").display is True
        assert "SAMPLE DATA" in _text(app, "#forecast_banner")
        assert "people.csv" in _text(app, "#forecast_banner")

    assert opened == []


# --- one model: the Forecast tab reads the project the way the CLI does ----


def _p50(text: str) -> float:
    import re

    return float(re.search(r"P50 \$([\d,]+)", text).group(1).replace(",", ""))


async def test_forecast_headline_matches_the_cli(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from budgie.budgie import cli

    init_workspace(tmp_path, year=2026)
    monkeypatch.chdir(tmp_path)
    forget_workspaces()
    cli_out = CliRunner().invoke(cli, ["forecast"]).output

    app = BudgieTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        headline = _text(app, "#forecast_headline")
        # Same project, same seed and iterations from budgie.yaml: same P50.
        assert _p50(headline) == _p50(cli_out)
        assert headline.startswith("Budget $425,000")
        assert "headroom" in headline and "chance over" in headline


async def test_a_plan_row_moves_the_forecast_tab(tmp_path, monkeypatch):
    init_workspace(tmp_path, year=2026)
    monkeypatch.chdir(tmp_path)
    forget_workspaces()

    app = BudgieTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        before = _p50(_text(app, "#forecast_headline"))
        append_plan_row(tmp_path / "plan.csv", "Bob", date(2026, 7, 1), 0.0)
        append_plan_row(tmp_path / "plan.csv", "Zed", date(2026, 7, 1), 1.0)
        await pilot.press("r")
        await pilot.pause()
        assert _p50(_text(app, "#forecast_headline")) < before
        banner = _text(app, "#forecast_banner")
        assert app.query_one("#forecast_banner").display is True
        assert "Zed is in plan.csv but has no rate" in banner


async def test_the_forecast_tab_has_no_unsaved_setting_boxes(tmp_path, monkeypatch):
    init_workspace(tmp_path, year=2026)
    monkeypatch.chdir(tmp_path)
    forget_workspaces()

    app = BudgieTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        for gone in ("#year", "#pto", "#iterations", "#seed", "#recalc"):
            assert not app.query(gone)


async def test_forecast_shows_settings_planned_hours_and_range(tmp_path, monkeypatch):
    init_workspace(tmp_path, year=2026)
    with (tmp_path / "people.csv").open("a") as people:
        people.write("Carol,90,0.5,0.5,0.5\n")  # a rate, but no plan rows
    monkeypatch.chdir(tmp_path)
    forget_workspaces()

    app = BudgieTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert _text(app, "#forecast_settings").startswith(
            "2026 · PTO 0d · 10,000 runs"
        )
        table = app.query_one("#forecast")
        rows = {
            str(table.get_row_at(i)[0]): table.get_row_at(i)
            for i in range(table.row_count)
        }
        assert rows["Alice"][1] == "$95/h"
        low, high = (float(x.replace(",", "")) for x in rows["Alice"][3].split("–"))
        assert low < float(rows["Alice"][2].replace(",", "")) < high
        assert rows["Carol"][2] == "0" and rows["Carol"][3] == "—"


# --- teaching: ? help, a hint per tab, an Assumptions tab that explains -----


def _project(tmp_path, monkeypatch):
    init_workspace(tmp_path, year=2026)
    monkeypatch.chdir(tmp_path)
    forget_workspaces()


def _help_text(app) -> str:
    from rich.text import Text

    return Text.from_markup(str(app.screen.query_one("#help_text").content)).plain


async def test_question_mark_opens_help_and_escape_or_question_mark_closes_it(
    tmp_path, monkeypatch
):
    from budgie.tui import HelpScreen

    _project(tmp_path, monkeypatch)
    app = BudgieTUI()
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        footer = {b.binding.key: b.binding for b in app.active_bindings.values()}
        assert footer["question_mark"].description == "Help"
        assert footer["question_mark"].key_display == "?"

        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, HelpScreen)

        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("question_mark")
        await pilot.pause()
        assert not isinstance(app.screen, HelpScreen)


async def test_help_teaches_the_model_and_every_term(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    app = BudgieTUI()
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        text = _help_text(app)
        # It is longer than the screen, so it has to scroll to the keys.
        await pilot.press("end")
        await pilot.pause()
        assert app.screen.query_one("#help").scroll_y > 0
        assert "closes" in str(app.screen.query_one("#help").border_subtitle)

    for step in (
        "Who and when",
        "Rate",
        "Time",
        "Cost",
        "Reality",
        "Will we run out",
    ):
        assert step in text
    assert "plan.csv is the only place FTE lives" in text
    for term in (
        "FTE",
        "effective_date",
        "hourly_cost",
        "under",
        "over",
        "util_low",
        "util_mode",
        "util_high",
        "hours_low",
        "hours_mode",
        "hours_high",
        "P10",
        "P50",
        "P90",
        "headroom",
        "stoplight",
        "readings",
        "iterations",
        "seed",
        "PTO",
    ):
        assert term in text, term
    assert "kept for old files" in text.lower()
    # And the keys, including how to get out again.
    for key in ("1-5", "enter", "escape", "Recalculate"):
        assert key in text, key


async def test_keys_under_the_help_screen_do_not_crash(tmp_path, monkeypatch):
    from budgie.tui import HelpScreen

    _project(tmp_path, monkeypatch)
    opened = _record_edits(monkeypatch)
    app = BudgieTUI()
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        await pilot.press("1", "d", "question_mark")
        await pilot.pause()
        for key in ("2", "r", "e", "d"):
            await pilot.press(key)
            await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.pause()
        # Nothing was deleted or opened from behind the help screen.
        assert (tmp_path / "budgie.yaml").exists()
    assert opened == []


async def test_every_tab_says_what_it_answers_and_which_file(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    app = BudgieTUI()
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        hints = {
            tab: _text(app, f"#{tab} .tab-hint")
            for tab in (
                "tab_projects",
                "tab_inputs",
                "tab_plan",
                "tab_forecast",
                "tab_assumptions",
            )
        }
    assert "budgie.yaml" in hints["tab_projects"]
    assert "e opens" in hints["tab_inputs"]
    assert "plan.csv" in hints["tab_plan"]
    assert hints["tab_forecast"].startswith("Will we run out?")
    for name in ("plan.csv", "people.csv", "weekly.csv", "costs.csv", "budget"):
        assert name in hints["tab_forecast"]
    assert "?" in hints["tab_assumptions"]


async def test_assumptions_tab_teaches_the_model_for_this_project(
    tmp_path, monkeypatch
):
    _project(tmp_path, monkeypatch)  # scaffolded with pto: 0
    app = BudgieTUI()
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        text = _text(app, "#assumptions_text")

    assert "Will we run out" in text and "Reality" in text
    for line in ("Gross", "holidays", "PTO", "Available"):
        assert line in text
    assert "pro-rated by FTE" in text
    assert "spread" in text
    # The TUI's PTO setting is budgie.yaml, not a CLI flag, and there is no
    # table above this text.
    assert "--pto" not in text
    assert "pto:" in text and "budgie.yaml" in text
    assert "table above" not in text


async def test_inputs_lists_budgie_yaml_and_e_opens_it(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    opened = _record_edits(monkeypatch)
    app = BudgieTUI()
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        await pilot.press("2")
        table = app.query_one("#inputs_table")
        last = table.row_count - 1
        row = [str(c) for c in table.get_row_at(last)]
        assert "budgie.yaml" in row[1]
        assert row[3].startswith("Settings: year, PTO, budget")
        table.move_cursor(row=last)
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()

    assert opened == [tmp_path / "budgie.yaml"]


async def test_inputs_used_by_names_the_tabs(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    app = BudgieTUI()
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        table = app.query_one("#inputs_table")
        used = {
            str(table.get_row_at(i)[1]): str(table.get_row_at(i)[4])
            for i in range(table.row_count)
        }
    assert used["people.csv"] == "Forecast"
    assert used["plan.csv"] == "Plan, Forecast"
    assert used["budgie.yaml"] == "every tab"
    assert "CLI" in used["scenarios.yaml"]


async def test_no_code_names_on_screen(tmp_path, monkeypatch):
    import re

    _project(tmp_path, monkeypatch)
    app = BudgieTUI()
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        table = app.query_one("#inputs_table")
        shown = [
            _text(app, "#mc_stats"),
            _text(app, "#mc_figures"),
            _text(app, "#assumptions_text"),
            *(str(c) for i in range(table.row_count) for c in table.get_row_at(i)),
        ]
    code = re.compile(r"util_|hours_low|effective_date|\bmode\b|\bstd\b|\bsims\b")
    for text in shown:
        assert not code.search(text), text
