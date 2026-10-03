# Budgie Fiscal Year Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Budgie's money year a span that can start on any month's first day (federal FY27 = 2026-10-01..2027-09-30), and move perch onto that span in the same round.

**Architecture:** One frozen `YearSpan(first, last)` in `budgie/core/calendar.py`, built by `year_span(year, year_start)`, replaces every hard-coded January 1, December 31, "months 1..12" and single-year holiday lookup. Functions that took `year: int` take `span: YearSpan`. The `01-01` default reproduces today's numbers exactly, and the existing suites, edited only mechanically, prove it. perch reads the span from `Snapshot.span` and does no month arithmetic.

**Tech Stack:** Python 3.12, stdlib `datetime`, the `holidays` package (already a dependency), click, Textual, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-10-02-fiscal-year-design.md` (this worktree). Bead: `budgie-bvd`.

## Global Constraints

- `year_start` is `MM-01`, i.e. the first day of a month, written in `budgie.yaml` beside `year:`. The default is `01-01`. A bad value raises `ValueError` naming `year_start` and the file. (This is narrower than the spec's `MM-DD`; see the "Spec deviations" section at the end.)
- Federal naming: `year: 2027` + `year_start: 10-01` = 2026-10-01..2027-09-30, and `YearSpan.label` = `FY27`. A calendar span's label is `2026`.
- No compatibility shims in the final state: `year: int` parameters become `span: YearSpan`. The `emails.py` functions are the one exception, because they use the year only as a printed label. They keep a `year` parameter typed `int | str`, and the CLI passes `span.label` to it.
- Calendar equivalence: an existing test may only be edited mechanically, meaning a year argument `2026` becomes `year_span(2026)`, and `.year` becomes `.span` or `.span.year`. **An expected number never changes.** If one has to change, that is a regression to fix, not an update.
- Mechanical test edits use one shell helper. Define it before Task 2, and again in the perch worktree before Task 9:
  ```bash
  mech() { pat=$1; shift; perl -pi -e "if (/\b(?:$pat)\(/) { s/(?<!date\()(?<!isocalendar\()(?<!span\()\b2026\b(?=\s*[,)])/year_span(2026)/g }" "$@"; }
  ```
  On lines that call one of the named functions, it turns a bare `2026` argument into `year_span(2026)`. It never touches `date(2026, …)`, `fromisocalendar(2026, …)` or an already-converted `year_span(2026)`, so it is safe to re-run. Calls split over several lines are edited by hand. After a `mech` run, add `year_span` to the file's `from budgie.core.calendar import …` line, or add `from budgie.core.calendar import year_span`.
- Bridges: until the task that converts a caller, that caller passes `year_span(year)` with the trailing comment `# bridge: budgie-bvd`. Task 8 ends with a grep that must find no bridges.
- Budgie tests are run from the Budgie worktree root with `PYTHONPATH=$PWD ~/Documents/tools/budgie/bin/pytest -q`. The baseline is 232 passed.
- Budgie lint: `~/Documents/tools/budgie/bin/ruff check . && ~/Documents/tools/budgie/bin/ruff format --check .`
- perch tests run from a perch worktree root (Task 9 creates it): `PYTHONPATH=/Users/ryanadams/Documents/git/pi_suite/budgie/.claude/worktrees/fiscal-year:$PWD ~/Documents/tools/perch/bin/pytest -q`. Never `pip install` into the shared venvs. `PYTHONPATH` already puts both worktrees ahead of the editable installs.
- Commit messages end with these two lines:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_016yzynb2jzmVaBeZ8DjERh9`
  Budgie commits reference `(budgie-bvd)`. perch commits also reference `(budgie-bvd)`: beads can't link across repos, so perch gets no bead of its own.
- **The Budgie and perch branches land together.** perch's venv installs `../budgie` (Budgie's main checkout) editable. Merging Budgie alone would break every perch command until perch's branch lands too.

## Review Focus

1. **FY28 `weekly.csv` with week 53.** ISO 2027 has only 52 weeks, so this must raise `ValueError("2027 has no ISO week 53")` rather than return a wrong date. Owning task: Task 4.
2. **A `year_start` that is not a month's first day** (`02-29`, `10-15`, `13-01`, or a bare int such as `1001`) is refused with an error naming `year_start` and the `budgie.yaml` path. Owning task: Task 1.
3. **An edge-week reading dated past `span.last`.** FY27 week 39 ends 2027-10-03, but the burndown's `as_of` clamps to 2027-09-30, so `days_elapsed == 365` and `required_pace.workdays_remaining == 0`. Owning task: Task 5.
4. **The default year around the boundary.** With `year_start: 10-01`, the default year is 2026 on 2026-09-30 and 2027 on 2026-10-01. Owning tasks: Task 1 (`current_year`) and Task 8 (CLI).
5. **A plan.csv row dated before `span.first`.** For example, a 2026-01-01 row at 0.5 FTE, reused for FY27, is in force for the whole fiscal year: 0.5 × 1,992 = 996.0 h. Owning task: Task 3.

## FY27: the hand-checkable figures

Every FY27 test asserts against these, so they live here once, and a docstring at the top of `budgie/tests/test_year_span.py` carries the same text.

```
FY27 = year_span(2027, "10-01") = 2026-10-01 .. 2027-09-30, 365 days (Feb 2027 has 28).
Federal holidays on a weekday inside it: 11.
  2026: Oct 12 Columbus, Nov 11 Veterans, Nov 26 Thanksgiving, Dec 25 Christmas
  2027: Jan 1, Jan 18 MLK, Feb 15 Washington, May 31 Memorial,
        Jun 18 Juneteenth (obs), Jul 5 Independence (obs), Sep 6 Labor
  (Calendar 2027 has 12: Dec 31, 2027 is New Year's 2028 observed. That day is FY28.)
Working days: 250. Productive hours: 2080 - 11 x 8 = 1992. Per working day: 1992 / 250 = 7.968.
Working days per month, Oct..Sep: 21 19 22 19 19 23 22 20 21 21 22 21  (Q1 = 62).
ISO weeks: 2026-10-01 is in week 40 of 2026, and ISO 2026 has 53 weeks.
  week 40 -> Sun 2026-10-04   week 53 -> Sun 2027-01-03
  week 1  -> Sun 2027-01-10   week 39 -> Sun 2027-10-03 (past the span)
Even burn, 1.0 FTE (1992 h), as of 2026-12-31: 92 days elapsed of 365 -> 1992 x 92/365 = 502.0931...
  Working days after it: 250 - 62 = 188.  Elapsed working share: 62/250 = 0.248.
  600 h spent by then: 600/92 h/day, so 1992 h runs out at day 305.44 -> 2027-08-02.
A 1.0 FTE plan row from 2027-04-01: 127 working days x 7.968 = 1011.936 h.
October's share of the year: 21/250, so its available hours = 1992 x 21/250 = 167.328.
```

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `budgie/core/calendar.py` | `YearSpan`, `year_span`, `year_start_month`, `current_year`, `federal_holidays`; productive hours over a span | 1, 2 |
| `budgie/core/workspace.py` | the `year_start` setting, validated on load | 1 |
| `budgie/core/plan.py` | plan walks over a span | 3 |
| `budgie/core/allocation.py` | `_planned_fte` via `ph.span` | 3 |
| `budgie/core/actuals.py` | week and month number to date, by the span's rule | 4 |
| `budgie/core/burndown.py`, `budgie/core/eac.py` | pace, required pace, exhaustion and elapsed share over a span | 5 |
| `budgie/core/monthly.py`, `costs.py`, `budget.py` | 12 buckets in span order; `month_names(span)` | 6 |
| `budgie/plots.py` | chart axes and titles from the span | 5, 6 |
| `budgie/core/project.py`, `scenario.py` | `Snapshot.span`; `load_snapshot` builds it | 7 |
| `budgie/budgie.py`, `tui.py`, `emails.py`, `core/scaffold.py` | `_span()`, today's-year fallback, labels, `init --year-start` | 8 |
| `README.md`, `docs/input-files.md`, `budgie/core/CLAUDE.md` | the span rule, setting and mapping rules | 2, 4, 5, 8 |
| `budgie/tests/test_year_span.py` (new) | the FY27 docstring plus every FY27 assertion, grouped by task | 1-8 |
| perch `perch/core/{money,rate,join,accuracy,watch,cut}.py`, `perch/cli.py` | `Money.span`, everything else on top of it | 9 |
| perch `perch/core/quarterly.py`, `report_mail.py` | quarters from `span.quarters`, `FY27-Q1` | 10 |

---

### Task 1: `YearSpan`, `year_span`, and the `year_start` setting

**Files:**
- Modify: `budgie/core/calendar.py` (new code after the `GROSS_ANNUAL_HOURS` constant)
- Modify: `budgie/core/workspace.py` (`SETTINGS` near line 107; `load_workspace` near line 322)
- Create: `budgie/tests/test_year_span.py`

**Interfaces:**
- Produces:
  - `YearSpan(first: date, last: date)`, frozen, with these properties:
    - `.year -> int` (`last.year`);
    - `.fiscal -> bool`;
    - `.label -> str`;
    - `.days -> int`;
    - `.zero -> date` (`first - 1 day`);
    - `.months -> list[tuple[int, int]]`;
    - `.quarters -> tuple[tuple[date, date], ...]`;
    - `.contains(day) -> bool`.
  - `year_start_month(text) -> int`
  - `year_span(year: int, year_start: str = "01-01") -> YearSpan`
  - `current_year(year_start: str, today: date) -> int`
  - Workspace setting key `"year_start"`.

- [ ] **Step 1: Write the failing tests.** Create `budgie/tests/test_year_span.py`:

```python
"""Fiscal-year span tests. FY27 = year_span(2027, "10-01"), worked by hand:

2026-10-01 .. 2027-09-30, 365 days. 11 federal holidays fall on a weekday in
it (2026: Oct 12, Nov 11, Nov 26, Dec 25; 2027: Jan 1, Jan 18, Feb 15, May 31,
Jun 18 obs, Jul 5 obs, Sep 6). Calendar 2027 has 12: Dec 31, 2027 is New
Year's 2028 observed, which is FY28. 250 working days; productive hours
2080 - 88 = 1992; 7.968 per working day. Working days Oct..Sep:
21 19 22 19 19 23 22 20 21 21 22 21 (Q1 = 62). ISO: Oct 1, 2026 is week 40 of
2026, which has 53 weeks; week 40 ends Sun 2026-10-04, 53 ends 2027-01-03,
1 ends 2027-01-10, 39 ends 2027-10-03 (past the span). Even burn of 1992 h
as of 2026-12-31: 1992 x 92/365. 600 h by then runs out at day 305.44,
2027-08-02.
"""

from datetime import date

import pytest

from budgie.core.calendar import YearSpan, current_year, year_span, year_start_month
from budgie.core.workspace import load_workspace

FY27 = year_span(2027, "10-01")
CAL26 = year_span(2026)


def test_a_calendar_span_is_the_calendar_year():
    assert CAL26 == YearSpan(date(2026, 1, 1), date(2026, 12, 31))
    assert (CAL26.year, CAL26.label, CAL26.fiscal, CAL26.days) == (2026, "2026", False, 365)
    assert CAL26.months[0] == (2026, 1) and CAL26.months[-1] == (2026, 12)


def test_fy27_runs_october_to_september_and_is_named_for_its_end():
    assert FY27 == YearSpan(date(2026, 10, 1), date(2027, 9, 30))
    assert (FY27.year, FY27.label, FY27.fiscal, FY27.days) == (2027, "FY27", True, 365)
    assert FY27.zero == date(2026, 9, 30)
    assert FY27.months[:3] == [(2026, 10), (2026, 11), (2026, 12)]
    assert FY27.months[-1] == (2027, 9)
    assert FY27.contains(date(2026, 10, 1)) and FY27.contains(date(2027, 9, 30))
    assert not FY27.contains(date(2026, 9, 30))


def test_quarters_cut_the_span_in_four():
    assert FY27.quarters == (
        (date(2026, 10, 1), date(2026, 12, 31)),
        (date(2027, 1, 1), date(2027, 3, 31)),
        (date(2027, 4, 1), date(2027, 6, 30)),
        (date(2027, 7, 1), date(2027, 9, 30)),
    )
    assert CAL26.quarters[2] == (date(2026, 7, 1), date(2026, 9, 30))


@pytest.mark.parametrize("bad", ["02-29", "10-15", "13-01", "00-01", "1-1", 1001, ""])
def test_year_start_must_be_a_months_first_day(bad):
    with pytest.raises(ValueError, match="year_start must be MM-01"):
        year_start_month(bad)


def test_the_year_containing_today_turns_over_on_the_start_day():
    assert current_year("10-01", date(2026, 9, 30)) == 2026
    assert current_year("10-01", date(2026, 10, 1)) == 2027
    assert current_year("01-01", date(2026, 12, 31)) == 2026


def test_a_bad_year_start_in_budgie_yaml_names_the_key_and_the_file(tmp_path):
    config = tmp_path / "budgie.yaml"
    config.write_text('year: 2027\nyear_start: "10-15"\n')
    with pytest.raises(ValueError, match=r"budgie\.yaml: year_start must be MM-01"):
        load_workspace(config)


def test_year_start_is_a_workspace_setting(tmp_path):
    config = tmp_path / "budgie.yaml"
    config.write_text('year: 2027\nyear_start: "10-01"\n')
    assert load_workspace(config).setting("year_start") == "10-01"
```

- [ ] **Step 2: Run the tests and confirm they fail.**
  Run: `PYTHONPATH=$PWD ~/Documents/tools/budgie/bin/pytest -q budgie/tests/test_year_span.py`
  Expected: FAIL at collection with `ImportError: cannot import name 'YearSpan'`.

- [ ] **Step 3: Implement the span in `calendar.py`.**
  - Add `import re` at the top. `dataclass`, `date` and `timedelta` are already imported.
  - Insert this after `GROSS_ANNUAL_HOURS = ...`:

```python
_YEAR_START = re.compile(r"(\d{2})-01")


def year_start_month(text) -> int:
    """The month a ``year_start`` setting names; it must be a month's first day."""
    match = _YEAR_START.fullmatch(str(text).strip())
    if not match or not 1 <= int(match[1]) <= 12:
        raise ValueError(
            f"year_start must be MM-01, the first day of a month "
            f'(e.g. "10-01" for a federal fiscal year), got {text!r}'
        )
    return int(match[1])


@dataclass(frozen=True)
class YearSpan:
    """The money year: ``first`` to ``last`` inclusive, twelve whole months.

    A calendar year starts Jan 1. A fiscal year is named for the calendar year
    it ends in: FY27 is 2026-10-01 to 2027-09-30.
    """

    first: date
    last: date

    @property
    def year(self) -> int:
        return self.last.year

    @property
    def fiscal(self) -> bool:
        return (self.first.month, self.first.day) != (1, 1)

    @property
    def label(self) -> str:
        """How the year prints: ``2026``, or ``FY27`` for a fiscal year."""
        return f"FY{self.year % 100:02d}" if self.fiscal else str(self.year)

    @property
    def days(self) -> int:
        return (self.last - self.first).days + 1

    @property
    def zero(self) -> date:
        """The day before ``first``: where a cumulative curve is 0."""
        return self.first - timedelta(days=1)

    @property
    def months(self) -> list[tuple[int, int]]:
        """The twelve ``(calendar year, month)`` pairs, in the year's order."""
        year, month, out = self.first.year, self.first.month, []
        for _ in range(12):
            out.append((year, month))
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        return out

    @property
    def quarters(self) -> tuple[tuple[date, date], ...]:
        """Four ``(first, last)`` quarters of three whole months each."""
        starts = [date(y, m, 1) for y, m in self.months[::3]]
        ends = [s - timedelta(days=1) for s in starts[1:]] + [self.last]
        return tuple(zip(starts, ends))

    def contains(self, day: date) -> bool:
        return self.first <= day <= self.last


def year_span(year: int, year_start: str = "01-01") -> YearSpan:
    """The span ``year`` names: Jan 1-Dec 31, or the twelve months ending in
    ``year`` that start on ``year_start`` (``"10-01"``: Oct 1 of year - 1)."""
    month = year_start_month(year_start)
    if month == 1:
        return YearSpan(date(year, 1, 1), date(year, 12, 31))
    return YearSpan(date(year - 1, month, 1), date(year, month, 1) - timedelta(days=1))


def current_year(year_start: str, today: date) -> int:
    """The year whose span contains ``today``."""
    month = year_start_month(year_start)
    return today.year + 1 if month > 1 and today.month >= month else today.year
```

- [ ] **Step 4: Add the setting in `workspace.py`.**
  - Change `SETTINGS = ("year", "pto", "iterations", "seed")` to `SETTINGS = ("year", "year_start", "pto", "iterations", "seed")`.
  - In `load_workspace`, directly after `settings = {k: data[k] for k in SETTINGS if k in data}`, add:

```python
    if "year_start" in settings:
        from budgie.core.calendar import year_start_month

        try:
            year_start_month(settings["year_start"])
        except ValueError as exc:
            raise ValueError(f"{path.name}: {exc}") from None
```

  This uses `path.name`, matching the existing "unknown inputs" error in the same function.
  - Update the `Workspace.setting` docstring to read: `"""A pinned default from ``budgie.yaml`` (year, year_start, pto, iterations, seed)."""`

- [ ] **Step 5: Run the new tests, then the whole suite.**
  - Run: `PYTHONPATH=$PWD ~/Documents/tools/budgie/bin/pytest -q budgie/tests/test_year_span.py`. Expected: PASS (13 passed).
  - Run: `PYTHONPATH=$PWD ~/Documents/tools/budgie/bin/pytest -q`. Expected: 245 passed (232 + 13).

- [ ] **Step 6: Lint and commit.**

```bash
~/Documents/tools/budgie/bin/ruff format budgie && ~/Documents/tools/budgie/bin/ruff check .
git add budgie/core/calendar.py budgie/core/workspace.py budgie/tests/test_year_span.py
git commit -m "feat(calendar): YearSpan, year_span and the year_start setting (budgie-bvd)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016yzynb2jzmVaBeZ8DjERh9"
```

---

### Task 2: Productive hours over a span

**Files:**
- Modify: `budgie/core/calendar.py`: `federal_holiday_workdays`, `workdays_in_year`, `hours_per_workday`, `ProductiveHours`, `productive_hours`, and a new `federal_holidays`
- Modify (bridges only): `budgie/core/plan.py:96`, `budgie/core/monthly.py:84`, `budgie/core/eac.py:60`, `budgie/core/allocation.py:146`, `budgie/core/project.py:221`, `budgie/core/scenario.py:91`, `budgie/budgie.py` (lines 327, 589, 695, 932, 1300, 1318, 1337), `budgie/tui.py:668`
- Modify: `budgie/core/CLAUDE.md` (the `calendar.py` bullet)
- Test: `budgie/tests/test_year_span.py`, plus mechanical edits to `test_core.py`, `test_allocation.py`, `test_project.py`, `test_plan*.py`, `test_monthly.py` and `test_tui.py` wherever they call these functions

**Interfaces:**
- Consumes: `YearSpan`, `year_span` (Task 1).
- Produces:
  - `federal_holidays(span) -> holidays.HolidayBase`
  - `federal_holiday_workdays(span) -> int`
  - `workdays_in_year(span) -> int`
  - `hours_per_workday(span, pto_days=0.0) -> float`
  - `productive_hours(span, pto_days=0.0, hours_per_day=8.0) -> ProductiveHours`
  - `ProductiveHours.span: YearSpan`, replacing `.year`.

- [ ] **Step 1: Write the failing tests.** Append to `budgie/tests/test_year_span.py`:

Add `federal_holiday_workdays, hours_per_workday, productive_hours, workdays_in_year` to the file's top `from budgie.core.calendar import …` line, then append:

```python
def test_fy27_counts_holidays_from_both_calendar_years():
    assert federal_holiday_workdays(FY27) == 11
    assert federal_holiday_workdays(year_span(2027)) == 12  # Dec 31 2027: FY28
    assert workdays_in_year(FY27) == 250


def test_fy27_productive_hours():
    ph = productive_hours(FY27)
    assert ph.span == FY27
    assert (ph.holiday_hours, ph.productive_hours) == (88.0, 1992.0)
    assert hours_per_workday(FY27) == pytest.approx(7.968)
```


- [ ] **Step 2: Run the tests and confirm they fail.**
  Run: `PYTHONPATH=$PWD ~/Documents/tools/budgie/bin/pytest -q budgie/tests/test_year_span.py -k "fy27_counts or productive"`
  Expected: FAIL with `TypeError` / `AttributeError` (`year_span` object used as an int).

- [ ] **Step 3: Implement.** In `calendar.py`, replace the four functions and the dataclass field:

```python
def federal_holidays(span: YearSpan) -> holidays.HolidayBase:
    """US federal holidays for every calendar year ``span`` touches."""
    return holidays.UnitedStates(years=range(span.first.year, span.last.year + 1))


def federal_holiday_workdays(span: YearSpan) -> int:
    """Number of US federal holidays that fall on a workday (Mon-Fri) in ``span``.

    Holidays observed on a weekend are shifted by the federal government to an
    adjacent weekday; the ``holidays`` package already encodes those observed
    dates, so counting weekday holidays here reflects days genuinely lost from a
    Mon-Fri schedule. A fiscal year draws on two calendar years' holidays.
    """
    return sum(
        1 for day in federal_holidays(span) if day.weekday() < 5 and span.contains(day)
    )


def workdays_in_year(span: YearSpan) -> int:
    """Working days in the whole span."""
    return workdays_between(span.first, span.last)


def hours_per_workday(span: YearSpan, pto_days: float = 0.0) -> float:
    # body unchanged except: workdays_in_year(span) and productive_hours(span, ...)
```

  The rest of the change:
  - In `hours_per_workday`, keep the docstring and replace the two `year` uses with `span`.
  - In `ProductiveHours`, replace `year: int` with `span: YearSpan`. `YearSpan` must be defined above it, which Task 1's placement already does.
  - In `productive_hours`, rename the parameter to `span: YearSpan`. The docstring's `Args` entry becomes `span: The year to anchor federal holidays to (see :func:`year_span`).` Use `holiday_days = federal_holiday_workdays(span)` and `ProductiveHours(span=span, ...)`.
  - In the module docstring, change "All calculations are anchored to a real calendar year" to "All calculations are anchored to a real year span (:class:`YearSpan`: a calendar or fiscal year)".

- [ ] **Step 4: Bridge every caller.** Each line changes as follows and ends with `# bridge: budgie-bvd`:

| File:line | Before | After |
|---|---|---|
| `core/plan.py:96` | `hours_per_workday(year, pto_days=pto_days)` | `hours_per_workday(year_span(year), pto_days=pto_days)` |
| `core/monthly.py:84` | `productive_hours(year, pto_days=pto_days)` | `productive_hours(year_span(year), pto_days=pto_days)` |
| `core/eac.py:60` | `workdays_in_year(year)` | `workdays_in_year(year_span(year))` |
| `core/allocation.py:146` | `ph.year` | `ph.span.year` |
| `core/project.py:221` | `productive_hours(year, pto_days=pto)` | `productive_hours(year_span(year), pto_days=pto)` |
| `core/scenario.py:91` | `productive_hours(int(spec.get("year", 2026)), ...` | `productive_hours(year_span(int(spec.get("year", 2026))), ...` |
| `budgie.py` (327, 589, 695, 932, 1300) | `productive_hours(year, pto_days=pto)` | `productive_hours(year_span(year), pto_days=pto)` |
| `budgie.py:1318` | `federal_holiday_workdays(year)` | `federal_holiday_workdays(year_span(year))` |
| `budgie.py:1337` | `workdays_in_year(year)` | `workdays_in_year(year_span(year))` |
| `tui.py:668` | `productive_hours(year, pto_days=pto)` | `productive_hours(year_span(year), pto_days=pto)` |

  Notes on the table:
  - The `allocation.py` change is final, not a bridge, so it gets no comment.
  - In each file, add `year_span` to the existing `from budgie.core.calendar import ...` line, or add a new import inside the function where the file imports lazily (as `budgie.py` does).
  - Find any other callers with: `grep -rn "productive_hours(\|hours_per_workday(\|workdays_in_year(\|federal_holiday_workdays(\|\.year\b" budgie --include=*.py | grep -v tests`

- [ ] **Step 5: Edit the existing tests mechanically.** Run this from the worktree root:

```bash
mech 'productive_hours|hours_per_workday|workdays_in_year|federal_holiday_workdays' budgie/tests/*.py
perl -pi -e 'if (/\b(?:productive_hours|hours_per_workday|workdays_in_year|federal_holiday_workdays)\(/) { s/(?<=\()YEAR\b/year_span(YEAR)/g }' budgie/tests/*.py
grep -ln "year_span(" budgie/tests/*.py | xargs grep -L "import.*year_span\|year_span,$" 
```

  The second command lists files that now use `year_span` without importing it. Add `year_span` to each one's `from budgie.core.calendar import ...` line, or add `from budgie.core.calendar import year_span`. Then run `PYTHONPATH=$PWD ~/Documents/tools/budgie/bin/pytest -q`. Fix any remaining failure by hand under the same rule: a year argument becomes `year_span(...)`, `ph.year` becomes `ph.span.year`, and expected values stay as they are.

- [ ] **Step 6: Update the `core/CLAUDE.md` note.**
  - In the `calendar.py` bullet, replace `productive_hours(year, pto_days)` with `productive_hours(span, pto_days)`.
  - Replace `anchored to the real calendar year so weekend-observed shifts are correct` with `anchored to a YearSpan — every calendar year the span touches, so weekend-observed shifts are correct and a fiscal year counts both years' holidays`.
  - At the end of that bullet, add: ``**`YearSpan` / `year_span(year, year_start)`** is the money year: `01-01` is the calendar year, `10-01` the federal fiscal year (FY27 = 2026-10-01..2027-09-30). Every January 1 / December 31 in core reads from it.``

- [ ] **Step 7: Run the suite.**
  Run: `PYTHONPATH=$PWD ~/Documents/tools/budgie/bin/pytest -q`. Expected: 247 passed.
  Run: `grep -c "bridge: budgie-bvd" -r budgie`. Expected: a count of about 11. Note it down, because later tasks must shrink it.

- [ ] **Step 8: Lint and commit.**

```bash
~/Documents/tools/budgie/bin/ruff format budgie && ~/Documents/tools/budgie/bin/ruff check .
git add -A budgie
git commit -m "feat(calendar): productive hours over a YearSpan, holidays from every year it touches (budgie-bvd)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016yzynb2jzmVaBeZ8DjERh9"
```

---

### Task 3: The plan walks a span

**Files:**
- Modify: `budgie/core/plan.py`: `allocated_hours` (line 79), `fraction_through` (113), `last_planned_day` (124), `team_hours` (138), and the imports
- Modify (bridges): `budgie/core/burndown.py:102,115,176`, `budgie/core/eac.py:96`, `budgie/core/monthly.py:150`, `budgie/core/project.py:181,193,235`, `budgie/budgie.py:1480`, `budgie/tui.py:836`. `core/allocation.py:146` becomes final, with no bridge.
- Test: `budgie/tests/test_year_span.py`; mechanical edits in `test_plan.py`, `test_plan_allocations.py`, `test_project.py`, `test_pace.py`

**Interfaces:**
- Consumes: `federal_holidays`, `hours_per_workday(span, ...)` (Task 2).
- Produces:
  - `AllocationPlan.allocated_hours(name, span, pto_days=0.0, through=None) -> float`
  - `fraction_through(name, span, day) -> float | None`
  - `last_planned_day(name, span) -> date | None`
  - `team_hours(span, pto_days=0.0) -> dict[str, float]`

- [ ] **Step 1: Write the failing tests.** Append to `test_year_span.py`. Add `AllocationPlan` and `PlanEntry` to the imports, from `budgie.core.plan`:

```python
def test_a_plan_row_before_the_span_is_in_force_for_all_of_it():
    plan = AllocationPlan((PlanEntry("Ann", date(2026, 1, 1), 0.5),))
    assert plan.allocated_hours("Ann", FY27) == pytest.approx(996.0)  # 0.5 x 1992


def test_a_mid_year_join_counts_from_its_own_day():
    plan = AllocationPlan((PlanEntry("Ben", date(2027, 4, 1), 1.0),))
    assert plan.allocated_hours("Ben", FY27) == pytest.approx(1011.936)  # 127 x 7.968


def test_fraction_through_and_last_planned_day_follow_the_span():
    plan = AllocationPlan(
        (PlanEntry("Cy", date(2026, 10, 1), 1.0), PlanEntry("Cy", date(2027, 3, 1), 0.0))
    )
    assert plan.last_planned_day("Cy", FY27) == date(2027, 2, 26)  # a Friday
    full = AllocationPlan((PlanEntry("Di", date(2026, 10, 1), 1.0),))
    assert full.fraction_through("Di", FY27, date(2026, 12, 31)) == pytest.approx(0.248)
    assert full.team_hours(FY27) == {"Di": pytest.approx(1992.0)}
```

- [ ] **Step 2: Run the tests and confirm they fail.**
  Run: `PYTHONPATH=$PWD ~/Documents/tools/budgie/bin/pytest -q budgie/tests/test_year_span.py -k plan`
  Expected: FAIL with `TypeError` (`date(span, 1, 1)`).

- [ ] **Step 3: Implement it in `plan.py`.**
  - Remove `import holidays`.
  - Change the import to `from budgie.core.calendar import YearSpan, federal_holidays, hours_per_workday`.
  - Replace the four methods with:

```python
    def allocated_hours(
        self,
        name: str,
        span: YearSpan,
        pto_days: float = 0.0,
        through: date | None = None,
    ) -> float:
        """Hours this person's plan buys them across ``span``.

        ``through`` stops the count at that date (inclusive), giving the plan's
        hours accumulated so far rather than the year's total.

        Sums each working day at the FTE in effect that day, so someone starting
        2026-07-15 at 0.50 FTE is charged only for the working days from July 15
        onward -- not a full-month or full-year approximation. A row dated
        before the span is in force from its first day.
        """
        per_day = hours_per_workday(span, pto_days=pto_days)
        schedule = self.changes_for(name)
        if not schedule:
            return 0.0

        us_holidays = federal_holidays(span)
        end = span.last if through is None else min(span.last, through)
        # Never start before the person's first effective date.
        day = max(span.first, schedule[0].effective_date)
        total = 0.0
        while day <= end:
            if day.weekday() < 5 and day not in us_holidays:
                total += self.fte_on(name, day) * per_day
            day += timedelta(days=1)
        return total

    def fraction_through(self, name: str, span: YearSpan, day: date) -> float | None:
        """Share (0..1) of this person's year of plan hours accrued by ``day``.

        PTO scales every day equally, so the ratio needs no PTO figure. ``None``
        when the plan has no hours for them -- the caller keeps its own default.
        """
        total = self.allocated_hours(name, span)
        if total <= 0:
            return None
        return self.allocated_hours(name, span, through=day) / total

    def last_planned_day(self, name: str, span: YearSpan) -> date | None:
        """Last working day in ``span`` on which the plan has them above 0 FTE."""
        us_holidays = federal_holidays(span)
        day = span.last
        while day >= span.first:
            if (
                day.weekday() < 5
                and day not in us_holidays
                and self.fte_on(name, day) > 0
            ):
                return day
            day -= timedelta(days=1)
        return None

    def team_hours(self, span: YearSpan, pto_days: float = 0.0) -> dict[str, float]:
        """Allocated hours for everyone in the plan."""
        return {n: self.allocated_hours(n, span, pto_days) for n in self.names}
```

- [ ] **Step 4: Update the callers.**
  - `allocation.py:146` (final): `plan.allocated_hours(name, ph.span, pto_days=days) / ceiling`.
  - Bridges, each ending with `# bridge: budgie-bvd`:
    - **`burndown.py`:** `self.plan.fraction_through(self.allocation.name, year_span(self.year), self.as_of)` at line 102, and the same `year_span(self.year)` at lines 115 and 176 (`last_planned_day`).
    - **`eac.py:96`:** `plan.fraction_through(person.name, year_span(year), when)`.
    - **`monthly.py:150`:** `plan.fraction_through(person.name, year_span(year), day)`.
    - **`project.py`:** line 181 `plan.team_hours(year_span(self.year), self.pto)`, line 193 `plan.allocated_hours(name, year_span(self.year), pto)`, and line 235 `plan.team_hours(year_span(year), pto_days=pto)`.
    - **`budgie.py:1480`:** `allocation_plan.allocated_hours(name, year_span(year), pto_days=days)`.
    - **`tui.py:836`:** `plan.allocated_hours(name, year_span(year), pto_days=...)`.

- [ ] **Step 5: Edit the tests mechanically.**

```bash
mech 'allocated_hours|fraction_through|last_planned_day|team_hours' budgie/tests/*.py
```

  Add the missing `year_span` imports as in Task 2, then run the suite and fix any remaining failures by hand under the same rule.

- [ ] **Step 6: Run the suite.** Expected: 250 passed.

- [ ] **Step 7: Lint and commit** with the message `feat(plan): plan hours walk a YearSpan (budgie-bvd)` plus the two attribution lines. Use `git add -A budgie`.

---

### Task 4: Week and month numbers map into the span

**Files:**
- Modify: `budgie/core/actuals.py`: `week_ending` (46), `load_weekly_actuals` (56), `monthly_to_observations` (82)
- Modify: `budgie/core/project.py`: `load_observations` (57)
- Modify (bridges): `budgie/core/project.py:229`, `budgie/budgie.py:388,593,737`
- Modify: `docs/input-files.md`, `README.md` (the `weekly.csv` paragraph near line 439)
- Test: `test_year_span.py`; mechanical edits in `test_core.py`, `test_burndown.py`, `test_project.py`, `test_monthly.py`

**Interfaces:**
- Consumes: `YearSpan.fiscal`, `.year`, `.months` (Task 1).
- Produces:
  - `week_ending(span, week) -> date`
  - `load_weekly_actuals(csv_path, span)`
  - `monthly_to_observations(span, monthly_hours)`
  - `load_observations(span, actuals=None, weekly=None)`

- [ ] **Step 1: Write the failing tests.** Append to `test_year_span.py`, importing `week_ending`, `load_weekly_actuals` and `monthly_to_observations` from `budgie.core.actuals`:

```python
@pytest.mark.parametrize(
    "week, ends",
    [(40, date(2026, 10, 4)), (53, date(2027, 1, 3)), (1, date(2027, 1, 10)),
     (39, date(2027, 10, 3))],
)  # fmt: skip
def test_fy27_week_numbers_map_by_the_start_week(week, ends):
    assert week_ending(FY27, week) == ends


def test_week_53_in_a_year_whose_first_iso_year_has_52_is_refused():
    fy28 = year_span(2028, "10-01")  # starts 2027-10-01; ISO 2027 has 52 weeks
    with pytest.raises(ValueError, match="2027 has no ISO week 53"):
        week_ending(fy28, 53)


def test_a_calendar_year_keeps_every_week_number_in_that_year():
    # Jan 1, 2027 is ISO week 53 of 2026; calendar 2027's week 1 is still 2027's.
    assert week_ending(year_span(2027), 1) == date(2027, 1, 10)


def test_weekly_csv_reads_into_fy27(tmp_path):
    csv = tmp_path / "weekly.csv"
    csv.write_text("name,week,hours_to_date\nAnn,40,10\nAnn,1,50\n")
    assert load_weekly_actuals(csv, FY27) == {
        "Ann": [(date(2026, 10, 4), 10.0), (date(2027, 1, 10), 50.0)]
    }


def test_monthly_hours_run_in_fiscal_order_and_stop_at_the_last_reported():
    hours = [0.0] * 12
    hours[9], hours[10], hours[0] = 10.0, 20.0, 5.0  # Oct, Nov, Jan
    assert monthly_to_observations(FY27, hours) == [
        (date(2026, 10, 31), 10.0),
        (date(2026, 11, 30), 30.0),
        (date(2026, 12, 31), 30.0),  # December between two readings: a real 0
        (date(2027, 1, 31), 35.0),
    ]
```

- [ ] **Step 2: Run the tests and confirm they fail.** Run: `... pytest -q budgie/tests/test_year_span.py -k "week or monthly"`. Expected: FAIL.

- [ ] **Step 3: Implement it in `actuals.py`.** Add `from budgie.core.calendar import YearSpan`, then:

```python
def week_ending(span: YearSpan, week: int) -> date:
    """The date ISO ``week`` ends (its Sunday) in the year ``span`` covers.

    "Hours up to week N" means through the end of that week, so this is the
    correct as-of date for such a reading. In a fiscal year a week numbered at
    or above the ISO week holding the first day belongs to that day's ISO year,
    a lower one to the last day's: in FY27 weeks 40-53 are 2026, 1-39 are 2027.
    A calendar year keeps every number in that year, as it always has.
    """
    iso_year = span.year
    if span.fiscal:
        first_year, first_week, _ = span.first.isocalendar()
        iso_year = first_year if week >= first_week else span.last.isocalendar()[0]
    try:
        return date.fromisocalendar(iso_year, week, 7)
    except ValueError as exc:  # week 53 in a 52-week year, week 0, etc.
        raise ValueError(f"{iso_year} has no ISO week {week}") from exc
```

  The other changes in this step:
  - **`load_weekly_actuals(csv_path, span: YearSpan)`:** inside, use `when = week_ending(span, as_int(row, "week"))`.
  - **`monthly_to_observations`:** replace it with the version below.

```python
def monthly_to_observations(
    span: YearSpan, monthly_hours: list[float]
) -> list[Observation]:
    """Convert per-month hours (index 0 = January) into cumulative month-end
    observations, in the order the year runs (October first in FY27).

    Stops after the last month that has hours. A trailing empty month is a
    month nobody has reported yet, not a reading of zero -- emitting it would
    date the latest observation on the year's last day and leave no year to
    pace against. An empty month *between* two reported ones is a real reading
    and is kept.
    """
    ordered = [monthly_hours[month - 1] for _, month in span.months]
    reported = max((i + 1 for i, h in enumerate(ordered) if h), default=0)
    out: list[Observation] = []
    running = 0.0
    for (year, month), hours in zip(span.months[:reported], ordered):
        running += hours
        out.append((last_day_of_month(year, month), running))
    return out
```

  - **`project.load_observations(span: YearSpan, actuals=None, weekly=None)`:** pass `span` through to both loaders.
  - **Bridges:**
    - `project.py:229`: `load_observations(year_span(year), actuals, weekly)  # bridge: budgie-bvd`;
    - `budgie.py:388` (`_with_actuals`), `:593` (`hours`) and `:737` (`_burndown_statuses`): `load_observations(year_span(year), ...)  # bridge: budgie-bvd`.

- [ ] **Step 4: Edit the tests mechanically.**

```bash
mech 'week_ending|load_weekly_actuals|monthly_to_observations|load_observations' budgie/tests/*.py
```

  Add the missing imports, run the suite, and fix the rest by hand. `week_ending(2026, 99)` becomes `week_ending(year_span(2026), 99)`, and its expected message "2026 has no ISO week 99" is unchanged.

- [ ] **Step 5: Write the docs.**
  - In `docs/input-files.md`, append this paragraph at the end of the `weekly.csv` section and repeat it in the monthly `actuals.csv` section:
    > In a fiscal year (`year_start` in budgie.yaml) a bare week or month number belongs to the calendar year that keeps it inside the money year. FY27 runs 2026-10-01 to 2027-09-30, so weeks 40–53 and months 10–12 are 2026, and weeks 1–39 and months 1–9 are 2027. A calendar year reads every number in that year, as it always has.
  - In `README.md`, add the same sentence after the "Or **cumulative hours through an ISO week**" paragraph (line 439).

- [ ] **Step 6: Run the suite.** Expected: 258 passed (250 + 8).

- [ ] **Step 7: Lint and commit** with the message `feat(actuals): week and month numbers map into a fiscal year (budgie-bvd)` plus the attribution lines. Use `git add -A budgie docs README.md`.

---

### Task 5: Burndown, estimate at completion and the burn-down chart over a span

**Files:**
- Modify: `budgie/core/burndown.py`: `BurndownStatus` (fields, `planned`, `expected_on`, `required_pace`, `exhaustion_date`), `burndown()`, and the module docstring
- Modify: `budgie/core/eac.py`: `elapsed_fraction`, `at_completion`
- Modify: `budgie/plots.py:95-96,172` (`burndown_chart`)
- Modify (bridges): `budgie/core/monthly.py:151` (`elapsed_fraction`), `budgie/budgie.py:395` (`at_completion`), `budgie/budgie.py:747` (`burndown`)
- Modify: `budgie/core/CLAUDE.md` (the burndown, eac and actuals bullets)
- Test: `test_year_span.py`; mechanical edits in `test_burndown.py`, `test_pace.py`, `test_eac.py`, `test_emails.py`, `test_allocation.py`, `test_monthly.py`

**Interfaces:**
- Consumes: `plan.fraction_through(name, span, day)` and `last_planned_day(name, span)` (Task 3); `workdays_in_year(span)` (Task 2).
- Produces:
  - `burndown(allocation, span, as_of=None, observations=None, plan=None) -> BurndownStatus`
  - `BurndownStatus.span: YearSpan`, replacing `.year`
  - `elapsed_fraction(span, as_of) -> float`
  - `at_completion(people, observations, span, as_of=None, plan=None) -> Completion`

- [ ] **Step 1: Write the failing tests.** Append to `test_year_span.py`, importing `Allocation` from `budgie.core.allocation`, `burndown` from `budgie.core.burndown`, and `elapsed_fraction` from `budgie.core.eac`:

```python
def _full_time(spent=0.0):
    return Allocation("Ann", 1.0, spent, 1992.0)


def test_fy27_even_burn_starts_october_first():
    st = burndown(_full_time(), FY27, as_of=date(2026, 12, 31))
    assert st.span == FY27 and (st.days_in_year, st.days_elapsed) == (365, 92)
    assert st.expected_by_now == pytest.approx(1992 * 92 / 365)
    assert st.required_pace.workdays_remaining == 188  # through 2027-09-30


def test_fy27_exhaustion_date_lands_in_calendar_2027():
    st = burndown(_full_time(600.0), FY27, as_of=date(2026, 12, 31))
    assert st.exhaustion_date == date(2027, 8, 2)  # day 305.44 after Oct 1


def test_an_edge_week_reading_past_the_span_clamps_to_its_last_day():
    st = burndown(_full_time(), FY27, observations=[(date(2027, 10, 3), 1900.0)])
    assert st.as_of == date(2027, 9, 30)
    assert st.days_elapsed == 365 and st.required_pace.workdays_remaining == 0


def test_fy27_elapsed_share_counts_working_days_from_october():
    assert elapsed_fraction(FY27, date(2026, 12, 31)) == pytest.approx(0.248)
    assert elapsed_fraction(FY27, date(2026, 9, 30)) == 0.0
```

  Before writing these, check the `Allocation` constructor order (`name, fte, hours_spent, available_hours`) in `budgie/core/allocation.py`. Use keyword arguments if it differs.

- [ ] **Step 2: Run the tests and confirm they fail.** Expected: FAIL (`TypeError` on `date(year, 1, 1)`).

- [ ] **Step 3: Implement it in `burndown.py`.**
  - Import `YearSpan` from `budgie.core.calendar`.
  - In `BurndownStatus`, replace `year: int` with `span: YearSpan`.
  - Replace the methods as shown:

```python
    @property
    def planned(self) -> bool:
        """Whether the plan has hours for this person (else pace is an even burn)."""
        return (
            self.plan is not None
            and self.plan.fraction_through(self.allocation.name, self.span, self.as_of)
            is not None
        )

    def expected_on(self, day: date) -> float:
        """Hours they'd have spent by ``day`` on pace.

        The plan's hours accumulated through ``day`` when they have a plan,
        otherwise an even burn across the year.
        """
        day = min(max(day, self.span.first), self.span.last)
        name = self.allocation.name
        fraction = (
            self.plan.fraction_through(name, self.span, day) if self.plan else None
        )
        if fraction is None:
            fraction = ((day - self.span.first).days + 1) / self.days_in_year
        return self.allocation.allocated_hours * fraction
```

  The rest of `burndown.py`:
  - **`required_pace`:** use `end = self.span.last` and `self.plan.last_planned_day(self.allocation.name, self.span) or end`. In its docstring, "not Dec 31" becomes "not the year's last day".
  - **`exhaustion_date`:** `return self.span.first + timedelta(days=day)`.
  - **`burndown()`:** the parameter becomes `span: YearSpan`, with docstring `span: The budget year (see :func:`~budgie.core.calendar.year_span`).` Use `start, end = span.first, span.last` and `days_in_year = span.days`, and pass `span=span` to the dataclass.
  - **Module docstring:** "the straight line from 0 hours on Jan 1 to the full allocation on Dec 31" becomes "the straight line from 0 hours on the year's first day to the full allocation on its last".

  In `eac.py`, import `YearSpan` and write:

```python
def elapsed_fraction(span: YearSpan, as_of: date) -> float:
    """Share of ``span``'s working days gone by the end of ``as_of``, in [0, 1].

    Working days are Mon-Fri minus federal holidays, and ``as_of`` itself counts
    as elapsed -- a reading dated the 30th includes the 30th's hours. Dates
    outside the year clamp to its ends.
    """
    if as_of < span.first:
        return 0.0
    return workdays_between(span.first, min(as_of, span.last)) / workdays_in_year(span)
```

  Also in `eac.py`:
  - `at_completion(people, observations, span: YearSpan, as_of=None, plan=None)`;
  - inside it, `plan.fraction_through(person.name, span, when)` and `elapsed_fraction(span, when)`. Remove the Task 3 bridge here.

  In `plots.burndown_chart`:
  - `start, end = status.span.first, status.span.last`;
  - the title becomes `f"{alloc.name} — {status.span.label} hours burn-down"`.

  Remove the bridges in `burndown.py` (Task 3).

- [ ] **Step 4: Add new bridges.** Each ends with `# bridge: budgie-bvd`:
  - `monthly.py:151`: `elapsed_fraction(year_span(year), day)`;
  - `budgie.py:395`: `at_completion(people, observations, year_span(year), as_of=..., plan=plan)`;
  - `budgie.py:747`: `burndown(alloc, year_span(year), as_of=as_of_date, observations=obs, plan=plan)`.

- [ ] **Step 5: Edit the tests mechanically.**

```bash
mech 'burndown|at_completion|elapsed_fraction' budgie/tests/*.py
```

  Then:
  - Lines where `burndown(` spans several lines (for example `pace = burndown(` in `test_pace.py`) need the year argument changed by hand.
  - `st.year` and `status.year` become `.span.year`.
  - Add the missing imports and run the suite.
  - `test_burndown.py:35` `assert st.exhaustion_date.year == 2026` is a date's `.year`; leave it alone.

- [ ] **Step 6: Update `core/CLAUDE.md`.**
  - In the burndown bullet, `burndown(allocation, year, as_of)` becomes `burndown(allocation, span, as_of)`, and `plan.fraction_through(name, year, day)` becomes `plan.fraction_through(name, span, day)`.
  - In the eac bullet, `at_completion(people, observations, year, as_of)` becomes `at_completion(people, observations, span, as_of)`, and `elapsed_fraction(year, date)` becomes `elapsed_fraction(span, date)`.
  - In the actuals bullet, "dated the latest observation Dec 31" becomes "dated the latest observation on the year's last day".

- [ ] **Step 7: Run the suite.** Expected: 262 passed.

- [ ] **Step 8: Lint and commit** with the message `feat(burndown): pace, required pace and EAC over a YearSpan (budgie-bvd)` plus the attribution lines.

---

### Task 6: Months, costs and budget steps in span order

**Files:**
- Modify: `budgie/core/monthly.py`:
  - new `month_names`;
  - `month_weights`, `monthly_available_hours`, `spent_at`, `_cum_hours`;
  - `MonthlyForecast` / `monthly_forecast`, `MonthlySimulation` / `monthly_simulation`;
  - the module docstring.
- Modify: `budgie/core/costs.py:107-120` (`monthly_totals`) and the `recurring` docstring wording "through December"
- Modify: `budgie/core/budget.py:96-98` (`monthly_amounts`)
- Modify: `budgie/plots.py` (`fan_chart`, `monthly_cost_bars`), `budgie/budgie.py` (`_print_monthly_table`, and bridges in the `monthly` command)
- Modify: `budgie/core/CLAUDE.md` (the costs bullet: "through December" becomes "through the year's last month")
- Test: `test_year_span.py`; mechanical edits in `test_monthly.py`, `test_costs_budget.py`, `test_eac.py`

**Interfaces:**
- Consumes: `YearSpan.months`, `.zero`, `.label` (Task 1); `elapsed_fraction(span, ...)` (Task 5); `productive_hours(span)` (Task 2).
- Produces:
  - `month_names(span) -> tuple[str, ...]`
  - `month_weights(span)`, `monthly_available_hours(span, pto_days=0.0)`
  - `spent_at(series, day, span)`
  - `monthly_forecast(people, span, ...)` and `monthly_simulation(people, span, ...)`
  - `MonthlyForecast.span` and `MonthlySimulation.span`, replacing `.year`
  - `monthly_totals(items, span)`
  - `Budget.monthly_amounts(span)`

- [ ] **Step 1: Write the failing tests.** Append to `test_year_span.py`, importing `month_names`, `month_weights`, `monthly_available_hours` and `spent_at` from `budgie.core.monthly`, `CostItem` and `monthly_totals` from `budgie.core.costs`, and `Budget` and `BudgetRevision` from `budgie.core.budget`:

```python
def test_fy27_months_run_october_to_september():
    assert month_names(FY27)[:3] == ("Oct", "Nov", "Dec")
    assert month_names(FY27)[-1] == "Sep"
    assert month_weights(FY27)[0] == pytest.approx(21 / 250)
    assert monthly_available_hours(FY27)[0] == pytest.approx(167.328)


def test_fy27_spend_curve_is_zero_on_september_30():
    assert spent_at([(date(2026, 10, 31), 31.0)], date(2026, 10, 1), FY27) == 1.0


def test_costs_outside_the_span_are_left_out_and_recurring_runs_to_september():
    items = [
        CostItem("old", 999.0, date(2026, 9, 15)),
        CostItem("cloud", 100.0, date(2026, 11, 1), recurring=True),
    ]
    assert monthly_totals(items, FY27) == [0.0] + [100.0] * 11


def test_budget_steps_follow_fiscal_month_ends():
    budget = Budget(
        (BudgetRevision(date(2026, 10, 1), 1000.0), BudgetRevision(date(2027, 4, 1), 1200.0))
    )
    assert budget.monthly_amounts(FY27) == [1000.0] * 6 + [1200.0] * 6
```

  Check `CostItem`'s field order in `costs.py` (`name, amount, when, category, low, high, recurring`) and use keywords where needed.

- [ ] **Step 2: Run the tests and confirm they fail.**

- [ ] **Step 3: Implement it in `monthly.py`.**
  - Import `YearSpan` from `budgie.core.calendar` and `last_day_of_month` from `budgie.core.csvio`.
  - Keep `MONTH_NAMES` (calendar order) and add the functions below.

```python
def month_names(span: YearSpan) -> tuple[str, ...]:
    """Month abbreviations in the order ``span`` runs (Oct first in FY27)."""
    return tuple(MONTH_NAMES[month - 1] for _, month in span.months)


def month_weights(span: YearSpan) -> list[float]:
    """Each month's share of the year's working days (sums to 1.0)."""
    counts = [workdays_in_month(y, m) for y, m in span.months]
    total = sum(counts)
    return [c / total for c in counts]


def monthly_available_hours(span: YearSpan, pto_days: float = 0.0) -> list[float]:
    """The year's available hours split across months by working-day share."""
    annual = productive_hours(span, pto_days=pto_days).available_hours
    return [annual * w for w in month_weights(span)]
```

  - **`spent_at(series, day, span: YearSpan)`:** start with `prev_day, prev_hours = span.zero, 0.0`. The docstring changes "starts at 0 on Dec 31 of the prior year" to "starts at 0 on the day before the year's first", and its `Args` entry to `span: The budget year (fixes where the curve starts).`
  - **`_cum_hours(person, span, actuals, total)`:**
    - use `month_weights(span)`;
    - use `plan.fraction_through(person.name, span, day)` and `elapsed_fraction(span, day)`, removing both bridges;
    - replace the loop with:

```python
    for year, month in span.months:
        end = last_day_of_month(year, month)
        past = end < when
        booked.append(spent_at(series, end, span) if past else spent)
```

  - Keep the rest of the loop body as it is.
  - **`MonthlyForecast` and `MonthlySimulation`:** `year: int` becomes `span: YearSpan`.
  - **`monthly_forecast(people, span, pto_days=0.0, costs=(), actuals=None)` and `monthly_simulation(people, span, ...)`:** replace every `year` with `span`, including `monthly_totals(costs, span)`, `_cum_hours(p, span, ...)`, `MonthlyForecast(span=span, ...)` and `MonthlySimulation(span=span, ...)`.
  - **Module docstring:** "spreads that year across its twelve months" stays, plus the sentence "The twelve months are the span's own, so a fiscal year's run October to September."

  In `costs.py`, replace `monthly_totals` with:

```python
def monthly_totals(items: Sequence[CostItem], span: YearSpan) -> list[float]:
    """Non-labor cost booked in each month of ``span``, in the year's order.

    A one-off lands in its own month; a recurring line is booked in every month
    from its own through the year's last. Lines dated outside the span are left
    out.
    """
    months = [0.0] * 12
    index = {ym: i for i, ym in enumerate(span.months)}
    for item in items:
        start = index.get((item.when.year, item.when.month))
        if start is None:
            continue
        if item.recurring:
            for m in range(start, 12):
                months[m] += item.amount
        else:
            months[start] += item.amount
    return months
```

  The import `from budgie.core.calendar import YearSpan` goes under `TYPE_CHECKING` if `costs.py` must stay free of `holidays`; check its current imports.

  In `budget.py`:

```python
    def monthly_amounts(self, span: YearSpan) -> list[float]:
        """The budget in force at each month end, for a stepped budget line."""
        return [self.amount_on(last_day_of_month(y, m)) for y, m in span.months]
```

  The remaining edits in this step:
  - **`plots.py`:**
    - replace the import `MONTH_NAMES` with `month_names`;
    - in `fan_chart`, use `ax.set_xticklabels(month_names(sim.span), fontsize=9)`, `budget.monthly_amounts(sim.span)` and the title `f"Cumulative cost through {sim.span.label} ({sim.iterations:,} simulations)"`;
    - in `monthly_cost_bars`, use `names = month_names(forecast.span)`, `positions = range(len(names))`, `ax.set_xticklabels(names)` and the title `f"Cost per month, {forecast.span.label} (weighted by working days)"`.
  - **`budgie.py` `_print_monthly_table`:** import `month_names` instead of `MONTH_NAMES`, use the title `f"Monthly breakdown {mf.span.label}"`, and loop with `for i, name in enumerate(month_names(mf.span)):`.
  - **Bridges in the `monthly` command:** `monthly_forecast(people, year_span(year), ...)` and `monthly_simulation(people, year_span(year), ...)`, each with `# bridge: budgie-bvd`.
  - **Assumptions command:** line 1301 becomes `weights = month_weights(year_span(year))  # bridge: budgie-bvd`.

- [ ] **Step 4: Edit the tests mechanically.**

```bash
mech 'month_weights|monthly_available_hours|spent_at|monthly_forecast|monthly_simulation|monthly_totals|monthly_amounts' budgie/tests/*.py
```

  `mf.year` and `sim.year` become `.span.year`. Add the missing imports, run the suite, and fix the rest by hand.

- [ ] **Step 5: Run the suite.** Expected: 266 passed.

- [ ] **Step 6: Lint and commit** with the message `feat(monthly): months, costs and budget steps in the span's order (budgie-bvd)` plus the attribution lines.

---

### Task 7: The snapshot carries the span

**Files:**
- Modify: `budgie/core/project.py`: `Snapshot` (`year` becomes `span`), `what_if`, `_replanned`, `load_snapshot`
- Modify: `budgie/core/scenario.py:90-92`
- Modify: `budgie/core/CLAUDE.md` (the project bullet: "seeded at their flat `fte` from Jan 1" becomes "from the year's first day")
- Test: `test_year_span.py`; mechanical edits in `test_project.py` (`snap.year == 2026` becomes `snap.span.year == 2026`; `Snapshot(year=2026, ...)` becomes `Snapshot(span=year_span(2026), ...)`), `test_startup.py` and `test_tui.py` if they read `.year`

**Interfaces:**
- Consumes: everything from Tasks 1-6.
- Produces: `Snapshot.span: YearSpan` (no `year` field) and `load_snapshot(project)` honouring `year_start`. perch Task 9 consumes these.

- [ ] **Step 1: Write the failing tests.** Append to `test_year_span.py`, importing `shutil`, `Path`, `load_snapshot` from `budgie.core.project`, `PlanEntry`, and `run_scenarios` from `budgie.core.scenario`:

```python
TESTS_DIR = Path(__file__).resolve().parent


def _fy27_project(tmp_path):
    (tmp_path / "budgie.yaml").write_text('year: 2027\nyear_start: "10-01"\nseed: 1\n')
    shutil.copy(TESTS_DIR / "team.csv", tmp_path / "people.csv")
    (tmp_path / "weekly.csv").write_text(
        "name,week,hours_to_date\nAlice,40,10\nAlice,1,50\n"
    )
    return tmp_path


def test_load_snapshot_reads_a_fiscal_year(tmp_path):
    snap = load_snapshot(_fy27_project(tmp_path))
    assert snap.span == FY27
    assert snap.ceiling.productive_hours == 1992.0
    assert snap.readings["Alice"] == [(date(2026, 10, 4), 10.0), (date(2027, 1, 10), 50.0)]


def test_what_if_seeds_a_flat_fte_at_the_spans_first_day(tmp_path):
    project = _fy27_project(tmp_path)
    (project / "allocations.csv").write_text("name,fte,hours_spent\nAlice,0.5,0\n")
    after = load_snapshot(project).what_if(
        plan_entries=[PlanEntry("Alice", date(2027, 4, 1), 0.0)]
    )
    assert after.plan.entries[0] == PlanEntry("Alice", date(2026, 10, 1), 0.5)


def test_a_scenario_without_a_year_is_an_error(tmp_path):
    shutil.copy(TESTS_DIR / "team.csv", tmp_path / "team.csv")
    config = tmp_path / "scenarios.yaml"
    config.write_text("budget: 1000\nscenarios:\n  - name: A\n    people: team.csv\n")
    with pytest.raises(ValueError, match="scenario 'A' has no year"):
        run_scenarios(config)
```

- [ ] **Step 2: Run the tests and confirm they fail.**

- [ ] **Step 3: Implement it in `project.py`.**
  - Import `YearSpan` and `year_span` from `budgie.core.calendar`.
  - In `Snapshot`, replace `year: int` with `span: YearSpan`.
  - In `what_if`, use `PlanEntry(n, self.span.first, flat[n])` and `changes["planned"] = plan.team_hours(self.span, self.pto)`, and change the docstring's "from Jan 1" to "from the year's first day" (twice).
  - In `_replanned`, use `plan.allocated_hours(name, self.span, pto)`.
  - In `load_snapshot`:

```python
    year = workspace.setting("year")
    if year is None:
        raise ValueError(f"{workspace.config_path}: `year` is not set")
    span = year_span(year, workspace.setting("year_start", "01-01"))
    pto = workspace.setting("pto", 0.0)
    ceiling = productive_hours(span, pto_days=pto)
    ...
    readings = {n: s for n, s in load_observations(span, actuals, weekly).items() if s}
    ...
    planned = plan.team_hours(span, pto_days=pto) if plan and not allocations else {}
    ...
    return Snapshot(span=span, ...)
```

  This removes the three `project.py` bridges.

  In `scenario.py`:
  - import `year_span`;
  - before the loop, add `year_start = str(config.get("year_start", "01-01"))`;
  - inside the loop:

```python
        if "year" not in spec:
            raise ValueError(
                f"{config_path}: scenario {spec.get('name', '?')!r} has no year"
            )
        span = year_span(int(spec["year"]), str(spec.get("year_start", year_start)))
        ph = productive_hours(span, pto_days=float(spec.get("pto", 0.0)))
```

  This removes the `scenario.py` bridge.

- [ ] **Step 4: Edit the tests mechanically.**
  - `perl -pi -e 's/\bsnap\.year\b/snap.span.year/g' budgie/tests/*.py`
  - Then hand-edit the `Snapshot(` constructor at `test_project.py:168`: `year=2026,` becomes `span=year_span(2026),`.
  - Run: `grep -n "\.year\b" budgie/tests/*.py | grep -v "exhaustion_date\|d\.year"` and convert any snapshot `.year` reads the grep shows.

- [ ] **Step 5: Run the suite.** Expected: 269 passed.

- [ ] **Step 6: Lint and commit** with the message `feat(project): Snapshot carries the YearSpan; scenarios name their year (budgie-bvd)` plus the attribution lines.

---

### Task 8: The CLI, TUI, init and emails speak the span

**Files:**
- Modify: `budgie/budgie.py`:
  - new `SAMPLE_YEAR` and `_span()`;
  - the six `--year` options (lines 247, 555, 612, 865, 1267, 1436);
  - `forecast`, `_with_actuals`, `hours`, `emails`, `_burndown_statuses`, `_write_html_emails`, `monthly`, `assumptions`, `_print_assumptions_table`, `plan`, `_print_plan_table`;
  - `init` (line 1042).
- Modify: `budgie/tui.py:355,663-674,711,815,836,884`
- Modify: `budgie/emails.py:105,135,197,290,321` (`year: int | str`) and line 278 ("rate to December")
- Modify: `budgie/core/scaffold.py`: `CONFIG_TEMPLATE`, `PLAN_CSV`, `COSTS_CSV`, `BUDGET_CSV`, `SCENARIOS_YAML`, `scaffold_files`, `init_workspace`
- Modify: `README.md` (the config example near line 134, plus a new "Fiscal year" subsection), `budgie/core/CLAUDE.md` (the scaffold bullet)
- Test: `test_year_span.py`; `test_workspace.py` / `test_main.py` only if their output assertions name the changed text

**Interfaces:**
- Consumes: `year_span`, `current_year`, `year_start_month`, `YearSpan.label` (Task 1); every core signature from Tasks 2-7.
- Produces:
  - `init_workspace(directory, year, overwrite=False, year_start="01-01")`
  - `scaffold_files(year, year_start="01-01")`
  - `budgie init --year-start MM-01`
  - CLI default year = the year containing today inside a project, or 2026 (the samples' year) outside one.

- [ ] **Step 1: Write the failing tests.** Append to `test_year_span.py`, importing `CliRunner` from `click.testing`, `cli` from `budgie.budgie`, `init_workspace` from `budgie.core.scaffold`, and `forget_workspaces` from `budgie.core.workspace`:

```python
def test_init_writes_a_fiscal_project_dated_from_october(tmp_path):
    init_workspace(tmp_path, year=2027, year_start="10-01")
    assert 'year_start: "10-01"' in (tmp_path / "budgie.yaml").read_text()
    assert (tmp_path / "plan.csv").read_text().splitlines()[1] == "Alice,2026-10-01,0.90"
    assert load_snapshot(tmp_path).span == FY27


def test_assumptions_in_a_fiscal_project_say_fy27(tmp_path, monkeypatch):
    init_workspace(tmp_path, year=2027, year_start="10-01")
    monkeypatch.chdir(tmp_path)
    forget_workspaces()
    out = CliRunner().invoke(cli, ["assumptions"], env={"COLUMNS": "200"}).output
    forget_workspaces()
    assert "Assumptions in force for FY27" in out
    assert "11 US federal holidays fall Mon-Fri in FY27" in out
    assert "250 in FY27" in out
    assert "(Oct 8.4% ... Nov 7.6%)" in out


def test_init_cli_refuses_a_bad_year_start(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["init", "--here", "--year", "2027", "--year-start", "10-15"])
    assert result.exit_code != 0 and "year_start must be MM-01" in result.output


def test_the_cli_default_year_inside_a_project_is_the_one_containing_today(
    tmp_path, monkeypatch
):
    from budgie import budgie as cli_module

    (tmp_path / "budgie.yaml").write_text('year_start: "10-01"\n')
    monkeypatch.chdir(tmp_path)
    forget_workspaces()
    monkeypatch.setattr(cli_module, "_today", lambda: date(2026, 9, 30))
    assert cli_module._span(None) == year_span(2026, "10-01")
    monkeypatch.setattr(cli_module, "_today", lambda: date(2026, 10, 1))
    assert cli_module._span(None) == FY27
    forget_workspaces()
```

  Where the percentages come from: 21/250 = 8.4% and 19/250 = 7.6%.

- [ ] **Step 2: Run the tests and confirm they fail.**

- [ ] **Step 3: Write the CLI helper.** In `budgie.py`, beside `_setting`:

```python
SAMPLE_YEAR = 2026  # the bundled sample files are dated in 2026


def _today() -> date:
    # Local calendar date is what a budget year is measured in.
    return date.today()  # noqa: DTZ011


def _span(year):
    """The money year: --year, else the project's ``year``, else the year that
    contains today -- or the samples' 2026 when there is no project at all."""
    from budgie.core.calendar import current_year, year_span

    workspace = _workspace()
    start = workspace.setting("year_start", "01-01") if workspace else "01-01"
    default = current_year(start, _today()) if workspace else SAMPLE_YEAR
    return year_span(_setting("year", year, default), start)
```

  Import `date` from `datetime` at the top of `budgie.py` if it isn't already imported; check the existing imports, since heavy imports stay inside functions.

- [ ] **Step 4: Use the span in every command.**
  - **The six `--year` options:** set the help to `"Year (fiscal when the project sets year_start) [default: the project's, else this year]."`
  - **Every `year = _setting("year", year, 2026)` line** becomes `span = _span(year)`. Then replace that function's year uses and remove each bridge:
    - **`forecast`:** `productive_hours(span, ...)`; the log line `f"Productive hours {span.label}: ..."`; `_with_actuals(people, span, ...)`.
    - **`_with_actuals(people, span, ...)`:** `load_observations(span, ...)` and `at_completion(people, observations, span, ...)`.
    - **`hours`:** `productive_hours(span, ...)`, `load_observations(span, ...)`, and the log line `f"Available hours {span.label}: ..."`.
    - **`emails`:** `productive_hours(span, ...)`, `_burndown_statuses(allocs, span, ...)`, `_write_html_emails(statuses, span, out_dir)`, `write_drafts(statuses, span.label, out_dir)`, and `render_email(..., span.label, pace=...)`.
    - **`_burndown_statuses(allocs, span, ...)`:** `load_observations(span, ...)` and `burndown(alloc, span, ...)`.
    - **`_write_html_emails(statuses, span, out_dir)`:** `write_eml_drafts(statuses, span.label, out, charts=charts)`.
    - **`monthly`:** `productive_hours(span, ...)`, `_with_actuals(people, span, ...)`, `monthly_forecast(people, span, ...)`, `monthly_simulation(people, span, ...)`, and the log line `f"... {span.label} split into months ..."`.
    - **`assumptions`:**

```python
    span = _span(year)
    pto = _setting("pto", pto, 0.0)
    ph = productive_hours(span, pto_days=pto)
    weights, names = month_weights(span), month_names(span)
    first, last = span.first, span.last
```

  The `assumptions` rows read: `f"{federal_holiday_workdays(span)} US federal holidays fall Mon-Fri in {span.label} (-{ph.holiday_hours:,.0f} h)"`, `f"{workdays_in_year(span)} in {span.label}; day-level math spreads ..."`, `f" ({names[0]} {weights[0]:.1%} ... {names[1]} {weights[1]:.1%})"`, and `f"expectation is a straight line from 0 on {first:%b} {first.day} to the full allocation on {last:%b} {last.day}"`. Then call `_print_assumptions_table(span.label, rows)`.

  The rest of the CLI:
  - **`plan`:** `span = _span(year)` and `_print_plan_table(allocation_plan, span, pto, pto_by_name)`.
  - **`_print_plan_table`:** the title `f"Allocation plan {span.label}"` and `allocated_hours(name, span, pto_days=days)`.
  - **`init`:**

```python
@click.option("--year", default=None, type=int, help="Year to scaffold for [default: this year].")
@click.option(
    "--year-start",
    default="01-01",
    show_default=True,
    help='First day of the money year: "01-01" calendar, "10-01" federal fiscal '
    "(--year 2027 is then Oct 2026-Sep 2027).",
)
```

  - In `init`'s body: `from budgie.core.calendar import current_year, year_start_month`, then `try: year_start_month(year_start) except ValueError as exc: raise click.BadParameter(str(exc), param_hint="--year-start") from None`, then `year = year or current_year(year_start, _today())`, then `init_workspace(target, year=year, overwrite=force, year_start=year_start)`. Add `year_start` to the function parameters.

- [ ] **Step 5: Update the TUI.**
  - Import `current_year` and `year_span` from `budgie.core.calendar`, and `date`.
  - Line 355 becomes `value=str(self._setting("year", current_year(self._setting("year_start", "01-01"), date.today())))`. Add a `# noqa: DTZ011` comment if ruff flags it.
  - Change `recalculate` to:

```python
        year = self._read_int("year", current_year(self._setting("year_start", "01-01"), date.today()))  # noqa: DTZ011
        span = year_span(year, self._setting("year_start", "01-01"))
        ...
        ph = productive_hours(span, pto_days=pto)
        self._refresh_chrome(span.label, pto)
        ...
        self._refresh_plan(span, pto)
        self._refresh_inputs()
        self._refresh_assumptions(ph, span.label)
```

  Then:
  - In `_refresh_chrome`, change the parameter to `label: str` and use `f"{label}   ·   PTO ..."`.
  - In `_refresh_plan(self, span, pto)`, use `plan.allocated_hours(name, span, ...)`.
  - In `_refresh_assumptions(self, ph, label: str)`, use `f"[b]Assumptions in force for {label}[/b]\n"`.

- [ ] **Step 6: Update the emails.**
  - Annotate the `year` parameter as `year: int | str` in `render_email`, `write_drafts`, `render_html_email`, `build_message` and `write_eml_drafts`, and add `(printed as given: 2026 or FY27)` to the docstrings.
  - In `render_html_email`, replace "rate to December." with `rate to year end ({status.span.last:%b} {status.span.last.day}).`. The template is already an f-string, and a calendar year prints "(Dec 31)".
  - Run `grep -rn "to December" budgie/tests`. If a test asserts the old text, update that assertion, because the wording is the spec's change and not a number.

- [ ] **Step 7: Update the scaffold.**
  - In `CONFIG_TEMPLATE`, add this line after `year: {year}`:
    `year_start: "{year_start}"  # first day of the money year: "01-01" calendar, "10-01" federal fiscal (year 2027 = Oct 2026-Sep 2027)`
  - In `PLAN_CSV`, `{year}-01-01` becomes `{start}` (both rows).
  - In `COSTS_CSV`, `{year}-03-15` becomes `{third_month_15}` and `{year}-01-01` becomes `{start}`.
  - In `BUDGET_CSV`, `{year}-01-01` becomes `{start}` and `{year}-05-01` becomes `{fifth_month}`.
  - In `SCENARIOS_YAML`, add a top-level `year_start: "{year_start}"` line after `seed: 42`.
  - Then:

```python
def scaffold_files(year: int, year_start: str = "01-01") -> dict[str, str]:
    """Filename -> contents for a fresh workspace, dated inside its year."""
    span = year_span(year, year_start)
    months = span.months
    dates = {
        "start": span.first.isoformat(),
        "third_month_15": date(*months[2], 15).isoformat(),
        "fifth_month": date(*months[4], 1).isoformat(),
    }
    return {
        CONFIG_NAME: CONFIG_TEMPLATE.format(year=year, year_start=year_start),
        "README.md": README_TEMPLATE.format(file_list=_file_list()),
        "people.csv": PEOPLE_CSV,
        "allocations.csv": ALLOCATIONS_CSV,
        "plan.csv": PLAN_CSV.format(**dates),
        "costs.csv": COSTS_CSV.format(**dates),
        "budget.csv": BUDGET_CSV.format(**dates),
        "actuals.csv": ACTUALS_CSV,
        "weekly.csv": WEEKLY_CSV,
        "scenarios.yaml": SCENARIOS_YAML.format(year=year, year_start=year_start),
    }
```

  - Change `init_workspace(directory, year, overwrite=False, year_start="01-01")` to pass `scaffold_files(year, year_start)`. For a calendar year `months[2]` is March and `months[4]` is May, so the files are byte-identical to today's.

- [ ] **Step 8: Write the docs.**
  - In `README.md`, under the config example (line 134), add the `year_start` line and this new subsection:

```markdown
### Fiscal year

A federal budget runs October to September. Set `year_start: "10-01"` beside
`year:` and the year is named for the calendar year it ends in: `year: 2027`
is FY27, 2026-10-01 to 2027-09-30. Holidays, working days, the pace line, the
forecast, the monthly view (October first) and every printed label follow it.
`year_start` must be a month's first day; the default `"01-01"` is the
calendar year. `budgie init --year 2027 --year-start 10-01` writes it for you.
```

  - In `core/CLAUDE.md`, in the scaffold bullet, add: "Template dates come from the span (`start`, `third_month_15`, `fifth_month`), so a calendar project's files are unchanged and a fiscal one's start on its first day."

- [ ] **Step 9: Check that no bridges remain and no calendar year is hard-coded.**

```bash
grep -rn "bridge: budgie-bvd" budgie                     # expected: nothing
grep -rn "date(year, 1, 1)\|date(self.year\|, 12, 31)\|_setting(\"year\", year, 2026)\|\"year\", 2026" budgie --include=*.py | grep -v "/tests/"   # expected: nothing
```

  Only `Budget.flat(..., year=1900)` and `SAMPLE_YEAR` may mention a fixed year.

- [ ] **Step 10: Run the full suite and lint.** Expected: 273 passed and a clean ruff. Also run `PYTHONPATH=$PWD ~/Documents/tools/budgie/bin/python -m budgie.budgie assumptions` from `/tmp` (no project) and check that it still says "Assumptions in force for 2026".

- [ ] **Step 11: Commit** with the message `feat(cli): every command, the TUI, init and emails on the YearSpan; init --year-start (budgie-bvd)` plus the attribution lines.

---

### Task 9: perch reads the span (contract, Money, rates, cut, watch)

perch main moves often. Create the worktree at execution time and re-run the greps in Step 4 there.

**Files (perch repo):**
- Modify: `perch/tests/test_contract.py`
- Modify: `perch/core/money.py`: `Money.year` becomes `Money.span`; `booked`; `money_from`
- Modify: `perch/core/rate.py:47-96` (`window`, `build_intervals`)
- Modify: `perch/core/join.py:39-52` (`calibrate`)
- Modify: `perch/core/accuracy.py:100`, `perch/core/watch.py:124`, `perch/core/cut.py:30-52`
- Modify: `perch/cli.py:52,715-719,905,914`
- Modify (bridges, so the suite stays green until Task 10): `perch/core/quarterly.py:188,194,271,276-277,406`
- Test: `perch/tests/test_join.py` (new FY test); mechanical edits in `test_rate.py`, `test_cut.py`, `test_watch.py`, `test_join.py`, `test_accuracy.py`, `test_quarterly.py`

**Interfaces:**
- Consumes: Budgie `Snapshot.span`, `burndown(a, span, ...)`, `spent_at(series, day, span)`, `at_completion(..., span, ...)`, `YearSpan.contains`, `.first`, `.zero`, `.label`, `year_span`.
- Produces (perch):
  - `Money.span: YearSpan`
  - `window(series, span, since)`, `build_intervals(readings, closed, span, since=None)`
  - `calibrate(readings, board, people, span)`
  - `parse_change(flag, names, span, *, leaves=False)`

- [ ] **Step 1: Create the worktree and check the import paths.**

```bash
cd /Users/ryanadams/Documents/git/pi_suite/perch
git worktree add -b fiscal-year .claude/worktrees/fiscal-year main
cd .claude/worktrees/fiscal-year
export PYTHONPATH=/Users/ryanadams/Documents/git/pi_suite/budgie/.claude/worktrees/fiscal-year:$PWD
~/Documents/tools/perch/bin/python -c "import budgie, perch; print(budgie.__file__); print(perch.__file__)"
```

  Expected: both paths are inside the two worktrees. The project's Makefile alternative is `make venv BUDGIE_DIR=/abs/budgie-worktree`, but that reinstalls into the shared venv, so don't use it here.

- [ ] **Step 2: Update the contract test, then watch it fail.** In `test_contract.py`:
  - add `from budgie.core.calendar import YearSpan, year_span`;
  - in the snapshot field list, `"year",` becomes `"span",`;
  - `{"series", "day", "year"} == set(inspect.signature(spent_at).parameters)` becomes `{"series", "day", "span"} == ...`;
  - `{"people", "observations", "year", "as_of", "plan"}` becomes `{"people", "observations", "span", "as_of", "plan"}`;
  - add `assert callable(year_span) and {"first", "last"} <= set(YearSpan.__dataclass_fields__)`.

  Run: `~/Documents/tools/perch/bin/pytest -q perch/tests/test_contract.py`. Expected: PASS, because Budgie's branch already has these. Then run `~/Documents/tools/perch/bin/pytest -q`. Expected: many FAILs (`Snapshot` has no `year`), which is the break this task fixes.

- [ ] **Step 3: Write the failing FY test.** Append to `perch/tests/test_join.py`, importing `year_span` from `budgie.core.calendar` and `Board` and `Issue` from `perch.core.board`:

```python
def test_calibrate_counts_a_december_close_inside_a_fiscal_year():
    fy27 = year_span(2027, "10-01")
    board = Board(
        "grp/proj", "Dev", date(2026, 12, 31),
        (Issue(1, "t", "asmith", (), date(2026, 12, 15)),),
    )  # fmt: skip
    rates = calibrate({"Alice": [(date(2026, 12, 27), 40.0)]}, board, {"asmith": "Alice"}, fy27)
    # Oct 1 to Dec 27: 40 h for 1 issue. A calendar-year filter dropped the close.
    assert rates.people["Alice"].mode == 40.0
```

- [ ] **Step 4: Implement.**

  **`money.py`:**
  - import `YearSpan` from `budgie.core.calendar`;
  - `year: int` becomes `span: YearSpan`;
  - `booked` becomes:

```python
        def at(day: date) -> float:
            return spent_at(series, max(day, self.span.zero), self.span)
```

  - in `money_from`: `span=snap.span` and `burndown(a, snap.span, observations=..., plan=snap.plan)`;
  - the `what_if` docstring's "from Jan 1" becomes "from the year's first day".

  **`rate.py`:**

```python
def window(series: list[Reading], span: YearSpan, since: date | None) -> Reading:
    """Where a person's measurable work opens: (first day, hours booked before it).

    The year's first day with nothing booked, unless the board dump's history
    starts later. ...  (rest of the docstring unchanged)
    """
    start, booked = span.first, 0.0
    ...
```

  - `build_intervals(readings, closed, span: YearSpan, since=None)` uses `window(series, span, since)`;
  - its docstring's "Cut each person's year" stays.

  **`join.py`:** `calibrate(readings, board, people, span: YearSpan)`, filtering with `if i.assignee in people and span.contains(i.closed_on)`, and `build_intervals(readings, closed, span, board.since)`.

  **The rest of perch:**
  - **`accuracy.py:100`:** `window(series, money.span, board.since)`.
  - **`watch.py:124`:** `if people.get(i.assignee) == name and money.span.contains(i.closed_on)`.
  - **`cut.py`:** `parse_change(flag, names, span: YearSpan, *, leaves=False)`, with `if not span.contains(when): raise refuse(f"{when} is outside {span.label}")`. A calendar span keeps the message "outside 2026".
  - **`cli.py`:**
    - line 52: `calibrate(money.readings, board, config.people, money.span)`;
    - lines 715-716: `parse_change(f, names, snap.span, ...)`;
    - line 719: `calibrate(now.readings, the_board, config.people, now.span)`;
    - line 905: `calibrate(..., money.span)`;
    - line 914: `last_complete_quarter(money.span.year, today)  # bridge: budgie-bvd`.
  - **`quarterly.py` bridges** (each with `# bridge: budgie-bvd`):
    - line 188: `at_completion(money.people, money.readings, money.span, ...)` (final, no comment needed);
    - line 194: `year_start = money.span.first` (final);
    - line 271: `day <= money.span.first` (final);
    - lines 276-277: `allocated_hours(name, money.span, money.pto)` (final);
    - lines 403-406: `if start.year != money.span.year:` with message `{money.span.year}`, which is the bridge.

  Re-grep the perch worktree for anything else:

```bash
grep -rn "\.year\b\|date(.*, 1, 1)" perch --include=*.py | grep -v "tests/\|closed_on.year\|today.year\|start.year\|end.year\|when.year\|isocalendar"
```

  Convert each Budgie-year use you find (for example a new `core/status.py`) the same way: `money.span`, or `span.first` / `span.contains`.

- [ ] **Step 5: Edit the perch tests mechanically.**

```bash
perl -pi -e 's/\bmoney\.year\b/money.span/g; s/\bnow\.year\b/now.span/g; s/Money\(year=2026,/Money(span=year_span(2026),/g' perch/tests/*.py
mech 'build_intervals|parse_change' perch/tests/*.py
```

  Add `from budgie.core.calendar import year_span` wherever it's now used, run the suite, and fix the rest by hand. Expected values never change.

- [ ] **Step 6: Run the suite and lint.** Run `~/Documents/tools/perch/bin/pytest -q`. Expected: the pre-change count + 1 passed. Then run `~/Documents/tools/perch/bin/ruff check . && ~/Documents/tools/perch/bin/ruff format --check .`.

- [ ] **Step 7: Commit (perch worktree)** with the message `refactor(money): perch reads Budgie's YearSpan; calibrate, cut and watch use it (budgie-bvd)` plus the attribution lines.

---

### Task 10: Fiscal quarters in `perch quarterly`

**Files (perch repo):**
- Modify: `perch/core/quarterly.py`:
  - `_QUARTER`, `parse_quarter`, `last_complete_quarter`;
  - `Quarter` gets a new `year_start` field;
  - `_previous`, `build`;
  - the docstrings.
- Modify: `perch/core/report_mail.py:159` (year to date from `q.year_start`)
- Modify: `perch/cli.py:914,938` (default quarter; `--quarter` help)
- Modify: `CLAUDE.md` (the quarterly bullet)
- Test: `perch/tests/test_quarterly.py`, `perch/tests/test_report_mail.py` (only if they construct `Quarter(...)` directly)

**Interfaces:**
- Consumes: `YearSpan.quarters`, `.label`, `.first` (Budgie Task 1); `Money.span` (Task 9).
- Produces:
  - `parse_quarter(text, span) -> tuple[date, date]`
  - `last_complete_quarter(span, today) -> str`
  - `Quarter.year_start: date`
  - quarter names `f"{span.label}-Q{n}"` (`2026-Q3`, `FY27-Q1`)

- [ ] **Step 1: Write the failing tests.** In `test_quarterly.py`:
  - add the `span` argument to the existing calls: `parse_quarter("2026-Q3", year_span(2026))`, `parse_quarter(bad, year_span(2026))`, and `last_complete_quarter(year_span(2026), date(...))`;
  - keep every expected value;
  - append:

```python
FY27 = year_span(2027, "10-01")


def test_fiscal_quarters_come_from_budgies_year():
    assert parse_quarter("FY27-Q1", FY27) == (date(2026, 10, 1), date(2026, 12, 31))
    assert parse_quarter("fy27-q4", FY27) == (date(2027, 7, 1), date(2027, 9, 30))
    with pytest.raises(ValueError, match="outside the Budgie project's year, FY27"):
        parse_quarter("2026-Q3", FY27)
    with pytest.raises(ValueError, match="FY27-Q3"):
        parse_quarter("FY27Q1", FY27)


def test_the_default_fiscal_quarter_is_the_last_complete_one():
    assert last_complete_quarter(FY27, date(2026, 12, 31)) == "FY27-Q1"  # none over yet
    assert last_complete_quarter(FY27, date(2027, 1, 1)) == "FY27-Q1"
    assert last_complete_quarter(FY27, date(2027, 4, 1)) == "FY27-Q2"


def test_a_fiscal_quarter_report_is_named_and_dated_by_the_span():
    money = Money(
        span=FY27,
        hourly_cost={"Alice": 50.0},
        people=[Person("Alice", 50.0, HoursEstimate.constant(1000.0))],
    )
    q = build(None, money, {}, None, {}, "FY27-Q1", date(2027, 1, 15), "proj")
    assert (q.name, q.start, q.end, q.year_start) == (
        "FY27-Q1", date(2026, 10, 1), date(2026, 12, 31), date(2026, 10, 1)
    )
    assert "FY27-Q1 runs Oct 1 – Dec 31" in render_md(q)
```

  These need imports: `year_span` (`budgie.core.calendar`), `Person` and `HoursEstimate` (`budgie.core.person`), `Money` (`perch.core.money`), and `render_md` (`perch.core.report_mail`).

- [ ] **Step 2: Run the tests and confirm they fail.** Run `~/Documents/tools/perch/bin/pytest -q perch/tests/test_quarterly.py`. Expected: FAIL (`parse_quarter()` takes 1 positional argument).

- [ ] **Step 3: Implement it in `quarterly.py`.**

```python
_QUARTER = re.compile(r"(\d{4}|FY\d{2})-Q([1-4])", re.IGNORECASE)


def parse_quarter(text: str, span: YearSpan) -> tuple[date, date]:
    """`2026-Q3` -> (Jul 1, Sep 30); `FY27-Q1` -> (Oct 1, Dec 31, 2026).

    The quarters are Budgie's year cut in four, so the name must be that
    year's: a calendar project takes `2026-Q3`, a fiscal one `FY27-Q1`.
    """
    match = _QUARTER.fullmatch(text.strip())
    if not match:
        raise ValueError(f"`{text}` is not a quarter; write it like {span.label}-Q3")
    if match[1].upper() != span.label:
        raise ValueError(f"{text} is outside the Budgie project's year, {span.label}")
    return span.quarters[int(match[2]) - 1]


def last_complete_quarter(span: YearSpan, today: date) -> str:
    """The year's last quarter that is over by `today`; Q1 when none is yet."""
    done = sum(1 for _, end in span.quarters if end < today)
    return f"{span.label}-Q{max(done, 1)}"
```

  The rest of `quarterly.py`:
  - import `YearSpan` from `budgie.core.calendar`.
  - **`Quarter`:** after `end: date`, add `year_start: date  # the Budgie year's first day: year to date counts from it`. The `name` comment becomes `# 2026-Q3, or FY27-Q1`.
  - **`build`:** replace the `parse_quarter` call and the `start.year != money.year` block with `start, end = parse_quarter(quarter, money.span)`. In the `Quarter(...)` call, use `name=f"{money.span.label}-Q{money.span.quarters.index((start, end)) + 1}"` and add `year_start=money.span.first`.
  - **`_previous`:**

```python
def _previous(
    board: Board, money: Money, start: date
) -> tuple[Week | None, int | None]:
    """(totals, blocked issue-days) for the quarter before `start`, or (None,
    None) unless the dump's recorded `since` covers all of it. Q1's previous
    quarter is outside the Budgie year."""
    quarters = money.span.quarters
    n = [a for a, _ in quarters].index(start)
    if n == 0:
        return None, None
    first, end = quarters[n - 1]
    covered = board.since is not None and board.since <= first
    if not covered or end > board.fetched_on:
        return None, None
    closed = sum(1 for i in board.closed if first <= i.closed_on <= end)
    read = money.as_of is not None and end <= money.as_of
    hours = _team(money, first, end, cost=False) if read else None
    name = f"{money.span.label}-Q{n}"
    blocked = _blocked_days(board, first, end, board.since)
    return Week(name, first, end, closed, hours), blocked
```

  - **Docstrings:** in the `Position.spent_year` comment, "Jan 1 to the quarter's last reading" becomes "the year's first day to the quarter's last reading". In `_staffing`, "A row on Jan 1 is the starting team" becomes "A row on the year's first day is the starting team".

  Elsewhere in perch:
  - **`report_mail.py:159`:** `f"Labor spent {_span(q.year_start, to)} (year to date)"`.
  - **`cli.py:914`:** `quarter or last_complete_quarter(money.span, today)`, removing the bridge.
  - **`cli.py:938`:** the help becomes `"e.g. 2026-Q3, or FY27-Q1 for a fiscal year; default the last complete one."`.
  - **`CLAUDE.md` quarterly bullet:** append "Quarters are Budgie's `YearSpan.quarters` (fiscal when the Budgie project sets `year_start`), named `2026-Q3` or `FY27-Q1`."
  - If `test_report_mail.py` builds `Quarter(...)` by hand, add `year_start=date(2026, 1, 1)` there. That is mechanical and matches today's January 1.

- [ ] **Step 4: Run the suite, check for bridges, and lint.**

```bash
~/Documents/tools/perch/bin/pytest -q
grep -rn "bridge: budgie-bvd" perch    # expected: nothing
~/Documents/tools/perch/bin/ruff check . && ~/Documents/tools/perch/bin/ruff format --check .
```

  Expected: the Task 9 count + 3 passed, no bridges, and a clean lint.

- [ ] **Step 5: Commit (perch worktree)** with the message `feat(quarterly): fiscal quarters from Budgie's YearSpan, FY27-Q1 (budgie-bvd)` plus the attribution lines.

---

## Final verification (before landing)

- [ ] Run the full Budgie suite (273 expected) and its lint in the Budgie worktree.
- [ ] Run the full perch suite and its lint in the perch worktree, with `PYTHONPATH` set as in Task 9.
- [ ] Run `bd close budgie-bvd --reason "..."` in `/Users/ryanadams/Documents/git/pi_suite/budgie`, and add a note to `perch-w1d` (perch) saying it is unblocked.
- [ ] Land both branches together (Budgie `fiscal-year`, perch `fiscal-year`) in one sitting, only when the user asks. Budgie goes first, then perch immediately after. Re-run perch's suite against Budgie main once both are merged.

## Self-review

- **Spec coverage.** Every spec item maps to a task:
  - the span: Task 1;
  - the setting and its validation: Task 1;
  - calendar and holidays: Task 2;
  - plan: Task 3;
  - the mapping rules and the "last reported month in fiscal order": Task 4;
  - burndown, EAC and the edge-week clamp: Task 5;
  - monthly, costs, budget and plots: Tasks 5 and 6;
  - `Snapshot`, `what_if` and scenario: Task 7;
  - CLI, TUI, init, scaffold, emails and docs: Tasks 2, 4, 5 and 8;
  - perch money, rate, join, cut, watch and accuracy: Task 9;
  - quarterly and report_mail: Task 10.
- **Spec coverage, tests.**
  - The spec's perch test "calibrate counts an issue closed 2026-12-15 inside FY27" is in Task 9.
  - "quarterly on the FY27 world gives FY27 Q1" is in Task 10. It uses a minimal `Money` rather than a full on-disk world, because perch's conftest world is calendar-2026.
  - "`year_start` errors naming the key" is in Task 1.
- **Placeholder scan.** Every code step has code. The mechanical edits name the command, the rule and the expected count.
- **Type consistency.** Every task uses the same names: `year_span(year, year_start)`, `YearSpan.first/.last/.year/.label/.fiscal/.days/.zero/.months/.quarters/.contains`, `current_year(year_start, today)`, `year_start_month(text)`, `federal_holidays(span)`. Every converted function takes `span` in the position `year` held.
- **Review Focus.** All five lines have tests: (1) Task 4, (2) Task 1, (3) Task 5, (4) Tasks 1 and 8, (5) Task 3.

## Spec deviations and gaps (for the reviewer)

1. **`year_start` is `MM-01`, not any `MM-DD`.** The spec says `MM-DD` and gives `02-30` as the example of a bad day, but months, monthly buckets, the month-number rule and quarters all assume the year starts on a month's first day. A `10-15` start would split October across two years. The plan refuses anything but `MM-01` with an error naming the key, which also covers `02-29`.
2. **The default year outside a project stays 2026.** The spec says the CLI falls back to "the year containing today". The bundled sample files are dated 2026, so that fallback would make sample runs wrong from January 2027, and every CLI test without a workspace would depend on the date. The plan therefore uses the year containing today only inside a project, and `SAMPLE_YEAR = 2026` outside one.
3. **The year's printed form.** The spec doesn't say how titles, emails and logs print the year. The plan adds `YearSpan.label` (`2026` / `FY27`), and emails keep a `year` label parameter (`int | str`) instead of taking a span.
4. **The quarterly heading.** The spec shows `FY27 Q1 (Oct 1 – Dec 31, 2026)`. The existing report prints `q.name` in `title()` and `"{name} runs Oct 1 – Dec 31"` in its opening, so the plan keeps that format with the name `FY27-Q1`. That name matches `--quarter` and round-trips through it. If the exact spec wording is wanted, change `title()` / `_opening()` in Task 10.
5. **Quarters live in Budgie.** The spec says perch cuts the span into four. The plan adds `YearSpan.quarters` in Budgie, so perch does no month arithmetic at all, in line with the spec's "perch does no fiscal arithmetic".
6. **Scenarios.** `scenario.py`'s default year of 2026 is replaced by an error naming the scenario, plus an optional top-level or per-scenario `year_start`. The spec only says the default "goes away".
