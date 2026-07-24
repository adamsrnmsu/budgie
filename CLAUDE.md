# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Budgie is a CLI budget/forecasting companion — a terminal alternative to spreadsheet budgeting. It forecasts team cost from each person's **hourly cost × productive hours**, and puts confidence bounds around that forecast with a Monte Carlo simulation over uncertain expected hours. Direction is **CLI-first**, with a Textual TUI planned later; the engine is deliberately UI-independent so that choice stays reversible.

## Install & Run

Editable install, then invoke via the `budgie` console script (`pyproject.toml` → `budgie.budgie:cli`):

```bash
pip install -e .                 # or: make venv  (creates .venv and installs)
budgie init                      # scaffold a project (budgie.yaml + starter CSVs)
budgie status                    # which inputs exist, and what feeds what
budgie assumptions               # every modelling assumption + where it's set
budgie forecast --people tests/team.csv --year 2026 --pto 15 --seed 42 --plots
budgie tui                       # 4-tab explorer: Forecast / Plan / Inputs / Assumptions
budgie hours                     # FTE allocated / spent / remaining per person
budgie emails --out-dir emails   # Outlook .eml drafts + charts by default (never sends)
budgie emails --plain            # plain-text drafts instead
budgie scenario                  # compare what-if scenarios with stoplight signals
budgie monthly --budget 720000   # per-month cost + cumulative P10/P90 fan
```

There is a user-facing `README.md` covering install, every command, and the input file
formats — keep it in sync when commands or CSV shapes change.

Or run the module directly: `python -m budgie.budgie forecast ...`.

Note: this project is typically installed into a virtualenv. Be careful that the interpreter running the package matches the one `pip`/`pytest` use — a bare `python3` on PATH may be a different version than where the package is installed.

## Commands

- Lint: `ruff check .` (the `Makefile` `lint` target runs `ruff lint .`, which is not a valid ruff subcommand — use `ruff check`)
- Format: `make format` (runs `isort .` then `ruff format .`)
- Test: `pytest` — single test e.g. `pytest budgie/tests/test_core.py::test_productive_hours_matches_definition`

## Architecture

**The core rule: all budgeting/forecast math lives in `budgie/core/` and imports no UI (`no click`, `no rich`, `no matplotlib`). Front-ends are thin adapters over it.** This is what keeps the CLI/TUI/GUI decision reversible.

**Second rule: nothing heavy is imported at module scope in `budgie/budgie.py`.** Click imports that file just to build the command tree, so engine and rendering imports live inside the command that needs them. `budgie --help` used to take 8+ seconds; it's now ~0.1s. `budgie/tests/test_startup.py` fails if numpy/holidays/matplotlib/textual/yaml/pyfiglet get imported by `import budgie.budgie`, or if anything reaches for pandas.

- `budgie/core/csvio.py` — the stdlib-`csv` reading layer every loader uses. **pandas is no longer a dependency**: inputs are small flat human-edited CSVs that were immediately iterated into frozen dataclasses, and pandas cost ~0.5s of import before anything printed. `read_rows(path, required)` returns a `Table` (a list of `{column: value}` dicts that also carries `.columns`, so a loader picking its shape from the header works on a header-only file). `as_float`/`as_required_float`/`as_int`/`as_str` convert with errors that name the column; `parse_date` takes ISO plus the usual spreadsheet exports.
- `budgie/core/calendar.py` — productive-hours calculation. `productive_hours(year, pto_days)` = 40 hrs/week × 52 (=2080 gross) minus US federal holidays (via the `holidays` package, anchored to the real calendar year so weekend-observed shifts are correct), optionally minus PTO to reach "available hours". ~1992 productive hrs/yr.
  - **PTO is pro-rated by FTE**, and this is the most-asked question about the model: the ceiling is computed full-time and *then* multiplied by FTE, so a 0.25 FTE person surrenders a quarter of their PTO to the project. The rule lives in one place as `PTO_RULE` (with `explain_pto()` for a worked example) so the CLI, TUI and README can't drift from it.
  - `ProductiveHours.available_for(pto_days)` and `resolve_ceiling(ceiling, pto_days)` support a per-person `pto_days` column. `resolve_ceiling` **raises** if given a per-person figure alongside a bare float ceiling — the float has already had PTO subtracted and can't be un-subtracted, so silently double-counting would be the alternative. Loaders therefore want the `ProductiveHours` object, not `.available_hours`.
- `budgie/core/workspace.py` — the project. `find_workspace()` walks up from cwd looking for `budgie.yaml` (cached; call `forget_workspaces()` after writing one or in tests). `INPUTS` is the single registry of every known input: config key → (default filename, description, which commands consume it), and it drives `budgie status`, the TUI Inputs tab, and the generated project README. `Workspace.resolve(key)` returns a path only if the file exists, so declaring a project never makes a command demand a file you haven't written.
- `budgie/core/scaffold.py` — what `budgie init` writes. Templates are strings here rather than package data so they can't drift from the loaders. **The generated CSVs carry no comment lines** — a `#` row is a malformed record to a CSV reader — so all explanation lives in `budgie.yaml` and the generated `README.md`, and the example rows are real loadable data.
- `budgie/core/person.py` — `Person` (hourly cost + hours) and `HoursEstimate`, a three-point (low/mode/high) estimate. Deterministic code uses `.point` (the mode); Monte Carlo draws `.sample()` (triangular). `HoursEstimate.from_utilization(ceiling, ...)` ties utilization fractions to the productive-hours ceiling.
- `budgie/core/forecast.py` — deterministic most-likely-case forecast (`Forecast` with per-person `LineItem`s and totals).
- `budgie/core/montecarlo.py` — `simulate(people, iterations, seed)` → `SimulationResult` (per-iteration total costs, `.percentiles()` for P10/P50/P90). Seedable for reproducibility.
- `budgie/core/loader.py` — CSV → `list[Person]`. Accepts either a **utilization** shape (`name,hourly_cost,util_low,util_mode,util_high`, needs the productive-hours ceiling) or an **absolute-hours** shape (`hours_low/mode/high`).
- `budgie/core/allocation.py` — FTE tracking (separate concern from forecasting). `Allocation` converts an FTE fraction × the year's available hours into allocated hours, subtracts `hours_spent` → `hours_remaining`, and flags `is_over_budget`. `load_allocations()` reads `name,fte,hours_spent[,email]`.
- `budgie/core/costs.py` — non-labor lines (materials/licences/travel). `CostItem` carries `amount` plus optional `low`/`high`, so uncertain costs sample triangularly into the same Monte Carlo as hours. `recurring=True` books the amount **every month from its own month through December** (`months_charged`), so `total` ≠ `amount` for those. `monthly_totals()` places each line in the month incurred. Costs flow in via optional `costs=` params on `forecast()`, `simulate()`, `monthly_forecast()`, and `monthly_simulation()` — all default to empty, so existing callers are unaffected.
  - **Presentation trap:** `Forecast.total_cost` is labor **+** non-labor. A per-person table's total row must use `.labor_cost`, or the rows won't sum to the total shown.
- `budgie/core/budget.py` — budgets as dated revisions rather than a scalar. `Budget.amount_on(date)` forward-fills (and returns the *original* for dates before the first revision — a budget set in May still governed that January). `original` / `latest` / `net_change` expose the drift; `monthly_amounts()` drives the stepped budget line on the fan chart. `coerce_budget()` accepts a number, a list of `{date, amount, note}`, or a CSV path, which is what keeps `budget: 720000` in existing scenario configs working. **Signals compare against `latest`, not `original`.**
- `budgie/core/plan.py` — **date-resolution** allocation planning. `load_plan()` reads `name,effective_date,fte`; each row applies from its date until the next row for that person, and 0 FTE applies before their first row. So "add member", "zero out", and "re-plan" are all just an appended row — never edit history. `allocated_hours()` walks the year **day by day** at the FTE in effect, so a mid-month start is charged from the actual day (Carol joining 2026-07-15 at 0.5 FTE → 466 h, not 996 flat or 502 month-rounded).
- `budgie/core/actuals.py` — observed spend as `(date, cumulative_hours)` tuples. `load_weekly_actuals()` reads `name,week,hours_to_date` — real timesheet exports give a **cumulative reading at an ISO week**, not a per-week series, so values are validated as non-decreasing (a decrease means someone pasted per-period values). `week_ending()` maps ISO week → its Sunday. `monthly_to_observations()` converts the monthly shape into the same form.
- `budgie/core/monthly.py` — the monthly time dimension. Months are weighted by **actual working days** (Mon–Fri minus federal holidays in that month), never an even 1/12, and `month_weights()` sums to 1 so monthly figures always reconcile back to the annual ones from `calendar.py`. Provides `monthly_forecast()`, `monthly_simulation()` (cumulative cost per month, `.band(p)` for fan-chart percentiles), `cumulative()`, and `load_monthly_actuals()` (tidy `name,month,hours` CSV → `{name: [12 monthly hours]}`).
- `budgie/core/burndown.py` — `burndown(allocation, year, as_of)` → `BurndownStatus`: even-pace expectation vs actual spend (`variance`, `is_over_pace`), observed `burn_rate_per_day`, `projected_total`, and `exhaustion_date` (None if the allocation lasts the year). Accepts optional `monthly_spent` cumulative actuals; **without it we only know the endpoint**, so the chart interpolates from the origin — don't present that line as measured month-by-month data.
  - `.required_pace` → `RequiredPace`: remaining hours restated as `hours_per_week` and an `fte` fraction, over the **real working days left** after `as_of` (not `weeks × 5`) — a December reading must not imply capacity that isn't there. `is_exhausted` / `is_impossible` / `out_of_time` cover the degenerate cases so callers don't divide by zero or print a 300% FTE with a straight face. This is what makes "318 hours left" actionable.
- `budgie/core/signals.py` — rules-based stoplight analysis. `evaluate(sim, budget, baseline=None)` → `SignalResult` with a `Signal` of GREEN (good, ≤10% chance over budget) / YELLOW (caution, ≤40%) / RED (bad, >40%) / BLUE (no change — only when a `baseline` sim is given and the mean moved ≤2%). The driving number is `probability_over()`, read straight off the simulated outcomes. Thresholds are keyword args, not magic numbers.
- `budgie/core/scenario.py` — `run_scenarios(config)` runs named what-if scenarios from a YAML config (`budget`, `iterations`, `seed`, `scenarios[]` each with `name/people/year/pto`) → `list[ScenarioResult]`. **The first scenario is the baseline** for both `cost_delta` and the BLUE signal. People paths resolve relative to the config file's directory.

Presentation layers (all thin adapters over `core/`):
- `budgie/budgie.py` — click CLI. `cli` is a `@click.group()`; subcommands are `@click.command()`s registered via `cli.add_command(...)`.
  - **Every input/setting option defaults to `None`**, not to a value. That's what makes "the user said nothing" distinguishable from "the user asked for the default", which is what lets the workspace supply a default without the option always winning. Resolution goes through `_input(key, override, sample)` (explicit > project file > bundled sample), `_workspace_input(key)` (project file or nothing, for genuinely optional inputs where a sample would invent data), and `_setting(key, override, default)`. Adding an option means adding the matching resolve call — a `default=` in the decorator would silently shadow the project.
  - `_SIGNAL_STYLE` is keyed by `Signal.name`, not the enum, so rendering never imports the engine.
- `budgie/tui.py` — Textual TUI (`BudgieTUI`), four tabs over the workspace: Forecast (live recompute), Plan (append a dated change), Inputs (list + open in `$EDITOR` via the `e` binding), Assumptions. `ascii_histogram()` renders the distribution as block characters.
  - **The only thing the TUI writes is a plan row, and it appends.** `append_plan_row()` never edits an existing row, because that's what `core/plan.py` models — history is a record, not mutable state.
  - `add_plan_row()` returns the status message it displayed, so tests can assert the outcome without reaching into widget internals.
  - TUI tests are async (`App.run_test()`); `pyproject.toml` sets `asyncio_mode = "auto"` so they don't each need a marker.
- `budgie/plots.py` — matplotlib figures (Agg backend, file output only — no windows). `montecarlo_histogram`, `forecast_bars`, and `burndown_chart` (even-pace vs actual vs projection, with the exhaustion date marked). Reusable by TUI/GUI.
- `budgie/emails.py` — renders a per-person `EmailDraft` from an `Allocation` and writes draft files. **Renders only; never sends** — sending is left to a reviewed, explicit step.
  - `budgie emails` defaults to `--html` (`.eml` + per-person burn-down charts under `emails/charts/`); `--plain` is the opt-out. It used to default the other way, which is why it looked like the charts were broken.
  - `pace_sentence()` restates remaining hours as a weekly commitment and goes in **both** the HTML body and the `text/plain` part — a recipient whose client blocks HTML must still get the whole message, so `build_message()` passes `status.required_pace` into `render_email()`. Forgetting that is a silent content loss, not an error.
  - **Outlook path:** `render_html_email()` / `build_message()` / `write_eml_drafts()` produce `.eml` files. Outlook renders HTML through Word, so the markup is **table-based with inline styles only** (no flex/grid) and the chart is a **`cid:` attachment, never a base64 `data:` URI** (Outlook desktop won't display those). MIME shape is `multipart/alternative` → text/plain + (`multipart/related` → text/html + image with `Content-ID: <burndown>`).
  - The HTML template builds its rows into a `rows` variable first so the big f-string holds only simple substitutions — otherwise `ruff format` reflows call expressions inside the template into unreadable shapes.
- `budgie/singletons.py` — shared `console`, `logger`, `header` banner, and `set_verbose()`. Import these rather than constructing new instances.
  - **Logging rule:** this is the *only* place rich is wired into logging. Modules under `core/` use plain `logging.getLogger(__name__)` and never import rich — their records propagate to the root handler configured here, so the engine stays UI-free while still logging rich-formatted under a front-end. Never `from budgie.singletons import logger` inside `core/`; that would break the no-UI rule.
  - Root level is **INFO** so third-party DEBUG (matplotlib's font manager emits hundreds of records per figure) doesn't flood output. `set_verbose(True)`, wired to the CLI's `-v/--verbose`, raises **only** the `budgie` package logger to DEBUG.
- `budgie/utils/utils.py` — small rich presentation helpers.

## Testing notes

- CLI tests use click's `CliRunner` against the `cli` group (`budgie/tests/test_main.py`); engine tests hit `budgie/core/` directly (`budgie/tests/test_core.py`).
- `display_startup_message` prints the banner as pyfiglet ASCII art, so the literal string `"Budgie"` does not appear in output — assert on exit code / rendered content instead.
- Sample data: `budgie/tests/team.csv` (forecast input), `budgie/tests/team_lean.csv` (3-person variant), `budgie/tests/allocations.csv` (FTE/email input), `budgie/tests/actuals.csv` (monthly actuals), `budgie/tests/scenarios.yaml` (scenario-compare config). The older `budgie/tests/costs.csv` is a different, legacy shape. **These double as the no-project fallback the CLI ships**, so changing them changes what a first-time user sees.
- `test_startup.py` (import weight), `test_workspace.py` (project discovery/scaffold), `test_pace.py` (required pace + per-person PTO), `test_emails.py` (draft contents and defaults), `test_tui.py` (async, Textual `run_test()`).
- Workspace-touching tests must call `forget_workspaces()` — `find_workspace()` is cached, and `tmp_path` changes between tests. `test_workspace.py` does it in an autouse fixture.
