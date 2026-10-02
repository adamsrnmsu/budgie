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

from budgie.core.actuals import (
    load_weekly_actuals,
    monthly_to_observations,
    week_ending,
)
from budgie.core.allocation import Allocation
from budgie.core.budget import Budget, BudgetRevision
from budgie.core.burndown import burndown
from budgie.core.calendar import (
    YearSpan,
    current_year,
    federal_holiday_workdays,
    hours_per_workday,
    productive_hours,
    workdays_in_year,
    year_span,
    year_start_month,
)
from budgie.core.costs import CostItem, monthly_totals
from budgie.core.eac import elapsed_fraction
from budgie.core.monthly import (
    month_names,
    month_weights,
    monthly_available_hours,
    spent_at,
)
from budgie.core.plan import AllocationPlan, PlanEntry
from budgie.core.workspace import load_workspace

FY27 = year_span(2027, "10-01")
CAL26 = year_span(2026)


def test_a_calendar_span_is_the_calendar_year():
    assert CAL26 == YearSpan(date(2026, 1, 1), date(2026, 12, 31))
    assert (CAL26.year, CAL26.label, CAL26.fiscal, CAL26.days) == (
        2026,
        "2026",
        False,
        365,
    )
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


def test_fy27_counts_holidays_from_both_calendar_years():
    assert federal_holiday_workdays(FY27) == 11
    assert federal_holiday_workdays(year_span(2027)) == 12  # Dec 31 2027: FY28
    assert workdays_in_year(FY27) == 250


def test_fy27_productive_hours():
    ph = productive_hours(FY27)
    assert ph.span == FY27
    assert (ph.holiday_hours, ph.productive_hours) == (88.0, 1992.0)
    assert hours_per_workday(FY27) == pytest.approx(7.968)


def test_a_plan_row_before_the_span_is_in_force_for_all_of_it():
    plan = AllocationPlan((PlanEntry("Ann", date(2026, 1, 1), 0.5),))
    assert plan.allocated_hours("Ann", FY27) == pytest.approx(996.0)  # 0.5 x 1992


def test_a_mid_year_join_counts_from_its_own_day():
    plan = AllocationPlan((PlanEntry("Ben", date(2027, 4, 1), 1.0),))
    assert plan.allocated_hours("Ben", FY27) == pytest.approx(1011.936)  # 127 x 7.968


def test_fraction_through_and_last_planned_day_follow_the_span():
    plan = AllocationPlan(
        (
            PlanEntry("Cy", date(2026, 10, 1), 1.0),
            PlanEntry("Cy", date(2027, 3, 1), 0.0),
        )
    )
    assert plan.last_planned_day("Cy", FY27) == date(2027, 2, 26)  # a Friday
    full = AllocationPlan((PlanEntry("Di", date(2026, 10, 1), 1.0),))
    assert full.fraction_through("Di", FY27, date(2026, 12, 31)) == pytest.approx(0.248)
    assert full.team_hours(FY27) == {"Di": pytest.approx(1992.0)}


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
        (
            BudgetRevision(date(2026, 10, 1), 1000.0),
            BudgetRevision(date(2027, 4, 1), 1200.0),
        )
    )
    assert budget.monthly_amounts(FY27) == [1000.0] * 6 + [1200.0] * 6
