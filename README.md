# Budgie

The ultimate project budget companion — a terminal alternative to spreadsheet budgeting.

Budgie forecasts what a team will cost from each person's **hourly cost × productive hours**,
then puts honest confidence bounds around that number with a Monte Carlo simulation. It also
tracks FTE allocations, tells each person how many hours they have left, and writes the emails
that say so.

```
$ budgie forecast --seed 42

       Deterministic forecast
┏━━━━━━━━━┳━━━━━━┳━━━━━━━┳━━━━━━━━━━┓
┃ Name    ┃ $/hr ┃ Hours ┃     Cost ┃
┡━━━━━━━━━╇━━━━━━╇━━━━━━━╇━━━━━━━━━━┩
│ Alice   │  $95 │ 1,793 │ $170,316 │
│ Bob     │ $110 │ 1,693 │ $186,252 │
│ Charlie │  $85 │ 1,753 │ $149,002 │
│ David   │ $130 │ 1,594 │ $207,168 │
├─────────┼──────┼───────┼──────────┤
│ Total   │      │ 6,833 │ $712,738 │
└─────────┴──────┴───────┴──────────┘
Monte Carlo (10,000 sims):  P10 $668,084  |  P50 $698,943  |  P90 $728,057
```

## Inspiration

Folks manage budgets in Excel spreadsheets. That's manual, error-prone, there's no workflow,
and it gives you a single fake-precise number. Budgie provides trend data, a simple planning
interface, cost scenario management — and is just cooler than a spreadsheet.

## Install

Requires Python 3.10+.

```bash
git clone https://github.com/adamsrnmsu/budgie.git
cd budgie
make venv                      # creates the venv and installs budgie + deps + dev tools
make activate                  # prints the source command for your shell
```

`make venv` builds the virtualenv **outside the repo**, at `~/Documents/tools/budgie`,
so nothing in the working tree is a build artifact. Put it somewhere else with
`make venv VENV=/path/to/env` (every other target takes the same `VENV=`).

Or by hand:

```bash
python3 -m venv /path/to/env && source /path/to/env/bin/activate
pip install -e .                # to use it
pip install -e '.[dev]'          # to work on it: adds pytest, ruff, isort
pip install -e '.[dev,docs]'     # ...and Sphinx, to build the docs site
```

> **Note:** make sure the interpreter running `budgie` is the same one `pip` installed into.
> A bare `python3` on your `PATH` may be a different version than your virtualenv.
>
> **macOS:** if `budgie` dies with `ModuleNotFoundError: No module named 'budgie'`
> right after a successful `pip install -e .`, check the editable `.pth` for the
> hidden flag: `ls -lO "$(python -c 'import site;print(site.getsitepackages()[0])')"`.
> `site.py` silently skips any `.pth` marked `hidden`, so the finder never installs.
> Clear it with `chflags nohidden <file>`.

## Start a project

```bash
budgie init my-budget
cd budget/my-budget
```

That creates a `budget/my-budget/` folder holding a `budgie.yaml` and a starter CSV for
every input, already filled with loadable example rows — `budgie forecast` works the
moment `init` finishes. Edit the CSVs with your own numbers and re-run.

Leave the name off and `budgie init` asks for one (it won't prompt when there's no
terminal, so scripts and CI still work). Use `--here` if you really do want the files
loose in the current directory.

**Projects live together under `budget/`.** A budget is rarely singular — there's next
year's, and the one for the other team — so each `init` adds another folder beside the
last:

```
my-work/
  budget/
    fy26/
      budgie.yaml
      people.csv
    fy27/
      budgie.yaml
      people.csv
```

With one project there, every command just finds it. With several there's no right answer
to guess at, so Budgie lists them instead of picking:

```console
$ budgie status
Several projects to choose from:
  fy26
  fy27

Pick one with --project NAME, or cd into it.
```

`--project fy27` works on any command, from anywhere — including from inside `fy26`, so
you can compare next year's numbers without changing directory.

To remove one:

```bash
budgie delete fy26        # asks you to type "fy26" back before it goes
budgie delete fy26 --yes  # for scripts
```

There is no undo, so `delete` refuses everything it isn't sure about: a name that matches
no project, an ambiguous "which one did you mean", a directory with no `budgie.yaml` in it,
or the directory you're currently standing in. A plain `y/N` confirmation is too easy to
hit by reflex for something irreversible, so it asks for the project's name instead.

Not sure what to do next? **`budgie`** on its own shows the commands grouped by when
you'd reach for them, and **`budgie guide`** walks through building a budget in five
steps. `budgie guide people` (or `allocations`, `plan`, `costs`, `budget`, `actuals`,
`weekly`, `scenarios`) explains one input file: its columns, an example, and the rules
the engine applies to it.

Every command finds the project by walking up from wherever you run it — and if there's
exactly one project directly below you, it uses that, so `budgie status` works from the
folder you ran `init` in. `budgie.yaml` also pins the settings you'd otherwise retype:

```yaml
year: 2026
pto: 0
iterations: 10000
seed: 42
budget: 720000

inputs:
  people: people.csv
  allocations: allocations.csv
```

An explicit option always wins over the project (`budgie forecast --people other.csv`),
and with no project at all every command falls back to bundled sample data — so you can
try everything before committing to anything.

### `budgie guide` — how do I actually build one of these?

```bash
budgie guide              # the five phases, in order
budgie guide allocations  # the columns and rules for one input file
```

Phase 1 creates the project, 2 describes the team, 3 checks the assumptions, 4 reads
the forecast, 5 keeps it current. Each phase names the files to edit and the command
that shows you the result.

### `budgie status` — what's in this project?

```bash
budgie status
```

Lists every input file, whether it exists, how many rows it has, what it's for, and which
commands consume it. Run this first when you're not sure where a number came from.

### `budgie assumptions` — what is Budgie assuming?

```bash
budgie assumptions --year 2026 --pto 15
```

Prints every modelling assumption with its current value and the module that sets it: the
working week, the holiday count for that year, how PTO interacts with part-time
allocations, the month weighting, the sampling distributions, and the signal thresholds.
Nothing about the model is meant to be folklore.

## Commands

Every command uses your project's files when there is one, and bundled sample data when
there isn't — so you can try them all immediately. Every command that reads your project's
files also takes `--project NAME` to choose between several budgets. (`budgie init` and
`budgie delete` manage the projects themselves — see [Start a project](#start-a-project).)

### `budgie forecast` — what will this team cost?

```bash
budgie forecast --people team.csv --year 2026 --pto 15 --seed 42 --plots
```

Prints the per-person deterministic forecast plus Monte Carlo **P10 / P50 / P90**.
`--plots` writes `montecarlo.png` (cost distribution) and `forecast.png` (cost per person).

Add non-labor costs and a budget to get the full picture and a stoplight:

```bash
budgie forecast --costs costs.csv --budget budget.csv --seed 42
```

```
Total (labor)                    $712,738
Non-labor                         $81,500
Labor + non-labor                $794,238
Budget: original $720,000 → current $765,000 (+45,000 over 3 revisions)
● BAD — 77% chance of exceeding budget
```

Once the project has spend readings (`actuals.csv` or `weekly.csv`), `forecast` stops
re-forecasting the months that have already happened and prints an **estimate at
completion** instead: the hours each person has actually booked, plus a forecast of only
the time left.

```bash
budgie forecast --weekly weekly.csv --seed 42     # or --actuals actuals.csv
budgie forecast --as-of 2026-06-30                # ignore readings dated after this
budgie forecast --ignore-actuals                  # the full-year plan, as before
```

The rule: **hours at completion = spent + plan × the share of working days left** after
that person's latest reading. It is applied to the low, most-likely and high estimates
alike, so the Monte Carlo range narrows as the year goes on and collapses to a single
number on Dec 31. The table gains a **Spent** column; anyone without a reading stays on
their full-year plan and shows `—`. If both files exist, weekly wins; a file named on the
command line beats the project's. `--as-of` only chooses which readings count — the
elapsed share is always measured at the reading's own date, because hours after it are
unknown. Spent hours are costed at the person's current rate, and non-labor costs are not
adjusted (there are no actuals for them).

### `budgie monthly` — the trend, not just the total

```bash
budgie monthly --budget 720000 --seed 42 --plots
```

Breaks the year into months **weighted by real working days** (February and holiday-heavy
months carry less), showing cumulative cost with P10/P90 at each month end. `--plots` writes
`fan.png` (cumulative cost with a widening uncertainty band) and `monthly.png` (cost per month).

With spend readings (the project's `actuals.csv` / `weekly.csv`, or `--actuals` / `--weekly`;
`--as-of` and `--ignore-actuals` work as for `forecast`) the months already past carry the hours
actually booked — between readings the line is interpolated — and only the time after each
person's latest reading is simulated, so the band is a single line until then and fans out from
there. The remaining hours are spread by the plan's shape when the project has a `plan.csv`,
else by working days. Non-labor costs are unchanged. Without readings the output is as before.

### `budgie scenario` — compare what-ifs with a stoplight

```bash
budgie scenario --config scenarios.yaml
```

```
● Baseline           $712,738        —   18% over budget → CAUTION
● With 15 PTO days   $669,802  −$42,936    0%            → GOOD
● Lean team (3)      $505,570 −$207,168    0%            → GOOD
```

The first scenario is the baseline; the rest are measured against it.

### `budgie plan` — allocations that change during the year

```bash
budgie plan --plan plan.csv --year 2026
```

People join, leave, and get re-planned. A plan records **when** each change takes effect;
each row applies from its date until the next row for that person.

```csv
name,effective_date,fte
Alice,2026-01-01,0.25
Bob,2026-01-01,0.50
Bob,2026-09-01,0.00      # zeroed out — left the project
Carol,2026-07-15,0.50    # joined mid-July
Dave,2026-01-01,0.25
Dave,2026-04-01,0.75     # re-planned upward
```

Adding a member, zeroing someone out, and re-planning are all the same operation: append a
row. You never edit history, so the record of what changed and when is preserved.

Hours are counted **day by day over real working days**, so a mid-month start is charged from
the actual day. Carol's July 15 start at 0.50 FTE yields 466 hours — not the 996 a flat annual
model would give, and not the 502 you'd get by rounding her start to July 1.

Inside a project, anyone with their own `pto_days` in `allocations.csv` is counted with that
figure rather than the team's `--pto`, so this table and `budgie hours` always agree.

### `budgie hours` — how much time does everyone have left?

```bash
budgie hours --allocations allocations.csv --year 2026
```

Converts each person's FTE into an hours budget, subtracts what they've spent, and flags
anyone over. `0.25 FTE × 1,992 available hours = 498 allocated`.

When the project has spend readings (`weekly.csv`, else `actuals.csv`), each person's
latest reading is their spent figure, the same number `emails` and `forecast` use;
`hours_spent` in `allocations.csv` only stands for anyone without a reading.

**`--plan`** — when the project has a `plan.csv` (or you pass `--plan FILE`), `hours` and
`emails` take each person's allocated hours from the plan rather than from the flat `fte`
column in `allocations.csv`. The plan is walked day by day, so someone who drops to 0 FTE on
September 1 is allocated only the working days before it. `allocations.csv` still supplies
`hours_spent`, `email` and `pto_days`. The FTE column then shows the **year average**
(planned hours ÷ the full-time ceiling), which is why a person planned at 0.50 until
September reads 0.33. Anyone the plan doesn't mention keeps their flat `fte`, with a
warning. Anyone in the plan but missing from `allocations.csv` is listed with 0 hours
spent. There is no sample fallback for this option: with no project and no `--plan`, the
flat `fte` is used exactly as before.

### `budgie emails` — tell each person where they stand

```bash
# Outlook-ready .eml drafts with an embedded burn-down chart (the default)
budgie emails --out-dir emails --actuals actuals.csv --as-of 2026-07-23

# plain-text drafts instead
budgie emails --plain --out-dir emails
```

Writes one draft per person, plus a burn-down chart per person under `emails/charts/`.
**Budgie never sends anything** — you review the drafts and send them yourself.

The `.eml` files open straight into Outlook. They're built for Outlook specifically (table
layout, inline styles, chart attached by `Content-ID` rather than a base64 image, which
Outlook won't render). Each contains a burn-down chart showing even pace vs actual spend, a
projection, and the date that person runs out of hours.

Every draft — plain or HTML — restates the remaining hours as a **weekly commitment**,
because "318 hours left" isn't something anyone can act on:

```
Hours remaining:  318  (36% used)

Spending the remaining 318 hours evenly over the 109 working days left (22 weeks)
means about 15 hours a week -- 36% of your time.
```

The working days left are real ones (Mon–Fri minus federal holidays), so a December
reading doesn't imply capacity that isn't there. If the remaining hours would need more
than a full-time week, the draft says so outright.

With `--actuals` or `--weekly`, the latest reading **is** the hours-spent figure everywhere
in the draft; `hours_spent` in `allocations.csv` is only the fallback when there are no
readings. A file you name beats the project's copies, whichever kind it is.

### `budgie tui` — explore and re-plan interactively

```bash
budgie tui
```

Five tabs over your project, left to right in the order you'd build a budget — data first,
conclusion last:

1. **Projects** — every budget under `budget/`, how many of its inputs exist, and which one
   is currently loaded. Select one and press `enter` to point every other tab at it, without
   quitting and changing directory. `d` deletes the selected project — twice, deliberately:
   the first press names what would go, the second does it, and any other key cancels.
2. **Inputs** — every project file, whether it exists, and what feeds what. Select one and
   press `e` to open it in `$EDITOR`, then `r` to recalculate.
3. **Plan** — the allocation plan, with a form to append a dated change. Re-planning is an
   appended row, never an edit, so the history stays intact.
4. **Forecast** — edit year, PTO, iterations and seed; the table and Monte Carlo histogram
   recompute live.
5. **Assumptions** — the same model assumptions `budgie assumptions` prints.

Press `1`–`5` to jump to a tab, `r` to recalculate, `e` to edit the selected input, `d` to
delete the selected project, `q` to quit.

It opens on **Forecast** when it can compute one, and otherwise on the tab that can fix what's
wrong: **Projects** when there are several budgets and nothing to auto-select, **Inputs** when
a file won't load. Landing on a tab that can only report an error helps nobody.

## Input files

All inputs are plain CSV (or YAML for scenarios), so they're easy to export from a spreadsheet.

**Team** — `team.csv`. Either utilization fractions of the productive-hours ceiling:

```csv
name,hourly_cost,util_low,util_mode,util_high
Alice,95,0.80,0.90,0.98
```

…or absolute hours, if you'd rather state them directly:

```csv
name,hourly_cost,hours_low,hours_mode,hours_high
Alice,95,1600,1800,1950
```

The three values are a **low / most-likely / high** estimate. The deterministic forecast uses
the middle one; Monte Carlo samples the whole range.

A `pto_days` column is optional on both shapes and overrides the project's PTO for that
person.

**Allocations** — `allocations.csv` (for `hours` and `emails`):

```csv
name,email,fte,hours_spent,pto_days
Alice,alice@example.com,0.25,180,
Bob,bob@example.com,0.50,540,20
```

`pto_days` is optional — leave it blank and the project's `pto` applies. Bob takes 20 days
regardless of what the rest of the team is assumed to take.

**Allocation plan** — `plan.csv` (for `plan`; see above for semantics):

```csv
name,effective_date,fte
Carol,2026-07-15,0.50
```

**Actuals** — optional, for true burn-down curves. Two shapes, whichever your data gives you.

Per-period monthly hours (`actuals.csv`, used with `--actuals`):

```csv
name,month,hours
Alice,1,26
Alice,2,24
```

Or **cumulative hours through an ISO week** (`weekly.csv`, used with `--weekly`) — which is what
most timesheet exports actually give you:

```csv
name,week,hours_to_date
Alice,12,88
Alice,20,142
Alice,29,180
```

These are *cumulative totals*, not per-week hours, so nothing is invented about how the time
was distributed between readings. One row per person is enough; more rows give a real curve.
Budgie takes the as-of date from the latest reading (week 29 of 2026 ends July 19), so the burn
rate is measured over the right window rather than against today's date.

**Non-labor costs** — `costs.csv` (materials, licences, hardware, travel):

```csv
name,category,date,amount,low,high,recurring
Laptops,materials,2026-03-15,12000,11000,14000,no
Cloud hosting,services,2026-01-01,2000,,,yes
Travel,travel,2026-06-01,8000,6000,11000,no
```

`amount` is the most-likely figure; `low`/`high` are optional and make the line participate in
the Monte Carlo just like uncertain hours do. `recurring: yes` books the amount **every month
from its own month through December**, so one row covers a subscription (the cloud line above
totals $24,000). Costs land in the month they're incurred, so they show up as a step in the
monthly and fan charts rather than being smeared across the year.

**Budget revisions** — `budget.csv`. Budgets get increased, cut, and re-baselined:

```csv
effective_date,amount,note
2026-01-01,720000,Original approved budget
2026-05-01,780000,Q2 increase for extra scope
2026-10-01,765000,Q4 trim
```

Each revision holds until the next, same as an allocation plan — you append rather than
overwrite, so the original baseline and the trail of changes stay recoverable. Stoplight
signals compare against the **current** budget, while the summary line shows the drift from the
original. A plain number still works anywhere a budget is accepted.

**Scenarios** — `scenarios.yaml`:

```yaml
budget: 720000        # or a list of revisions, or budget.csv
costs: costs.csv      # optional non-labor lines applied to every scenario
iterations: 10000
seed: 42
scenarios:
  - name: Baseline
    people: team.csv
    year: 2026
    pto: 0
  - name: With 15 PTO days
    people: team.csv
    year: 2026
    pto: 15
```

## How the numbers work

Run `budgie assumptions` to see all of this with the current year's numbers filled in.

**Productive hours.** 40 hrs/week × 52 weeks = 2,080 gross, minus the 11 US federal holidays
(8 hrs each) = **1,992 productive hours/year**. Holidays are counted against the real calendar,
so weekend-observed shifts land correctly. Subtract PTO with `--pto` to get "available hours".

**PTO is pro-rated by FTE.** This is the question everyone asks, so it's worth stating
plainly. A person's ceiling is computed **full-time** — 2,080 gross, minus holidays, minus
their PTO — and *then* multiplied by their FTE:

```
allocated = fte × (2080 − holidays − pto)
```

So someone 25% on your project gives up 25% of their PTO to it, not all of it; the other
75% comes out of whatever else they work on. With 15 PTO days, a 0.25 FTE person gets
`0.25 × 1,872 = 468` hours. Charging their whole PTO to this project would have given 378 —
a 90-hour difference on one person, which is why the choice is worth knowing about.

Set `pto` in `budgie.yaml` (or `--pto`) for the team default, and a `pto_days` column for
anyone who differs.

**Required pace.** `budgie emails` restates remaining hours as hours-per-week and an FTE
fraction, spread over the **real working days left** in the year rather than a flat count of
weeks. That's the number someone can actually plan their week around.

**P10 / P50 / P90.** These are percentiles of the *simulation output*, not the input model.
Budgie runs 10,000 simulated budgets, sorts the totals, and reports:

- **P50** — the median. Half of outcomes land below this; your expected budget.
- **P90** — a conservative number you'd only exceed 10% of the time. Good for what to reserve.
- **P10** — the optimistic case.

Each person's uncertain hours are drawn from a **triangular** distribution (PERT's simpler
cousin) across their low/most-likely/high estimate. That's the input model; the percentiles
above are read off the output — two different layers.

**Stoplight signals.** Rules-based and deliberately transparent. The driving number is the
probability of exceeding your budget, measured straight off the simulated outcomes:

| Signal | Meaning | Rule |
| --- | --- | --- |
| 🟢 green | good | ≤10% chance over budget |
| 🟡 yellow | caution | ≤40% |
| 🔴 red | bad | >40% |
| 🔵 blue | no change | within 2% of a baseline run |

## Troubleshooting

Every command accepts `-v` / `--verbose` for DEBUG logging of what Budgie is doing — which
files it loaded, each person's plan changes, simulation parameters, and how a stoplight signal
was decided:

```bash
budgie -v plan
```

Verbose affects Budgie's own loggers only; third-party libraries stay quiet.

**"Which files is it actually reading?"** `budgie status` shows the project it found and
every input path. If it reports no project, you're on the bundled sample data — run
`budgie init` where you want your numbers to live.

**"It says there are several projects and won't pick one."** That's deliberate: with two
budgets under `budget/` there's no right answer to guess at, and quietly forecasting the
wrong one is worse than asking. Add `--project NAME` (it works from anywhere, including
from inside a different project) or `cd` into the one you mean.

**"Where did that number come from?"** `budgie assumptions` prints every modelling choice
with its current value and the module that sets it.

## Development

```bash
make test      # pytest
make lint      # ruff check
make format    # isort + ruff format
make docs      # Sphinx site in docs/_build/html
make help      # list all targets
```

Every target runs against the virtualenv at `~/Documents/tools/budgie` (see
[Install](#install)), not one inside the repo — pass `VENV=/path/to/env` to point them
elsewhere. The working tree holds no build artifacts.

Run a single test:

```bash
pytest budgie/tests/test_core.py::test_productive_hours_matches_definition
```

**Architecture.** All budgeting math lives in `budgie/core/` and imports no UI — no click, no
rich, no matplotlib. The CLI, TUI, and plot/email renderers are thin adapters over it. That's
what keeps the interface decision reversible and the engine testable.

**Startup cost is a feature.** `budgie --help` imports nothing but click, so it returns in
well under a second. Every engine and rendering import lives inside the command that needs
it, and the CSV loaders use the stdlib `csv` module rather than pandas. `test_startup.py`
fails if a heavy import creeps back up to module scope.

## License

MIT — see [LICENSE](LICENSE).
