from datetime import date
from pathlib import Path

import pytest

from budgie.core.actuals import (
    load_weekly_actuals,
    monthly_to_observations,
    week_ending,
)
from budgie.core.allocation import Allocation
from budgie.core.burndown import burndown
from budgie.core.calendar import (
    hours_per_workday,
    workdays_between,
    workdays_in_year,
    year_span,
)
from budgie.core.plan import load_plan

TESTS_DIR = Path(__file__).resolve().parent


# --- calendar day helpers -------------------------------------------------


def test_workdays_between_excludes_weekend_and_holiday():
    # Jul 1-7 2026: Jul 4 is a Saturday, observed Friday Jul 3.
    assert workdays_between(date(2026, 7, 1), date(2026, 7, 7)) == 4
    assert workdays_between(date(2026, 7, 7), date(2026, 7, 1)) == 0  # reversed


def test_hours_per_workday_reconciles_to_annual():
    assert workdays_in_year(year_span(2026)) == 250
    assert hours_per_workday(year_span(2026)) * 250 == pytest.approx(1992)


# --- allocation plan ------------------------------------------------------


def _plan_file(tmp_path, rows):
    path = tmp_path / "plan.csv"
    path.write_text("name,effective_date,fte\n" + "".join(f"{r}\n" for r in rows))
    return load_plan(path)


def test_full_year_allocation_matches_flat_model():
    plan = load_plan(TESTS_DIR / "plan.csv")
    # The sample team is at 0.90 FTE all year -> 0.9 * 1992.
    assert plan.allocated_hours("Alice", 2026) == pytest.approx(1793, abs=0.5)
    assert plan.names == ["Alice", "Bob", "Charlie", "David"]


def test_mid_year_join_is_charged_from_the_actual_day(tmp_path):
    plan = _plan_file(tmp_path, ["Carol,2026-07-15,0.50"])
    carol = plan.allocated_hours("Carol", 2026)
    # Joining Jul 15 at 0.5 must be well under a full year at 0.5 (996)...
    assert carol < 996 * 0.6
    # ...and under a Jul 1 start (502), since she misses two weeks of July.
    assert carol < 502
    assert carol == pytest.approx(466, abs=1.0)


def test_zeroing_someone_out_stops_accrual(tmp_path):
    plan = _plan_file(tmp_path, ["Bob,2026-01-01,0.50", "Bob,2026-09-01,0.00"])
    assert plan.fte_on("Bob", date(2026, 8, 31)) == 0.50
    assert plan.fte_on("Bob", date(2026, 9, 1)) == 0.0
    assert plan.fte_on("Bob", date(2026, 12, 31)) == 0.0
    # Eight months at 0.5 is less than a full year at 0.5.
    assert plan.allocated_hours("Bob", 2026) < 996


def test_replan_midyear_raises_allocation(tmp_path):
    plan = _plan_file(tmp_path, ["Dave,2026-01-01,0.25", "Dave,2026-04-01,0.75"])
    assert plan.fte_on("Dave", date(2026, 3, 31)) == 0.25
    assert plan.fte_on("Dave", date(2026, 4, 1)) == 0.75
    # Between a flat 0.25 (498) and a flat 0.75 (1494) year.
    assert 498 < plan.allocated_hours("Dave", 2026) < 1494


def test_before_first_entry_is_zero(tmp_path):
    plan = _plan_file(tmp_path, ["Carol,2026-07-15,0.50"])
    assert plan.fte_on("Carol", date(2026, 1, 1)) == 0.0
    assert plan.allocated_hours("Nobody", 2026) == 0.0


def test_plan_rejects_negative_fte(tmp_path):
    csv = tmp_path / "p.csv"
    csv.write_text("name,effective_date,fte\nA,2026-01-01,-0.5\n")
    with pytest.raises(ValueError):
        load_plan(csv)


def test_plan_requires_columns(tmp_path):
    csv = tmp_path / "p.csv"
    csv.write_text("name,fte\nA,0.5\n")
    with pytest.raises(ValueError):
        load_plan(csv)


# --- weekly cumulative actuals -------------------------------------------


def test_week_ending_is_the_sunday():
    d = week_ending(2026, 29)
    assert d.weekday() == 6  # Sunday
    assert d.year == 2026


def test_week_ending_rejects_impossible_week():
    with pytest.raises(ValueError):
        week_ending(2026, 99)


def test_load_weekly_actuals_sorted_and_cumulative():
    obs = load_weekly_actuals(TESTS_DIR / "weekly.csv", 2026)
    alice = obs["Alice"]
    assert [h for _, h in alice] == [430, 660, 990]
    assert alice[0][0] < alice[1][0] < alice[2][0]


def test_weekly_actuals_reject_decreasing_totals(tmp_path):
    csv = tmp_path / "w.csv"
    # Per-week values pasted where cumulative was expected.
    csv.write_text("name,week,hours_to_date\nA,10,50\nA,20,30\n")
    with pytest.raises(ValueError, match="cumulative"):
        load_weekly_actuals(csv, 2026)


def test_monthly_converts_to_cumulative_observations():
    obs = monthly_to_observations(2026, [10, 20, 30])
    assert [h for _, h in obs] == [10, 30, 60]
    assert obs[0][0] == date(2026, 1, 31)
    assert obs[-1][0] == date(2026, 3, 31)


# --- burndown driven by observations -------------------------------------


def test_latest_observation_drives_spent_and_as_of():
    alloc = Allocation(name="Alice", fte=0.25, hours_spent=0, available_hours=1992)
    obs = load_weekly_actuals(TESTS_DIR / "weekly.csv", 2026)["Alice"]
    st = burndown(alloc, 2026, observations=obs)
    # The dated reading wins over the allocation's undated scalar (0).
    assert st.hours_spent == 990
    # as_of defaults to the latest observation, not today.
    assert st.as_of == obs[-1][0]
    assert st.burn_rate_per_day > 0


def test_no_observations_falls_back_to_allocation_scalar():
    alloc = Allocation(name="Alice", fte=0.25, hours_spent=180, available_hours=1992)
    st = burndown(alloc, 2026, as_of=date(2026, 7, 23))
    assert st.hours_spent == 180
    assert st.observations == ()
