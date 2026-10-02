"""
Budgie Textual TUI.

An interactive front-end over ``budgie.core``, laid out as the workflow the CLI
teaches -- left to right, data to conclusion:

    1 Inputs       the project's files: what exists, and open one in $EDITOR
    2 Plan         who is on the project and when; re-plan by appending a row
    3 Forecast     assumptions in, cost + Monte Carlo out, recomputed live
    4 Assumptions  what the engine assumes, so it isn't folklore

That order is the point: you cannot read a forecast sensibly without knowing
what went into it, so the inputs come first and the model's assumptions are one
keystroke away from the number they produced. The app opens on Forecast when it
can compute one and on Inputs when it can't, because a broken input is the only
thing worth looking at until it's fixed.

Like every other front-end this file contains no budgeting math -- it wires
widgets to the engine. The one thing it *writes* is a plan row, and it appends
rather than edits, because that is what :mod:`budgie.core.plan` models: history
is a record, not mutable current state.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import ClassVar

import numpy as np
from textual.app import App, ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Input,
    Label,
    Static,
    TabbedContent,
    TabPane,
)

from budgie.core.allocation import pto_overrides
from budgie.core.calendar import PTO_RULE, explain_pto, productive_hours
from budgie.core.csvio import parse_date
from budgie.core.forecast import forecast as run_forecast
from budgie.core.loader import load_people
from budgie.core.montecarlo import simulate
from budgie.core.plan import load_plan
from budgie.core.workspace import (
    INPUTS,
    PROJECTS_DIR,
    Workspace,
    available_projects,
    find_workspace,
    forget_workspaces,
)

_BLOCKS = " ▁▂▃▄▅▆▇█"

# Tabs in workflow order. The number is shown in the label so the sequence is
# legible at a glance and the 1-5 keys have something obvious to map onto.
# Projects comes first because it decides what every other tab is showing.
_TABS: tuple[tuple[str, str], ...] = (
    ("tab_projects", "1 Projects"),
    ("tab_inputs", "2 Inputs"),
    ("tab_plan", "3 Plan"),
    ("tab_forecast", "4 Forecast"),
    ("tab_assumptions", "5 Assumptions"),
)

# Inputs-table geometry. A DataTable clips its cells rather than wrapping them,
# so the widths have to be chosen rather than discovered: everything here is
# fixed and the description column absorbs whatever is left.
_FILE_COL = 16  # longest scaffolded filename is `allocations.csv`
_ROWS_COL = 4
_CELL_PADDING = 2  # DataTable's default, one space either side

# `#mc_pane` is `padding: 1 2`, so four columns of its width are not content.
_MC_PANE_PADDING = 4


def ascii_histogram(values: np.ndarray, bins: int = 42, height: int = 8) -> str:
    """Render a compact vertical block histogram of ``values`` as text.

    ``bins`` is the character width of the result, so callers pass the width
    they actually have -- a histogram wider than its pane wraps and turns into
    noise, which is worse than no histogram at all.
    """
    bins = max(int(bins), 4)
    counts, _ = np.histogram(values, bins=bins)
    peak = counts.max() or 1
    # Each column is `height` block-rows tall; fill from the bottom up.
    scaled = counts / peak * height
    rows = []
    for row in range(height, 0, -1):
        line = []
        for col in scaled:
            filled = col - (row - 1)
            if filled >= 1:
                line.append(_BLOCKS[-1])
            elif filled <= 0:
                line.append(" ")
            else:
                line.append(_BLOCKS[int(filled * (len(_BLOCKS) - 1))])
        rows.append("".join(line))
    return "\n".join(rows)


def _money(x: float) -> str:
    return f"${x:,.0f}"


def shorten_path(path: str | Path, width: int = 60) -> str:
    """Truncate a path from the LEFT, keeping the part that identifies it.

    The end of a path says which file it is; the start says which disk it's on.
    Cutting the wrong end is why the old header showed a screenful of
    /private/tmp/... and never got to the filename.
    """
    text = str(path)
    if len(text) <= width:
        return text
    return "…" + text[-(width - 1) :]


def _ellipsize(text: str, width: int) -> str:
    """Trim ``text`` to ``width``, ending in an ellipsis when it was cut.

    A DataTable clips a too-long cell mid-word with no marker, which reads as a
    rendering bug. The ellipsis says the truncation was deliberate.
    """
    if len(text) <= width:
        return text
    return text[: max(width - 1, 0)].rstrip() + "…"


def open_in_editor(path: Path) -> str:
    """Open ``path`` in the user's editor, returning a status message.

    Uses ``$VISUAL``/``$EDITOR`` when set. This is the "links to the inputs"
    half of the Inputs tab -- seeing that a file exists doesn't help if you
    then have to go hunting for it in another window.
    """
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not editor:
        return f"Set $EDITOR to open files from here. Path: {path}"
    if not path.exists():
        return f"{path.name} doesn't exist yet."
    try:
        subprocess.run([*editor.split(), str(path)], check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        return f"Could not open {path.name} with {editor!r}: {exc}"
    return f"Edited {path.name}."


def append_plan_row(plan_path: Path, name: str, effective: date, fte: float) -> None:
    """Append one allocation change to the plan CSV.

    Appending, never editing: a re-plan is a new dated row, so the record of
    what changed and when survives. Creates the file with a header if needed.
    """
    if not plan_path.exists():
        plan_path.write_text("name,effective_date,fte\n")
    existing = plan_path.read_text()
    # Guard against a file whose last line has no newline.
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    with plan_path.open("a") as handle:
        handle.write(f"{prefix}{name},{effective:%Y-%m-%d},{fte:g}\n")


SUITE = "PI_SUITE"  # set by `perch tui`: app -> {"cwd", "argv"}
NO_SUITE = "start from perch tui to switch apps"


def suite_entry(name: str) -> dict | None:
    """$PI_SUITE's entry for ``name``; None when unset, malformed or absent."""
    try:
        entry = json.loads(os.environ.get(SUITE, ""))[name]
        cwd, argv = str(entry["cwd"]), [str(a) for a in entry["argv"]]
    except (ValueError, KeyError, TypeError):
        return None
    return {"cwd": cwd, "argv": argv} if argv else None


def switch(entry: dict) -> None:
    """Become the other app. Call only once the terminal is restored."""
    try:
        os.chdir(entry["cwd"])
        os.execvp(entry["argv"][0], entry["argv"])
    except OSError as exc:
        sys.exit(f"switch failed: {exc}")


class BudgieTUI(App):
    """Interactive explorer over a Budgie project."""

    CSS = """
    /* --- Title bar -----------------------------------------------------
       Textual's stock Header is one dim line, which left the app name, the
       project and the clock competing for the same row. This is two rows with
       a clear hierarchy: identity and figures on top, location below. */
    #titlebar {
        height: 1;
        background: $accent;
        color: $text;
        text-style: bold;
        padding: 0 2;
    }
    #contextbar {
        height: 1;
        background: $panel;
        color: $text-muted;
        padding: 0 2;
    }

    /* --- Tabs ----------------------------------------------------------
       The stock inactive tab is $foreground 50%, which on a dark background
       reads as disabled rather than merely unselected. These are legible at
       rest, and the active one is unmistakable. */
    Tabs {
        height: 3;
        background: $surface;
    }
    Tabs Tab {
        height: 3;
        padding: 1 3;
        color: $foreground 75%;
    }
    Tabs Tab:hover {
        color: $foreground;
        background: $boost;
    }
    Tabs Tab.-active {
        color: $text;
        background: $accent 25%;
        text-style: bold;
    }
    Underline > .underline--bar {
        color: $accent;
        background: $surface;
    }

    /* --- Shared -------------------------------------------------------- */
    /* Hidden until something goes wrong -- an empty banner is still two rows
       of alarm-coloured background, which is worse than no banner. */
    .banner {
        display: none;
        height: auto;
        padding: 1 2;
        background: $error 20%;
        color: $text;
    }
    .hint { padding: 1 2; color: $text-muted; }
    .status { padding: 0 2; color: $success; height: 1; }
    .pane-title { text-style: bold; padding: 0 0 1 0; }

    /* --- Forecast tab --------------------------------------------------
       The controls were nearly a quarter of the screen for four numbers.
       A bordered, titled box reads as "controls" rather than content, and
       keeps them to a single compact row. */
    #controls {
        height: auto;
        border: round $primary;
        border-title-color: $text-muted;
        padding: 0 1;
        margin: 1 1 0 1;
    }
    #controls Input { width: 9; border: none; padding: 0 1; height: 1; }
    #controls Label { padding: 0 1 0 2; color: $text-muted; }
    #controls Button { height: 1; border: none; margin: 0 0 0 2; }
    #forecast_body { height: 1fr; }
    #table_pane { width: 3fr; padding: 1 1 0 1; }
    #mc_pane { width: 2fr; padding: 1 2 0 2; background: $panel; }
    #hist { color: $success; height: auto; padding: 1 0; }
    #mc_figures { height: auto; }
    #source { color: $text-muted; height: auto; padding: 1 0 0 0; }

    /* --- Plan tab ------------------------------------------------------ */
    #plan_form {
        height: auto;
        border: round $primary;
        border-title-color: $text-muted;
        padding: 0 1;
        margin: 1 1 0 1;
    }
    #plan_form Input { width: 14; border: none; padding: 0 1; height: 1; }
    #plan_form Label { padding: 0 1 0 2; color: $text-muted; }
    #plan_form Button { height: 1; border: none; margin: 0 0 0 2; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        ("r", "recalculate", "Recalculate"),
        ("e", "edit_selected", "Edit input"),
        ("d", "delete_project", "Delete project"),
        ("1", "show_tab('tab_projects')", "Projects"),
        ("2", "show_tab('tab_inputs')", "Inputs"),
        ("3", "show_tab('tab_plan')", "Plan"),
        ("4", "show_tab('tab_forecast')", "Forecast"),
        ("5", "show_tab('tab_assumptions')", "Assumptions"),
        ("P", "switch('perch')", "perch"),
        ("G", "switch('gitboard')", "gitboard"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, csv_path: str | Path | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.workspace: Workspace | None = find_workspace()
        # An explicit path still wins, exactly like on the command line.
        self._people_override = str(csv_path) if csv_path else None
        self._load_error: str | None = None
        # Which project the next `d` would actually delete. Set by the first
        # press and cleared by anything else, so deletion always takes two
        # deliberate keystrokes aimed at the same row.
        self._delete_armed: str | None = None

    # -- paths -------------------------------------------------------------

    @property
    def people_path(self) -> str:
        if self._people_override:
            return self._people_override
        if self.workspace:
            resolved = self.workspace.resolve("people")
            if resolved:
                return resolved
        return str(Path(__file__).parent / "tests" / "team.csv")

    @property
    def plan_path(self) -> Path | None:
        return self.workspace.path_for("plan") if self.workspace else None

    @property
    def project_name(self) -> str:
        return self.workspace.root.name if self.workspace else "no project"

    def projects(self) -> list:
        """The budgets on offer: siblings of the current one, else whatever is
        below the working directory."""
        return available_projects(self.workspace.root if self.workspace else Path.cwd())

    def action_switch(self, target: str) -> None:
        """Hand the terminal to perch or gitboard; nothing written is lost."""
        if suite_entry(target) is None:
            self.notify(NO_SUITE, severity="warning")
            return
        self.exit(target)

    # -- layout ------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static(id="titlebar")
        yield Static(id="contextbar")
        with TabbedContent(initial="tab_forecast", id="tabs"):
            with TabPane(_TABS[0][1], id=_TABS[0][0]):
                yield from self._compose_projects()
            with TabPane(_TABS[1][1], id=_TABS[1][0]):
                yield from self._compose_inputs()
            with TabPane(_TABS[2][1], id=_TABS[2][0]):
                yield from self._compose_plan()
            with TabPane(_TABS[3][1], id=_TABS[3][0]):
                yield from self._compose_forecast()
            with TabPane(_TABS[4][1], id=_TABS[4][0]):
                yield VerticalScroll(Static(id="assumptions_text"))
        yield Footer()

    def _compose_projects(self) -> ComposeResult:
        yield Static(
            f"Budgets under [b]{PROJECTS_DIR}/[/b]. Select one and press "
            "[b]enter[/b] to switch every other tab to it, or [b]d[/b] twice "
            "to delete it.",
            classes="hint",
        )
        yield DataTable(id="projects_table")
        yield Static(id="projects_status", classes="status")

    def _compose_forecast(self) -> ComposeResult:
        controls = Horizontal(id="controls")
        controls.border_title = "Assumptions"
        with controls:
            yield Label("Year")
            yield Input(
                value=str(self._setting("year", 2026)), id="year", type="integer"
            )
            yield Label("PTO days")
            yield Input(value=str(self._setting("pto", 0)), id="pto", type="number")
            yield Label("Iterations")
            yield Input(
                value=str(self._setting("iterations", 10_000)),
                id="iterations",
                type="integer",
            )
            yield Label("Seed")
            yield Input(value=str(self._setting("seed", 42)), id="seed", type="integer")
            yield Button("Recalculate", id="recalc", variant="primary")
        yield Static(id="forecast_banner", classes="banner")
        with Horizontal(id="forecast_body"):
            with Vertical(id="table_pane"):
                yield DataTable(id="forecast")
            with VerticalScroll(id="mc_pane"):
                yield Static("Monte Carlo", classes="pane-title")
                yield Static(id="mc_figures")
                yield Static(id="hist")
                yield Static(id="mc_stats")
                yield Static(id="source")

    def _compose_plan(self) -> ComposeResult:
        yield Static(
            "Re-planning appends a dated row -- it never edits history. "
            "0 FTE takes someone off the project.",
            classes="hint",
        )
        form = Horizontal(id="plan_form")
        form.border_title = "Append a change"
        with form:
            yield Label("Name")
            yield Input(placeholder="Alice", id="plan_name")
            yield Label("From")
            yield Input(placeholder="2026-09-01", id="plan_date")
            yield Label("FTE")
            yield Input(placeholder="0.5", id="plan_fte", type="number")
            yield Button("Add row", id="add_plan_row", variant="primary")
        yield Static(id="plan_status", classes="status")
        yield DataTable(id="plan_table")

    def _compose_inputs(self) -> ComposeResult:
        yield Static(
            "Your project's files. Select one and press [b]e[/b] to open it in "
            "$EDITOR, then [b]r[/b] to recalculate.",
            classes="hint",
        )
        yield DataTable(id="inputs_table")
        yield Static(id="inputs_status", classes="status")

    # -- lifecycle ---------------------------------------------------------

    def on_mount(self) -> None:
        self.title = "Budgie"
        self.sub_title = str(self.workspace.root) if self.workspace else "no project"

        forecast_table = self.query_one("#forecast", DataTable)
        forecast_table.add_columns("Name", "$/hr", "Hours", "Cost")
        forecast_table.zebra_stripes = True

        plan_table = self.query_one("#plan_table", DataTable)
        plan_table.add_columns("Name", "Changes", "Allocated hours")
        plan_table.zebra_stripes = True

        inputs_table = self.query_one("#inputs_table", DataTable)
        inputs_table.cursor_type = "row"
        inputs_table.zebra_stripes = True

        projects_table = self.query_one("#projects_table", DataTable)
        projects_table.cursor_type = "row"
        projects_table.zebra_stripes = True

        self.recalculate()
        # Open on Forecast when there is one, otherwise on the tab that can fix
        # what's wrong -- landing on a tab that can only show an error helps
        # nobody. `recalculate` has already tried the load, so this reads the
        # outcome rather than parsing the file a second time. No workspace but
        # projects on disk is the ambiguous case the browser exists to settle,
        # and it outranks a load error: there is nothing to load yet.
        if self.workspace is None and self.projects():
            self.action_show_tab("tab_projects")
        elif self._load_error is not None:
            self.action_show_tab("tab_inputs")

    def _setting(self, key: str, default):
        if self.workspace:
            return self.workspace.setting(key, default)
        return default

    # -- events ------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "recalc":
            self.recalculate()
        elif event.button.id == "add_plan_row":
            self.add_plan_row()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id and event.input.id.startswith("plan_"):
            self.add_plan_row()
        else:
            self.recalculate()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        # Three tables share this event; only the project browser acts on it.
        if event.data_table.id == "projects_table":
            self.action_open_project()

    def action_recalculate(self) -> None:
        self.recalculate()

    def action_show_tab(self, tab_id: str) -> None:
        self.query_one("#tabs", TabbedContent).active = tab_id

    def action_edit_selected(self) -> None:
        """Open the highlighted input file in $EDITOR."""
        table = self.query_one("#inputs_table", DataTable)
        status = self.query_one("#inputs_status", Static)
        self.action_show_tab("tab_inputs")
        if self.workspace is None:
            status.update("No project here -- run `budgie init` to create one.")
            return
        items = self.workspace.inputs()
        row = table.cursor_row
        if not 0 <= row < len(items):
            status.update("Select a file first.")
            return
        with self.suspend():
            message = open_in_editor(items[row].path)
        # Recalculate first: it rewrites this same status line with whatever
        # the edited file now says, and the editor's own message is the newer
        # news of the two.
        self.recalculate()
        status.update(message)

    # -- reading the form --------------------------------------------------

    def _read_int(self, widget_id: str, default: int) -> int:
        try:
            return int(self.query_one(f"#{widget_id}", Input).value)
        except (ValueError, TypeError):
            return default

    def _read_float(self, widget_id: str, default: float) -> float:
        try:
            return float(self.query_one(f"#{widget_id}", Input).value)
        except (ValueError, TypeError):
            return default

    # -- actions -----------------------------------------------------------

    def add_plan_row(self) -> str:
        """Append the form's row to the plan CSV and refresh the plan table.

        Returns the status message it displayed, so the outcome is observable
        without reaching into the widget.
        """
        path = self.plan_path
        if path is None:
            return self._plan_status("No project here -- run `budgie init` first.")

        name = self.query_one("#plan_name", Input).value.strip()
        raw_date = self.query_one("#plan_date", Input).value.strip()
        raw_fte = self.query_one("#plan_fte", Input).value.strip()
        if not (name and raw_date and raw_fte):
            return self._plan_status("Name, from-date and FTE are all needed.")

        try:
            effective = parse_date(raw_date)
            fte = float(raw_fte)
        except ValueError as exc:
            return self._plan_status(str(exc))
        if fte < 0:
            return self._plan_status("FTE cannot be negative.")

        append_plan_row(path, name, effective, fte)
        # Clear the form so the same row can't be added twice by a stray Enter.
        for widget_id in ("plan_name", "plan_date", "plan_fte"):
            self.query_one(f"#{widget_id}", Input).value = ""
        self.recalculate()
        return self._plan_status(
            f"Added {name} → {fte:g} FTE from {effective} ({path.name})"
        )

    def _plan_status(self, message: str) -> str:
        self.query_one("#plan_status", Static).update(message)
        return message

    def switch_project(self, name: str) -> str:
        """Point the whole app at project ``name``.

        Returns the status message it displayed, so the outcome is observable
        without reaching into the widget.
        """
        for project in self.projects():
            if project.name != name:
                continue
            workspace = self._open(project)
            if workspace is None:
                return self._projects_status(
                    f"{name}'s {project.config_path.name} won't load -- fix it first."
                )
            self.workspace = workspace
            # A --people path given at launch was an instruction about the old
            # project; picking a new one in the browser is the newer of the two,
            # and leaving it set would make the switch look like it did nothing.
            self._people_override = None
            self._load_error = None
            self.recalculate()
            return self._projects_status(f"Switched to {name}")
        return self._projects_status(f"No project called {name}")

    @staticmethod
    def _open(project):
        """The project's workspace, or None if its config won't load.

        The browser lists every project nearby, so one of them being broken is
        a normal state -- the same stance as a people.csv that won't parse.
        """
        try:
            return project.load()
        except (OSError, TypeError, ValueError):
            return None

    def _projects_status(self, message: str) -> str:
        self.query_one("#projects_status", Static).update(message)
        return message

    def selected_project(self) -> str | None:
        """The name under the cursor in the projects table, if any."""
        projects = self.projects()
        row = self.query_one("#projects_table", DataTable).cursor_row
        return projects[row].name if 0 <= row < len(projects) else None

    def project_names(self) -> list[str]:
        """The projects on offer, in listed order."""
        return [p.name for p in self.projects()]

    def project_marks(self) -> dict[str, str]:
        """Name -> marker as the table is actually rendering it.

        Read back off the table rather than recomputed, so a test sees what a
        user would see.
        """
        table = self.query_one("#projects_table", DataTable)
        rows = (table.get_row_at(i) for i in range(table.row_count))
        return {str(row[1]): str(row[0]) for row in rows}

    def action_open_project(self) -> str:
        name = self.selected_project()
        if name is None:
            return self._projects_status("No project to open.")
        return self.switch_project(name)

    def action_delete_project(self) -> str:
        """Delete the selected project -- on the second press, not the first.

        There is no undo and no modal in this app, so the arming step *is* the
        confirmation: the first `d` names what would go, the second does it.
        Aiming at a different row in between disarms, so a stale confirmation
        can't land on whatever happens to be under the cursor.
        """
        from budgie.core.scaffold import delete_project

        self.action_show_tab("tab_projects")
        name = self.selected_project()
        if name is None:
            return self._projects_status("No project selected.")

        if self._delete_armed != name:
            self._delete_armed = name
            return self._projects_status(
                f"Delete {name} and everything in it? Press d again to confirm, "
                f"any other key to cancel. This cannot be undone."
            )

        target = next((p for p in self.projects() if p.name == name), None)
        self._delete_armed = None
        if target is None:
            return self._projects_status(f"No project called {name}.")
        try:
            removed = delete_project(target.root)
        except (OSError, ValueError) as exc:
            return self._projects_status(str(exc))

        # The deleted project may be the one being displayed; drop it and let
        # what's left be re-discovered rather than showing numbers from a
        # directory that no longer exists.
        if self.workspace is not None and self.workspace.root == target.root:
            self.workspace = None
            self._people_override = None
            remaining = self.projects()
            if len(remaining) == 1:
                self.workspace = self._open(remaining[0])
        forget_workspaces()
        self.recalculate()
        return self._projects_status(f"Deleted {name} ({len(removed)} file(s)).")

    def on_key(self, event) -> None:
        # Any key that isn't the confirming `d` cancels a pending delete, so an
        # armed confirmation never outlives the moment it was offered.
        if self._delete_armed is not None and event.key != "d":
            self._delete_armed = None
            self._projects_status("Cancelled.")

    def recalculate(self) -> None:
        year = self._read_int("year", 2026)
        pto = self._read_float("pto", 0.0)
        iterations = max(self._read_int("iterations", 10_000), 100)
        seed = self._read_int("seed", 42)

        ph = productive_hours(year, pto_days=pto)
        self._refresh_chrome(year, pto)
        self._refresh_projects()
        self._refresh_forecast(ph, iterations, seed)
        self._refresh_plan(year, pto)
        self._refresh_inputs()
        self._refresh_assumptions(ph, year)

    def _refresh_projects(self) -> None:
        """List the projects, marking the one in play."""
        table = self.query_one("#projects_table", DataTable)
        cursor = table.cursor_row
        table.clear(columns=True)
        table.add_columns("", "Project", "Inputs", "Location")

        current = self.workspace.root if self.workspace else None
        projects = self.projects()
        for project in projects:
            # A neighbour's broken budgie.yaml is that project's problem: say
            # so on its row rather than taking the whole browser down with it.
            workspace = self._open(project)
            if workspace is None:
                inputs = "[red]bad config[/red]"
            else:
                present = sum(1 for i in workspace.inputs() if i.exists)
                inputs = f"{present}/{len(INPUTS)}"
            table.add_row(
                "→" if project.root == current else "",
                project.name,
                inputs,
                shorten_path(project.root, max(self.size.width - 40, 20)),
            )
        if projects:
            # Keep the cursor where the user left it across a recalculate.
            table.move_cursor(row=min(cursor, len(projects) - 1))
        else:
            self._projects_status(
                f"No projects found. `budgie init NAME` writes one "
                f"under {PROJECTS_DIR}/."
            )

    # -- rendering ---------------------------------------------------------

    def _refresh_chrome(self, year: int, pto: float) -> None:
        """The two header rows: who/what/when on top, where below."""
        figures = f"{year}   ·   PTO {pto:g}d   ·   {self._clock()}"
        self.query_one("#titlebar", Static).update(
            f"BUDGIE   {self.project_name}{' ' * 4}[not bold]{figures}[/not bold]"
        )
        location = (
            shorten_path(self.workspace.root, 70)
            if self.workspace
            else "no project here — run `budgie init` to make one"
        )
        self.query_one("#contextbar", Static).update(location)

    @staticmethod
    def _clock() -> str:
        # Local time: the point is "did my keypress take effect", not UTC.
        return datetime.now().strftime("%H:%M:%S")  # noqa: DTZ005

    def _mc_width(self) -> int:
        """Content width of the Monte Carlo pane, in characters.

        Derived from the app width and the 3fr/2fr split rather than read off
        the widget: the first render happens from ``on_mount``, before layout
        has run, so ``#mc_pane.size.width`` is still 0 and a fallback guess
        would lay out the one pass a user actually sees on startup.
        """
        return max(int(self.size.width * 2 / 5) - _MC_PANE_PADDING, 12)

    def _refresh_forecast(self, ph, iterations: int, seed: int) -> None:
        banner = self.query_one("#forecast_banner", Static)
        table = self.query_one("#forecast", DataTable)
        try:
            people = load_people(self.people_path, productive_hours=ph)
        except (OSError, ValueError) as exc:
            # A missing or malformed CSV is a normal state to be in, not a
            # crash: say which file and what to read to fix it.
            self._load_error = f"Can't read {Path(self.people_path).name}: {exc}"
            banner.display = True
            banner.update(
                f"{self._load_error}\n"
                f"Fix the file, then press r. `budgie guide people` explains "
                f"the columns."
            )
            table.clear()
            return

        self._load_error = None
        banner.display = False
        det = run_forecast(people)
        sim = simulate(people, iterations=iterations, seed=seed)
        pct = sim.percentiles()

        table.clear()
        for item in det.line_items:
            table.add_row(
                item.name,
                _money(item.hourly_cost),
                f"{item.hours:,.0f}",
                _money(item.cost),
            )
        table.add_row(
            "[b]Total[/b]",
            "",
            f"[b]{det.total_hours:,.0f}[/b]",
            f"[b]{_money(det.total_cost)}[/b]",
        )

        width = self._mc_width()
        # Fit the histogram to the pane; a wider one wraps into noise.
        self.query_one("#hist", Static).update(
            ascii_histogram(sim.total_costs, bins=width)
        )

        # Percentiles as aligned rows rather than one wrapping line -- three
        # numbers meant to be compared should sit in a column. The gloss is the
        # first thing dropped on a narrow pane: a wrapped label costs a whole
        # row and pushes the figure it explains away from it.
        glosses = ("optimistic", "expected", "reserve this")
        room = width >= 34
        self.query_one("#mc_figures", Static).update(
            "\n".join(
                f"{style}  {_money(pct[p]):>12}"
                + (f"   [dim]{gloss}[/dim]" if room else "")
                for p, style, gloss in zip(
                    (10, 50, 90),
                    ("[green]P10[/green]", "[b]P50[/b]", "[green]P90[/green]"),
                    glosses,
                )
            )
        )
        # One figure per line. Run these together and the pane wraps them at
        # whatever column it reaches, which breaks a number across two rows.
        self.query_one("#mc_stats", Static).update(
            f"{sim.iterations:,} sims\n"
            f"mean {_money(sim.mean)}   std {_money(sim.std)}\n"
            f"[dim]available hours {ph.available_hours:,.0f} @ 1.0 FTE[/dim]"
        )
        self.query_one("#source", Static).update(
            # -8 for the "people: " label, -2 for the pane's scrollbar: this
            # line is the last thing in a VerticalScroll, so the bar is usually
            # there and a path sized to the full width wraps under its label.
            f"[dim]people:[/dim] {shorten_path(self.people_path, max(width - 10, 12))}"
        )

    def _refresh_plan(self, year: int, pto: float) -> None:
        table = self.query_one("#plan_table", DataTable)
        table.clear()
        path = self.plan_path
        if path is None or not path.exists():
            table.add_row("[dim]no plan.csv in this project[/dim]", "", "")
            return

        # A person's own pto_days (allocations.csv) applies here too, or this
        # tab and `budgie hours` disagree about the same plan.
        allocations = self.workspace.resolve("allocations") if self.workspace else None
        try:
            plan = load_plan(path)
            pto_by_name = pto_overrides(allocations) if allocations else {}
        except (OSError, ValueError) as exc:
            table.add_row(f"[red]{exc}[/red]", "", "")
            return

        total = 0.0
        for name in plan.names:
            hours = plan.allocated_hours(
                name, year, pto_days=pto_by_name.get(name, pto)
            )
            total += hours
            changes = ", ".join(
                f"{e.effective_date:%b %-d}→{e.fte:g}" for e in plan.changes_for(name)
            )
            table.add_row(name, changes, f"{hours:,.0f}")
        table.add_row("[b]Total[/b]", "", f"[b]{total:,.0f}[/b]")

    def _refresh_inputs(self) -> None:
        # Say why we're here. Arriving on this tab because a file wouldn't load
        # is confusing unless the reason arrives with you.
        self.query_one("#inputs_status", Static).update(
            "" if self._load_error is None else f"[red]{self._load_error}[/red]"
        )
        table = self.query_one("#inputs_table", DataTable)
        items = self.workspace.inputs() if self.workspace else []
        used_by = [" ".join(item.used_by) for item in items]

        # Columns are rebuilt each refresh because the description column is
        # sized to whatever room is left over. A DataTable clips rather than
        # wraps, and the rightmost column is the one that says what feeds what
        # -- letting prose push it off the screen loses the point of the tab.
        table.clear(columns=True)
        width = table.size.width or self.size.width
        fixed = _FILE_COL + _ROWS_COL + max(map(len, used_by), default=0) + 1
        description_width = max(width - fixed - _CELL_PADDING * 5, 20)

        table.add_column("", width=1)
        table.add_column("File", width=_FILE_COL)
        table.add_column("Rows", width=_ROWS_COL)
        table.add_column("What it is", width=description_width)
        table.add_column("Used by")

        if self.workspace is None:
            table.add_row(
                "", "[dim]no budgie.yaml[/dim]", "", "Run `budgie init` to start", ""
            )
            return
        for item, used in zip(items, used_by):
            table.add_row(
                "[green]✓[/green]" if item.exists else "[dim]·[/dim]",
                item.path.name if item.exists else f"[dim]{item.path.name}[/dim]",
                "" if item.rows is None else str(item.rows),
                _ellipsize(item.description, description_width),
                used,
            )

    def _refresh_assumptions(self, ph, year: int) -> None:
        lines = [
            f"[b]Assumptions in force for {year}[/b]\n",
            f"Gross hours          {ph.gross_hours:,.0f}  (40 h x 52 weeks)",
            f"Federal holidays    -{ph.holiday_hours:,.0f}",
            f"Productive hours     {ph.productive_hours:,.0f}",
            f"PTO                 -{ph.pto_hours:,.0f}  ({ph.pto_days:g} days)",
            f"Available hours      {ph.available_hours:,.0f}  (1.0 FTE)\n",
            f"[b]PTO and part-time[/b]\n{PTO_RULE}\n",
            f"  {explain_pto(ph)}\n",
            "[b]Uncertainty[/b]",
            "  Hours are a triangular low/mode/high draw; the table above uses",
            "  the mode. The Monte Carlo redraws every person each iteration.\n",
            "[b]Inputs[/b]",
            *(
                f"  {default:<16} {description}"
                for default, description, _used in INPUTS.values()
            ),
        ]
        self.query_one("#assumptions_text", Static).update("\n".join(lines))


def run(csv_path: str | Path | None = None) -> None:
    target = BudgieTUI(csv_path).run()
    if target:
        switch(suite_entry(target))
