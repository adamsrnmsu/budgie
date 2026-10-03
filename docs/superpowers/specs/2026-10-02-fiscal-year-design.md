# Budgie fiscal year: one year span instead of January 1

Date: 2026-10-02. Status: design approved in chat; spec awaiting review.
Bead: budgie-bvd. Follow-on: perch-w1d (perch earned value) depends on it.

## Purpose

The money in these projects is federal, and the federal fiscal year starts on
October 1. Budgie today assumes a year runs January 1 to December 31: the
budget, the plan, the readings, the pace line, the forecast and the monthly
view all end on December 31. That year has to be the fiscal year, so that
"hours left this year", the forecast and the quarters perch reports match the
budget the funder issues.

A year that starts in October belongs in Budgie, the tool that owns the money
math. perch reads it from Budgie and does no fiscal arithmetic of its own.

## Decisions taken

- **A workspace setting.** `year_start: MM-DD` sits next to `year:` in
  `budgie.yaml`. The default is `01-01`, and with it every number is what
  Budgie prints today.
- **Federal naming.** The year is named for the calendar year it ends in, so
  `year: 2027` with `year_start: 10-01` is FY27, 2026-10-01 to 2027-09-30.
- **The whole money year is fiscal,** not only the reports: the budget, plan,
  readings, pace line, forecast, monthly view, `quarterly` and earned value.
- **No migration.** Existing calendar-2026 projects stay as they are, as the
  record of January to September. FY27 starts as a new Budgie project with
  `year: 2027` and `year_start: 10-01`.
- **One span, used everywhere.** A single value, `YearSpan(first, last)`,
  replaces every hard-coded January 1, December 31, "months 1..12" and
  single-year holiday lookup. Two alternatives were rejected:
  - shifting every date by the offset leaves holidays, ISO weeks and printed
    dates wrong;
  - mapping only the input files and labels leaves the pace line and forecast
    ending December 31.
- **No compatibility shims.** Functions that took `year: int` take
  `span: YearSpan`. perch is the only consumer; its contract test fails first,
  and it changes in the same round.
- **When no year is given,** the CLI uses the fiscal year that contains today,
  instead of the hard-coded 2026.

## The span

`year_span(year, year_start) -> YearSpan` lives in `budgie/core/calendar.py`.

| year | year_start | first      | last       |
|------|------------|------------|------------|
| 2026 | 01-01      | 2026-01-01 | 2026-12-31 |
| 2027 | 10-01      | 2026-10-01 | 2027-09-30 |

`YearSpan` also gives:

- `months`: the 12 `(calendar_year, month)` pairs in fiscal order, from
  October through September;
- `contains(day)`;
- the day before `first`, which is where a cumulative curve is zero.

A bad `year_start` (not `MM-DD`, or a day that does not exist, such as
`02-30`) is an error that names the key and the file.

## Reading the input files

`plan.csv`, `budget.csv` and `costs.csv` carry full dates, so their formats do
not change.

`actuals.csv` (`name,month,hours`) and `weekly.csv` (`name,week,hours_to_date`)
carry a bare month number or ISO week number. Within one fiscal year each
number is still unique, so it maps to a calendar year by rule:

- **Month:** a month at or after the start month belongs to `first`'s
  calendar year; an earlier month belongs to `last`'s. In FY27, months 10, 11
  and 12 are 2026, and 1 to 9 are 2027.
- **Week:** a week numbered at or above the ISO week that contains `first`
  belongs to `first`'s ISO year; a lower number belongs to `last`'s. In FY27,
  weeks 40 to 53 are 2026 (2026 has 53 ISO weeks), and 1 to 39 are 2027.
- **With `01-01`, neither rule applies:** every number belongs to `year`, as
  it does today, so a calendar project's files read exactly as before. This
  is an explicit case, not a reduction of the week rule: January 1, 2027
  falls in ISO week 53 of 2026, so the general rule would misread calendar
  2027.

A reading keeps its real week-ending date. The two edge weeks reach outside
the span: FY27's week 40 starts September 28, 2026, and week 39 of 2027 ends
October 3, 2027. They are clamped by whatever already clamps to the year,
such as the burndown and the pace line, now clamping to the span. There is no
new clamp rule.

"Last reported month" in the monthly loader is taken in fiscal order.

## What changes in Budgie

- **`core/workspace.py`:** add the `year_start` setting, validated as above.
- **`core/calendar.py`:**
  - add `YearSpan` and `year_span`;
  - `productive_hours`, `workdays_in_year` and `hours_per_workday` take a
    span and count holidays through `workdays_between(first, last)`, which
    already loads every calendar year in a range;
  - `ProductiveHours` carries the span.
- **`core/plan.py`:** `allocated_hours`, `fraction_through`,
  `last_planned_day` and `team_hours` walk the span, with holidays from both
  calendar years.
- **`core/actuals.py`:** the month and week rules above. `week_ending`
  resolves the ISO year by the rule before calling `date.fromisocalendar`.
- **`core/burndown.py`:** `burndown()`, `expected_on`, `required_pace`,
  `exhaustion_date` and `days_in_year` start at `first` and end at `last`.
- **`core/eac.py`:** `elapsed_fraction` and `at_completion` count working days
  from `first`.
- **`core/monthly.py`, `core/costs.py`, `core/budget.py` and `plots.py`:**
  - the 12 buckets follow `span.months`;
  - `MONTH_NAMES` output is rotated to fiscal order;
  - `spent_at` is zero on the day before `first`;
  - a recurring cost is booked from its own month through `last`;
  - `costs.monthly_totals` keeps items where `span.contains(when)`.
- **`core/project.py`:**
  - `Snapshot` carries the span;
  - `load_snapshot` builds it from the workspace;
  - `what_if` dates new plan rows at `first`.
- **`core/allocation.py` and `core/scenario.py`:** use the span. The default
  `2026` in `scenario.py` goes away.
- **CLI (`budgie.py`) and `tui.py`:**
  - the six `--year` options say "Year (fiscal when year_start is set)";
  - when no year is given, they fall back to the year containing today;
  - "Jan"/"Dec" wording (`budgie.py:1344,1375-1376`) comes from the span.
- **`init` and `core/scaffold.py`:** `budgie init --year-start MM-DD` writes
  the setting, and template dates start at `first`.
- **`emails.py`:** "to December" becomes "to year end (Sep 30)", the date
  taken from `last`.
- **Docs:**
  - the README covers `year_start`, the naming and the week and month rules;
  - `budgie/core/CLAUDE.md` replaces "anchored to the real calendar year"
    with the span rule;
  - `docs/input-files.md` covers the mapping rules.

## What changes in perch (same round)

perch gets the span from `Snapshot` (through `Money`) and never builds a year
boundary from an integer.

- **`core/money.py`, `core/rate.py` (`window`), `core/join.py`
  (`calibrate`), `core/cut.py`, `core/watch.py`, `core/accuracy.py`,
  `core/report_mail.py` (year to date):**
  - `date(year, 1, 1)` becomes `span.first`;
  - `.year == year` becomes `span.contains(...)`.
- **`core/quarterly.py`:**
  - the quarters are the span cut into four;
  - `--quarter` takes `FY27-Q1` when `year_start` is not `01-01`, and keeps
    `2026-Q3` for calendar projects;
  - `last_complete_quarter` follows the span;
  - the report heading says `FY27 Q1 (Oct 1 – Dec 31, 2026)`.
- **`tests/test_contract.py`:** updated for the new signatures.

## Testing

- **Calendar equivalence.**
  - Budgie's and perch's existing suites run against a calendar span, with
    only mechanical edits (`year=2026` becomes the calendar span).
  - Any expected number that changes is a regression, not an update.
  - This is the proof that projects without `year_start` do not move.
- **A FY27 world.** A small, hand-checkable fixture whose docstring holds the
  arithmetic, in the style of perch's `conftest.py`. It checks:
  - productive hours for 2026-10-01 to 2027-09-30, with federal holidays
    drawn from both calendar years;
  - weekly weeks 40, 53, 1 and 39, and monthly month 10 (2026) and month 9
    (2027), mapping to the right days;
  - the pace line and `required_pace` ending September 30, 2027;
  - monthly forecast buckets running October to September;
  - an exhaustion date that falls in calendar 2027;
  - `year_start` errors naming the key.
- **In perch:**
  - `quarterly` on the FY27 world gives FY27 Q1 = Oct 1 to Dec 31, 2026;
  - `calibrate` counts an issue closed on 2026-12-15 inside FY27;
  - the contract test passes against the new Budgie.

## Out of scope

- Converting or splitting existing calendar projects.
- A per-project `year_start` that differs within one workspace.
- Fiscal labels in gitboard (gitboard has no money year).
- Earned value itself, which is perch-w1d and is built on top of this.

## Changes during planning

The plan (`docs/superpowers/plans/2026-10-02-fiscal-year.md`) settled six
points the spec left open or got wrong:

1. `year_start` must be the first of a month (`MM-01`). Monthly buckets, the
   month-number rule and quarters all need that. `10-15` and `02-29` are
   refused, with an error naming the key and the file.
2. The CLI falls back to the year containing today only inside a project.
   Outside one, it keeps 2026, because the bundled sample files are dated
   2026.
3. `YearSpan.label` prints the year: "2026" for a calendar year, "FY27" for a
   fiscal one. Email functions take the label.
4. The quarterly heading keeps its existing form, `FY27-Q1 runs Oct 1 – Dec
   31`, so the printed name works as input to `--quarter`.
5. Quarters are `YearSpan.quarters`, in Budgie, so perch does no month
   arithmetic.
6. A scenario without a year is an error, not a silent 2026. Scenarios gain
   an optional `year_start`.
