# CLAUDE.md

## Project

Budgie is a CLI budget/forecasting companion — a terminal alternative to spreadsheet budgeting. It forecasts team cost from each person's **hourly cost × productive hours**, and puts confidence bounds around that forecast with a Monte Carlo simulation over uncertain expected hours. It is **CLI-first**, with a Textual TUI (`budgie tui`) over the same engine; the engine is deliberately UI-independent so either front-end can change without touching the math.

## Install & Run

Editable install, then invoke via the `budgie` console script (`pyproject.toml` → `budgie.budgie:cli`):

```bash
pip install -e .                 # to use it (runtime deps only)
pip install -e '.[dev]'           # to work on it: adds pytest, pytest-asyncio, ruff, isort
                                 # or: make venv  (builds the venv and installs '.[dev]')
```

There is a user-facing `README.md` covering install, every command, and the input file
formats — keep it in sync when commands or CSV shapes change.

Or run the module directly: `python -m budgie.budgie forecast ...`.

Note: this project is typically installed into a virtualenv. Be careful that the interpreter running the package matches the one `pip`/`pytest` use — a bare `python3` on PATH may be a different version than where the package is installed.

**The venv lives outside the repo, at `~/Documents/tools/budgie`** (alongside the other tools there), so the working tree holds no build artifacts. `Makefile` `VENV ?=` sets it; every target takes `VENV=` to override. Run the suite as `~/Documents/tools/budgie/bin/pytest`.

**macOS hidden-`.pth` trap.** `site.addpackage` *silently skips any `.pth` file carrying the `UF_HIDDEN` flag* — so an editable install can report success while the package stays unimportable, and `budgie` dies with `ModuleNotFoundError: No module named 'budgie'`. The tell: importing works from the repo root (cwd puts `./budgie/` on `sys.path`) but fails from anywhere else, and every test module errors on collection at once. Diagnose from a **neutral cwd** — testing from the repo root gives a false pass. `/bin/ls -lO <site-packages>` shows the flag; `chflags nohidden <file>` clears it (`chflags -R` skips symlinks — use `find ... -print0 | xargs -0 chflags -h nohidden`). Moving the venv out of the tree is what keeps whatever hides files from reaching it.

## Commands

- Docs: `make docs` (`sphinx-build -W` into `docs/_build/html`; needs the `docs` extra). CI runs the same build.
  - The user-guide pages **include `README.md` in pieces** rather than copying it, cut on the exact text of its `## ` headings (`:start-after:` / `:end-before:` in `docs/*.md`). Renaming or reordering a README `## ` section means updating those pages; the `-W` build fails if a cut point goes missing. The CLI reference is sphinx-click over `cli`, and the API reference is autodoc over `budgie.core` (Google-style `Args:` sections via napoleon) — so a new core module needs an `automodule` line in `docs/api.md`.

## Architecture

**The core rule: all budgeting/forecast math lives in `budgie/core/` and imports no UI (`no click`, `no rich`, `no matplotlib`). Front-ends are thin adapters over it.** This is what keeps the CLI/TUI/GUI decision reversible.

**Second rule: nothing heavy is imported at module scope in `budgie/budgie.py`.** Click imports that file just to build the command tree, so engine and rendering imports live inside the command that needs them. `budgie --help` used to take 8+ seconds; it's now ~0.1s. `budgie/tests/test_startup.py` fails if numpy/holidays/matplotlib/textual/yaml/pyfiglet get imported by `import budgie.budgie`, or if anything reaches for pandas.

Per-module notes load on demand: `budgie/core/CLAUDE.md` for the engine modules, `budgie/tests/CLAUDE.md` for testing notes.

Presentation layers (all thin adapters over `core/`):
- `budgie/budgie.py` — click CLI. `cli` is a `@click.group()`; subcommands are `@click.command()`s registered via `cli.add_command(...)`.
  - **Every input/setting option defaults to `None`**, not to a value. That's what makes "the user said nothing" distinguishable from "the user asked for the default", which is what lets the workspace supply a default without the option always winning. Resolution goes through `_input(key, override, sample)` (explicit > project file > bundled sample), `_workspace_input(key)` (project file or nothing, for genuinely optional inputs where a sample would invent data), and `_setting(key, override, default)`. Adding an option means adding the matching resolve call — a `default=` in the decorator would silently shadow the project.
  - **`--project` is `_project_option`, a shared `click.option` with `expose_value=False`.** Its callback records the name in the module-level `_SELECTED_PROJECT`, which `_workspace()` feeds to `find_workspace`. That's why adding it to a command is a one-line decorator with no signature change. The group callback calls `_forget_project()` first — it runs *before* the subcommand's options are parsed, so it clears the previous invocation without discarding this one's. Without that reset, one command's `--project` leaks into the next in any process that calls `cli` more than once (the test suite does, and caught it).
  - `_no_project_message()` distinguishes *no* project from *several*: telling someone who has two budgets to "run budgie init" is nonsense advice.
  - `init` prompts for a project name via `_ask_project_name`, guarded by `_interactive()` — a named function precisely so tests can monkeypatch it, since `CliRunner` swaps out `sys.stdin` wholesale. No terminal means take the default rather than abort on EOF, so `budgie init` stays scriptable.
  - `_SIGNAL_STYLE` is keyed by `Signal.name`, not the enum, so rendering never imports the engine.
  - The group is `invoke_without_command=True, add_help_option=False` with its own `-h/--help` flag, so bare `budgie` and `budgie --help` both render the grouped overview from `guide_ui`. Click's built-in group help is a flat alphabetical list that tells a new user nothing about what to run second. Subcommands keep click's normal `--help`.
- `budgie/guide_ui.py` — rich rendering for the landing screen, the walkthrough and the topic pages. On the bare-`budgie` path, so it must stay cheap: rich only, no engine, no pyfiglet. Prose that wraps goes through `_indented()` or a borderless two-column `Table` — `console.print(f"    {text}")` only indents the *first* line, and rich wraps the rest to column zero.
- `budgie/tui.py` — Textual TUI (`BudgieTUI`), five tabs over the workspace in **workflow order, data to conclusion**: `1` Projects (browse and switch), `2` Inputs (list + open in `$EDITOR`), `3` Plan (append a dated change), `4` Forecast (built from `load_snapshot` like the CLI: plan-driven hours, readings, costs, budget; leads with a budget · spent · P50 · headroom · stoplight line from `_headline()`, warnings in the banner; year/PTO/iterations/seed come from budgie.yaml only, the old per-session boxes are gone; the sample or a `--people` file keeps the plain people.csv path), `5` Assumptions. `_TABS` is the one place that order lives, and the number keys are bindings onto it. `e` opens the file the current tab shows (`_edit_target`: Plan → plan.csv, Forecast → people.csv but never the bundled sample, Inputs → the highlighted row, Projects → the open project's budgie.yaml). Status lines go through `_status(..., error=)`, which toggles the red `.error` class; failures are red, successes green. `ascii_histogram()` renders the distribution as block characters.
  - `d` deletes the selected project, **only from the Projects tab** (`check_action` hides it elsewhere; keys are app-global, and on Plan `d` reads as "delete this row") and **only on the second press** — `_delete_armed` holds the name the first press offered, and `on_key` clears it on any other key, so a stale confirmation can't land on whatever happens to be under the cursor. There are no modals in this app; the arming step *is* the confirmation. Deleting the open project drops the workspace and re-resolves, rather than displaying numbers from a directory that no longer exists.
  - **The Projects tab is how you change budget without quitting.** `switch_project(name)` repoints `self.workspace` and recalculates everything; it also **clears `_people_override`**, because a `--people` path given at launch was an instruction about the old project and keeping it would make the switch look like it did nothing. `_projects_root()` is what makes browsing work from *inside* a project: from `budget/fy26` it searches two levels up, so the siblings are reachable. `switch_project` returns its status message, and `project_names()` / `project_marks()` expose the listing — `project_marks()` reads back off the `DataTable` so a test sees what a user sees.
  - **A neighbour's broken `budgie.yaml` is a normal state too.** The browser loads every nearby project to count its inputs, so `_open(project)` returns `None` instead of raising: the row reads "bad config", and `switch_project` refuses with a message rather than crashing. This also removed a test-order dependency — `test_workspace.py` leaves a deliberately broken config in a sibling tmp dir, and the TUI tests only passed because they sorted first.
  - **The only thing the TUI writes is a plan row, and it appends.** `append_plan_row()` never edits an existing row, because that's what `core/plan.py` models — history is a record, not mutable state.
  - `add_plan_row()` returns the status message it displayed, so tests can assert the outcome without reaching into widget internals.
  - A people.csv that won't load is a **normal state**, not a crash: `_refresh_forecast` catches it into `_load_error`, shows a banner naming the file, empties the table rather than leaving stale numbers, and `on_mount` opens on Inputs instead of Forecast — the tab that can fix it rather than the one that can only complain. No workspace *but* projects on disk outranks that and opens on Projects: there is nothing to load yet, so the ambiguity is the real problem.
  - **Layout widths are computed, not read off widgets.** The first render runs from `on_mount`, *before* Textual has laid anything out, so `widget.size.width` is still 0 — the one pass a user sees on startup would be laid out against a fallback guess. `_mc_width()` derives the Monte Carlo pane from the app width and the 3fr/2fr split instead. A `DataTable` clips rather than wraps, so the Inputs table rebuilds its columns each refresh with the description sized to what's left over and `_ellipsize`d, keeping "Used by" on screen. (`budgie status` renders the same data through a rich `Table`, which wraps, so it doesn't need any of this.)
  - TUI tests are async (`App.run_test()`); `pyproject.toml` sets `asyncio_mode = "auto"` so they don't each need a marker. `run_test(size=...)` is how the responsive behaviour is tested; `_text()` reads a `Static` back via `.content` (Textual 8 dropped `.renderable`).
- `budgie/emails.py` — renders a per-person `EmailDraft` from an `Allocation` and writes draft files. **Renders only; never sends** — sending is left to a reviewed, explicit step.
  - `budgie emails` defaults to `--html` (`.eml` + per-person burn-down charts under `emails/charts/`); `--plain` is the opt-out. It used to default the other way, which is why it looked like the charts were broken.
  - `pace_sentence()` restates remaining hours as a weekly commitment and goes in **both** the HTML body and the `text/plain` part — a recipient whose client blocks HTML must still get the whole message, so `build_message()` passes `status.required_pace` into `render_email()`. Forgetting that is a silent content loss, not an error.
  - **Outlook path:** `render_html_email()` / `build_message()` / `write_eml_drafts()` produce `.eml` files. Outlook renders HTML through Word, so the markup is **table-based with inline styles only** (no flex/grid) and the chart is a **`cid:` attachment, never a base64 `data:` URI** (Outlook desktop won't display those). MIME shape is `multipart/alternative` → text/plain + (`multipart/related` → text/html + image with `Content-ID: <burndown>`).
  - The HTML template builds its rows into a `rows` variable first so the big f-string holds only simple substitutions — otherwise `ruff format` reflows call expressions inside the template into unreadable shapes.
- `budgie/singletons.py` — shared `console`, `logger`, `header` banner, and `set_verbose()`. Import these rather than constructing new instances.
  - **Logging rule:** this is the *only* place rich is wired into logging. Modules under `core/` use plain `logging.getLogger(__name__)` and never import rich — their records propagate to the root handler configured here, so the engine stays UI-free while still logging rich-formatted under a front-end. Never `from budgie.singletons import logger` inside `core/`; that would break the no-UI rule.
  - Root level is **INFO** so third-party DEBUG (matplotlib's font manager emits hundreds of records per figure) doesn't flood output. `set_verbose(True)`, wired to the CLI's `-v/--verbose`, raises **only** the `budgie` package logger to DEBUG.

## Non-interactive shell commands

The agent's shell has no TTY, so a command that waits for y/n input hangs. Use the non-interactive form where one exists: `-o BatchMode=yes` for `ssh`/`scp`; `HOMEBREW_NO_AUTO_UPDATE=1` for `brew`.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:46cd31e7 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   bd dolt push
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->
