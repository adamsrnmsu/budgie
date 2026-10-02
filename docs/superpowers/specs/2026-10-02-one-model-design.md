# One model: the plan sets the hours, everyone quotes the same number

Date: 2026-10-02
Status: approved 2026-10-02 ("B now"); implemented, plan docs/superpowers/plans/2026-10-02-one-model.md
Review: `2026-10-02-ux-review.md`, step B. Step C (editing the Plan tab in the
TUI) and step D (teaching) get their own specs once this one is approved;
they build on the interfaces named under "Hooks for later steps".

## Goal

One team model, read the same way by the TUI, the CLI and perch.

- **plan.csv** is the only place FTE lives: who works how much, from when.
- **people.csv** says what an hour costs, and how far real hours might stray
  from the plan.
- Cost = planned hours × rate, plus non-labour costs, minus what is already
  spent. The TUI Forecast tab shows the same budget, spent, forecast, headroom
  and stoplight as `budgie forecast` and perch.

**Done when:**
- Adding a row to plan.csv changes the forecast total in the CLI, the TUI and
  perch.
- On the user's perch project (`perch/budget/test`), Alice's cut to 0.25 FTE
  from 2026-10-02 lowers the forecast. Today it doesn't.

## Decisions

### Hours come from the plan

When a project has plan.csv, a person's most likely hours are
`plan.allocated_hours(name, year, pto)`. That is their FTE walked day by day
over the year's working days, less PTO. This is already how the Plan tab and
`budgie hours` count. Their low and high hours are that figure scaled by the
person's spread (next section).

A project without plan.csv keeps today's behaviour: hours = util_mode × the
full-time year. Nothing breaks for plan-less projects.

### Strict about who is planned, and loud about it

When plan.csv exists:

| Case | Hours | Warning (shown, not just logged) |
|---|---|---|
| In people.csv and in plan.csv | from the plan | — |
| In people.csv, not in plan.csv | **0**: no plan rows means not on the project | "Bob has a rate in people.csv but no rows in plan.csv, so 0 hours" |
| In plan.csv, not in people.csv | not costed, since there's no rate | "Zed is in plan.csv but has no rate in people.csv, so not costed" |

These warnings go to every place a user looks:
- a line under the CLI forecast;
- a banner on the TUI Forecast tab;
- `Snapshot.warnings`, a list of strings perch can show.

They are **never** only `logger.warning`: the review found those never reach a
person.

### The spread: how far hours might stray from the plan

people.csv gains a plain form, used by new projects:

```
name,hourly_cost,under,over
Alice,95,10,5
```

`under` / `over` are percentages: "Alice may work up to 10% fewer hours than
planned, or up to 5% more."
- Hours are triangular: low = plan × (1 − under/100), likely = plan,
  high = plan × (1 + over/100).
- Both columns are optional. A missing value means 0, which is no
  uncertainty, so a bare `name,hourly_cost` file works.

**Old util form, still loaded:** `util_low,util_mode,util_high`. With a plan,
these become a spread around the plan: low = plan × util_low/util_mode,
high = plan × util_high/util_mode.
- If util_mode is 0, the spread is 0 (low = likely = high = the plan) and a
  warning names the person.
- Without a plan they mean what they mean today.

**Old hours form** (`hours_low/mode/high`): without a plan, unchanged. With a
plan, it becomes a spread the same way (low/mode and high/mode). It is kept
only for old files.

The Forecast tab and `budgie guide people` describe the plain form. Old forms
load without complaint.

### One place for per-person PTO

Per-person days off live in **people.csv `pto_days`**, for both forms.
`allocations.csv pto_days` is still read so old projects keep working:
- when only allocations.csv has a value, it applies;
- when both files have a value and they differ, there is a visible warning and
  people.csv wins.

### allocations.csv shrinks

- `fte` and `hours_spent` become optional. The plan supersedes `fte`, and
  readings supersede `hours_spent`.
- `email` and `pto_days` keep their meaning.
- A file with only `name,email` is valid.

### The TUI Forecast tab reads the project, not just people.csv

When a project is open, the tab is built from `load_snapshot`, the same read
the CLI and perch use. It then applies `at_completion` (readings) and
`simulate` with costs, and leads with one line:

```
Budget $425,000 · spent $96,450 · forecast P50 $331,220 · headroom $93,780 · ● GOOD (3% chance over)
```

Under it come the per-person table, the cost lines, the P10/P50/P90 pane and
any warnings.

**The Year / PTO / Iterations / Seed boxes are removed.** They change numbers
for one session without saving, which the review found confusing. Those
settings live in budgie.yaml.
- **Proposed:** budgie.yaml is opened with `e` from the Projects tab.
- **Alternative:** keep the boxes, relabelled "What-if (not saved)".

The CLI `forecast` uses the same Snapshot, so its numbers match the TUI's to
the dollar for the same project, seed and iterations.

### Core API changes (perch depends on these)

| Change | Why |
|---|---|
| `load_snapshot` returns plan-driven `people` when the project has a plan | the one model |
| `Snapshot.warnings: list[str]` (new field, default empty) | the visible warnings above |
| `Snapshot.what_if(plan_entries=…)` recomputes `people`, not just `allocations`/`planned` | otherwise `perch cut` shows hours moving but not money |
| `Snapshot.with_plan(plan: AllocationPlan) -> Snapshot` (new) | swaps in a whole plan, which is how edits and deletes get previewed in step C |
| `people_on_plan(people, plan, year, ceiling) -> (list[Person], list[str])` in core (new, pure) | the one function every caller uses: Snapshot, CLI forecast/monthly, scenarios |
| `load_people` returns the spread and per-person PTO it read (new optional fields on `Person`, with defaults, so perch's `Person(name, hourly_cost, hours)` still works) | `people_on_plan` needs them |
| `load_allocations`: `fte`, `hours_spent` optional | allocations shrinks |

`HoursEstimate`, `Person.hours`, `simulate`, `at_completion` and `evaluate`
keep their signatures. perch's contract test
(`perch/tests/test_contract.py`) must still pass, with names added only.

### Where the plan applies, command by command

- `forecast`, `monthly`, the TUI Forecast tab and perch (through the Snapshot)
  use plan-driven people.
- `scenarios.yaml` scenarios name their own people file and have no plan. They
  keep today's behaviour unless the scenario names a plan. Adding `plan:` to a
  scenario is out of scope here.
- `hours`, `plan`, `emails` and `burndown` already read the plan, so they are
  unchanged.

## Hooks for later steps

- **Step C (editing the Plan tab):** edits and deletes build a new
  `AllocationPlan` and preview it with `Snapshot.with_plan`; adding a row uses
  `Snapshot.what_if(plan_entries=…)`. A `save_plan(path, entries)` writer
  (atomic, keeps the header and row order) belongs to step C, not here.
- **Step D (teaching):**
  - the scaffold writes the plain people.csv form, with no `fte` or
    `hours_spent` in allocations.csv;
  - `budgie guide people` / `allocations` and the Assumptions tab teach the
    model;
  - one-line CLI errors.

## Migration and rollout

- **Existing projects load unchanged.** Only the numbers move, and only where
  plan.csv disagrees with util_mode (that disagreement was the bug).
- **perch:** its venv imports budgie (editable) from budgie's **main**
  checkout, so the merge goes live in perch at once.
  - Run perch's whole suite against the budgie branch before merging.
  - Fix perch's tests and fixtures in a perch branch.
  - Merge both together.
  - `perch/core/quarterly.py:_staffing` costs plan entries by leaving each one
    out. With this change that now moves the cost, as intended, so check its
    tests' expectations.
- **The user's project `perch/budget/test`:** show `budgie forecast` before and
  after, as the acceptance check.

## Testing

- `people_on_plan`, for each case in the table:
  - planned;
  - rate but no plan rows: 0 h plus a warning;
  - planned but no rate: not costed, plus a warning;
  - the plain spread, util spread and hours spread;
  - util_mode 0;
  - per-person PTO, with the people.csv vs allocations.csv conflict.
- The original bug is gone: append a plan row in a project, and
  `load_snapshot(...).people` hours, the CLI forecast total and the TUI Forecast
  total all change.
- `what_if(plan_entries=…)` and `with_plan` change `people` hours and the P50.
- The TUI Forecast summary line equals `budgie forecast` on the same project
  (same seed).
- A plan-less project gives identical numbers before and after (regression).
- perch's suite passes against the branch.

## Out of scope

- Editing the Plan tab in the TUI (step C).
- Labels, help, scaffold and CLI error wording (step D).
- Rate history; plans in scenarios.yaml.
