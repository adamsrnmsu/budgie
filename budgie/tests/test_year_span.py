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
