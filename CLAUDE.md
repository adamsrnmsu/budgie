# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Budgie is a CLI budget/forecasting companion — a terminal alternative to spreadsheet budgeting. It forecasts team cost from each person's **hourly cost × productive hours**, and puts confidence bounds around that forecast with a Monte Carlo simulation over uncertain expected hours. Direction is **CLI-first**, with a Textual TUI planned later; the engine is deliberately UI-independent so that choice stays reversible.

## Install & Run

Editable install, then invoke via the `budgie` console script (`pyproject.toml` → `budgie.budgie:cli`):

```bash
pip install -e .                 # or: make venv  (creates .venv and installs)
budgie forecast --people tests/team.csv --year 2026 --pto 15 --seed 42 --plots
budgie tui                       # interactive forecast explorer
budgie hours                     # FTE allocated / spent / remaining per person
budgie emails --out-dir emails   # write a per-person hours email draft (never sends)
budgie emails --html             # Outlook-ready .eml drafts w/ embedded burn-down chart
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

- `budgie/core/calendar.py` — productive-hours calculation. `productive_hours(year, pto_days)` = 40 hrs/week × 52 (=2080 gross) minus US federal holidays (via the `holidays` package, anchored to the real calendar year so weekend-observed shifts are correct), optionally minus PTO to reach "available hours". ~1992 productive hrs/yr.
- `budgie/core/person.py` — `Person` (hourly cost + hours) and `HoursEstimate`, a three-point (low/mode/high) estimate. Deterministic code uses `.point` (the mode); Monte Carlo draws `.sample()` (triangular). `HoursEstimate.from_utilization(ceiling, ...)` ties utilization fractions to the productive-hours ceiling.
- `budgie/core/forecast.py` — deterministic most-likely-case forecast (`Forecast` with per-person `LineItem`s and totals).
- `budgie/core/montecarlo.py` — `simulate(people, iterations, seed)` → `SimulationResult` (per-iteration total costs, `.percentiles()` for P10/P50/P90). Seedable for reproducibility.
- `budgie/core/loader.py` — CSV → `list[Person]`. Accepts either a **utilization** shape (`name,hourly_cost,util_low,util_mode,util_high`, needs the productive-hours ceiling) or an **absolute-hours** shape (`hours_low/mode/high`).
- `budgie/core/allocation.py` — FTE tracking (separate concern from forecasting). `Allocation` converts an FTE fraction × the year's available hours into allocated hours, subtracts `hours_spent` → `hours_remaining`, and flags `is_over_budget`. `load_allocations()` reads `name,fte,hours_spent[,email]`.
- `budgie/core/monthly.py` — the monthly time dimension. Months are weighted by **actual working days** (Mon–Fri minus federal holidays in that month), never an even 1/12, and `month_weights()` sums to 1 so monthly figures always reconcile back to the annual ones from `calendar.py`. Provides `monthly_forecast()`, `monthly_simulation()` (cumulative cost per month, `.band(p)` for fan-chart percentiles), `cumulative()`, and `load_monthly_actuals()` (tidy `name,month,hours` CSV → `{name: [12 monthly hours]}`).
- `budgie/core/burndown.py` — `burndown(allocation, year, as_of)` → `BurndownStatus`: even-pace expectation vs actual spend (`variance`, `is_over_pace`), observed `burn_rate_per_day`, `projected_total`, and `exhaustion_date` (None if the allocation lasts the year). Accepts optional `monthly_spent` cumulative actuals; **without it we only know the endpoint**, so the chart interpolates from the origin — don't present that line as measured month-by-month data.
- `budgie/core/signals.py` — rules-based stoplight analysis. `evaluate(sim, budget, baseline=None)` → `SignalResult` with a `Signal` of GREEN (good, ≤10% chance over budget) / YELLOW (caution, ≤40%) / RED (bad, >40%) / BLUE (no change — only when a `baseline` sim is given and the mean moved ≤2%). The driving number is `probability_over()`, read straight off the simulated outcomes. Thresholds are keyword args, not magic numbers.
- `budgie/core/scenario.py` — `run_scenarios(config)` runs named what-if scenarios from a YAML config (`budget`, `iterations`, `seed`, `scenarios[]` each with `name/people/year/pto`) → `list[ScenarioResult]`. **The first scenario is the baseline** for both `cost_delta` and the BLUE signal. People paths resolve relative to the config file's directory.

Presentation layers (all thin adapters over `core/`):
- `budgie/budgie.py` — click CLI. `cli` is a `@click.group()`; subcommands (`forecast`, `tui`, `hours`, `emails`) are `@click.command()`s registered via `cli.add_command(...)`. `THIS_DIR` anchors default file paths to the package dir.
- `budgie/tui.py` — Textual TUI (`BudgieTUI`). Edits year/PTO/iterations/seed and recomputes the forecast table + Monte Carlo live; `ascii_histogram()` renders the distribution as block characters.
- `budgie/plots.py` — matplotlib figures (Agg backend, file output only — no windows). `montecarlo_histogram`, `forecast_bars`, and `burndown_chart` (even-pace vs actual vs projection, with the exhaustion date marked). Reusable by TUI/GUI.
- `budgie/emails.py` — renders a per-person `EmailDraft` from an `Allocation` and writes draft files. **Renders only; never sends** — sending is left to a reviewed, explicit step.
  - **Outlook path:** `render_html_email()` / `build_message()` / `write_eml_drafts()` produce `.eml` files. Outlook renders HTML through Word, so the markup is **table-based with inline styles only** (no flex/grid) and the chart is a **`cid:` attachment, never a base64 `data:` URI** (Outlook desktop won't display those). MIME shape is `multipart/alternative` → text/plain + (`multipart/related` → text/html + image with `Content-ID: <burndown>`).
  - The HTML template builds its rows into a `rows` variable first so the big f-string holds only simple substitutions — otherwise `ruff format` reflows call expressions inside the template into unreadable shapes.
- `budgie/singletons.py` — shared `console`, `logger` (rich-backed, level **INFO** so third-party DEBUG logs like matplotlib's font manager don't flood output), and `header` banner. Import these rather than constructing new instances.
- `budgie/utils/utils.py` — small rich presentation helpers.

## Testing notes

- CLI tests use click's `CliRunner` against the `cli` group (`budgie/tests/test_main.py`); engine tests hit `budgie/core/` directly (`budgie/tests/test_core.py`).
- `display_startup_message` prints the banner as pyfiglet ASCII art, so the literal string `"Budgie"` does not appear in output — assert on exit code / rendered content instead.
- Sample data: `budgie/tests/team.csv` (forecast input), `budgie/tests/team_lean.csv` (3-person variant), `budgie/tests/allocations.csv` (FTE/email input), `budgie/tests/actuals.csv` (monthly actuals), `budgie/tests/scenarios.yaml` (scenario-compare config). The older `budgie/tests/costs.csv` is a different, legacy shape.
