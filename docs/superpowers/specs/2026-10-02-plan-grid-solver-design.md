# Plan grid and cost solver

Date: 2026-10-02 · Epic: budgie-w3l · Status: solver on main; step B (budgie-3oj) landed,
so the grid is unblocked.

## Why

Keying month-by-month FTE for a large team is one form submit per change. And
most planning is scenario work: the user adjusts a few people's FTE until the
plan cost hits a number. Budgie gives no help hitting it.

## What the user approved

- **Approach A:** a people × months grid in the Plan tab. Edits are
  scratch: they preview the cost and write nothing. `c` commits the changed
  cells as dated plan rows, appended. `x` discards.
- **Solver, both modes:** fill one person's selected months exactly, or
  spread the gap across several people. The spread is proportional by
  default, with even available.
- **Target:** plan cost = budget by default, or a dollar figure typed in.
  Monte Carlo is context only.
- **Import:** a wide sheet with one column per month of the year's span
  (`name,Oct,...,Sep` for an Oct-start fiscal year) seeds the grid.

## Plan cost (the number the solver aims at)

```
plan cost = Σ people: rate × (hours up to as_of + plan hours after as_of) + non-labor
```

- "Hours up to as_of" is the reading of spend when one is given, else the
  plan's own hours to that date.
- A plan name with no rate in people.csv is not costed, and is listed in
  `uncosted`.
- On a project where `plan.csv` and `people.csv` agree, this matches step B's
  one-model total. Until step B lands, the Forecast tab is still built from
  people.csv `util_*`, so its total can differ.

## Solver: `budgie/core/solve.py` (pure, no UI)

- `PlanCosting`: the plan, rates, year, PTO (flat or per person), non-labor,
  spent, as_of.
  - `cost(plan)`: the number above.
  - `grid(name)`: FTE per month, averaged over the month's working days
    after `as_of`.
  - `rate(name, month)`: dollars per 1.0 FTE for those days.
  - `editable(month)`: false once the month has no working days after
    `as_of`.
- `solve(costing, cells, target, mode, cap)` returns `Solution`: new FTE per
  cell, the resulting cost, and the gap still left.
  - Changing a cell from f to f' moves the cost by exactly
    `(f' − f) × rate(cell)`, so the solve is closed-form:
    - **proportional:** every cell × k, where
      `k = 1 + gap / Σ rate·f`;
    - **even:** every cell + d, where `d = gap / Σ rate`.
  - FTE is clamped to `[0, cap]` (cap 1.0 by default). Clamped cells are
    fixed and the rest re-solved until nothing new clamps. Whatever gap is
    left is reported, never hidden.
  - Proportional with all cells at 0 falls back to even, and the solution
    carries a note saying so.
- `entries_for(costing, edits)` turns `{(name, month): fte}` into
  `PlanEntry` rows: one at the month's first counted day, one at each
  existing change date inside the month (so an older mid-month row cannot
  override the edit), and a restore row at the next month start when that
  month is not edited.
  - Preview is `cost(AllocationPlan(plan.entries + entries))`. Commit
    appends the same rows, so preview and commit cannot disagree.

## Grid (budgie-w3l.2, built in `budgie/plan_grid.py`)

The grid gets built after step B, so the Forecast tab agrees with the grid's
readout. It lives in its own module, which the TUI imports, so it does not
collide with the `tui.py` safety work under way. Defaults:
- arrows move between cells, and typing a number then Enter sets a cell;
- space toggles the cell in the selection, and shift+arrows extend it;
- `s` solves the selection to the target, and `S` uses the even spread;
- `t` sets a typed target;
- `c` commits and `x` discards;
- a readout line shows: plan cost · target · gap · P50 · P80.

## Months follow the year's span

A cell's month number is its position in the project's `YearSpan` (budgie-bvd):
1 is the span's first month, so 1 is October in an Oct-start fiscal year.
`solve.months(span)` gives each month's first and last day, and the grid labels
its columns from `span.months` (Oct … Sep). A calendar-year project is the
Jan … Dec case of the same rule.

## Out of scope

- Saved named scenarios (they could sit on top of the scratch layer later).
- A `budgie solve` CLI (cheap to add later on top of `solve`).
- Solving for Monte Carlo percentiles.
