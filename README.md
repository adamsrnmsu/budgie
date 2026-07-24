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
make venv                      # creates .venv and installs budgie + deps
source .venv/bin/activate      # (make activate prints this for you)
```

Or by hand:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

> **Note:** make sure the interpreter running `budgie` is the same one `pip` installed into.
> A bare `python3` on your `PATH` may be a different version than your virtualenv.

## Commands

Every command runs against bundled sample data by default, so you can try them all
immediately. Swap in your own files with the options shown.

### `budgie forecast` — what will this team cost?

```bash
budgie forecast --people team.csv --year 2026 --pto 15 --seed 42 --plots
```

Prints the per-person deterministic forecast plus Monte Carlo **P10 / P50 / P90**.
`--plots` writes `montecarlo.png` (cost distribution) and `forecast.png` (cost per person).

### `budgie monthly` — the trend, not just the total

```bash
budgie monthly --budget 720000 --seed 42 --plots
```

Breaks the year into months **weighted by real working days** (February and holiday-heavy
months carry less), showing cumulative cost with P10/P90 at each month end. `--plots` writes
`fan.png` (cumulative cost with a widening uncertainty band) and `monthly.png` (cost per month).

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

### `budgie hours` — how much time does everyone have left?

```bash
budgie hours --allocations allocations.csv --year 2026
```

Converts each person's FTE into an hours budget, subtracts what they've spent, and flags
anyone over. `0.25 FTE × 1,992 available hours = 498 allocated`.

### `budgie emails` — tell each person where they stand

```bash
# plain-text drafts
budgie emails --out-dir emails

# Outlook-ready .eml with an embedded burn-down chart
budgie emails --html --actuals actuals.csv --as-of 2026-07-23 --out-dir emails
```

Writes one draft per person. **Budgie never sends anything** — you review the drafts and send
them yourself.

The `--html` drafts are `.eml` files you can open straight into Outlook. They're built for
Outlook specifically (table layout, inline styles, chart attached by `Content-ID` rather than a
base64 image, which Outlook won't render). Each contains a burn-down chart showing even pace vs
actual spend, a projection, and the date that person runs out of hours.

### `budgie tui` — explore forecasts interactively

```bash
budgie tui
```

Edit the year, PTO, iterations, and seed, and watch the forecast table and Monte Carlo
histogram recompute live. Press `r` to recalculate, `q` to quit.

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

**Allocations** — `allocations.csv` (for `hours` and `emails`):

```csv
name,email,fte,hours_spent
Alice,alice@example.com,0.25,180
```

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

**Scenarios** — `scenarios.yaml`:

```yaml
budget: 720000
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

**Productive hours.** 40 hrs/week × 52 weeks = 2,080 gross, minus the 11 US federal holidays
(8 hrs each) = **1,992 productive hours/year**. Holidays are counted against the real calendar,
so weekend-observed shifts land correctly. Subtract PTO with `--pto` to get "available hours".

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

## Development

```bash
make test      # pytest
make lint      # ruff check
make format    # isort + ruff format
make help      # list all targets
```

Run a single test:

```bash
pytest budgie/tests/test_core.py::test_productive_hours_matches_definition
```

**Architecture.** All budgeting math lives in `budgie/core/` and imports no UI — no click, no
rich, no matplotlib. The CLI, TUI, and plot/email renderers are thin adapters over it. That's
what keeps the interface decision reversible and the engine testable.

## License

MIT — see [LICENSE](LICENSE).
