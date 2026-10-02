from datetime import date

import pytest

from budgie.core.calendar import productive_hours, year_span
from budgie.core.monthly import (
    cumulative,
    load_monthly_actuals,
    month_weights,
    monthly_available_hours,
    monthly_forecast,
    monthly_simulation,
    spent_at,
    workdays_in_month,
)
from budgie.core.person import HoursEstimate, Person


def _team():
    return [
        Person("A", 100, HoursEstimate(900, 1000, 1100)),
        Person("B", 50, HoursEstimate(1800, 1900, 2000)),
    ]


def test_workdays_exclude_weekends_and_holidays():
    # July 2026 has 23 weekdays; July 3 (observed Independence Day) removes one.
    assert workdays_in_month(2026, 7) == 22
    # Months are never longer than 23 working days.
    assert all(17 <= workdays_in_month(2026, m) <= 23 for m in range(1, 13))


def test_weights_sum_to_one_and_vary():
    w = month_weights(year_span(2026))
    assert len(w) == 12
    assert sum(w) == pytest.approx(1.0)
    # February is shorter than March -- an even 1/12 split would be wrong.
    assert w[1] < w[2]


def test_monthly_hours_reconcile_to_annual():
    annual = productive_hours(year_span(2026)).available_hours
    months = monthly_available_hours(year_span(2026))
    assert sum(months) == pytest.approx(annual)


def test_monthly_forecast_reconciles_to_annual_total():
    people = _team()
    mf = monthly_forecast(people, year_span(2026))
    expected = sum(p.expected_cost() for p in people)
    assert mf.total_cost == pytest.approx(expected)
    assert mf.cumulative_costs[-1] == pytest.approx(expected)
    assert len(mf.costs) == 12


def test_simulation_bands_widen_and_are_ordered():
    sim = monthly_simulation(_team(), year_span(2026), iterations=4000, seed=7)
    p10, p50, p90 = sim.band(10), sim.band(50), sim.band(90)
    assert len(p50) == 12
    # Ordered at every month.
    assert all(a <= b <= c for a, b, c in zip(p10, p50, p90))
    # Cumulative, so each month is at least the previous.
    assert all(p50[i] <= p50[i + 1] for i in range(11))
    # The band widens as the year progresses.
    assert (p90[-1] - p10[-1]) > (p90[0] - p10[0])


def test_simulation_requires_people():
    with pytest.raises(ValueError):
        monthly_simulation([], year_span(2026), iterations=10)


def test_cumulative_helper():
    assert cumulative([1, 2, 3]) == [1, 3, 6]


def test_load_monthly_actuals(tmp_path):
    csv = tmp_path / "a.csv"
    csv.write_text("name,month,hours\nAlice,1,10\nAlice,3,5\nBob,2,7\n")
    actuals = load_monthly_actuals(csv)
    assert actuals["Alice"][0] == 10
    assert actuals["Alice"][1] == 0  # missing months are zero
    assert actuals["Alice"][2] == 5
    assert len(actuals["Bob"]) == 12
    assert cumulative(actuals["Alice"])[2] == 15


def test_load_monthly_actuals_rejects_bad_month(tmp_path):
    csv = tmp_path / "a.csv"
    csv.write_text("name,month,hours\nAlice,13,10\n")
    with pytest.raises(ValueError):
        load_monthly_actuals(csv)


def test_load_monthly_actuals_requires_columns(tmp_path):
    csv = tmp_path / "a.csv"
    csv.write_text("name,hours\nAlice,10\n")
    with pytest.raises(ValueError):
        load_monthly_actuals(csv)


# --- actuals: book the past, fan out only the rest (budgie-dhi) ------------


from budgie.core.calendar import workdays_between
from budgie.core.monthly import Actuals
from budgie.core.plan import AllocationPlan, PlanEntry

# $100/h, 1,000 h at completion of which 400 are booked by Jun 30 (100 by Mar 31).
_ALICE = Person("Alice", 100, HoursEstimate.constant(1000))
_SERIES = [(date(2026, 3, 31), 100.0), (date(2026, 6, 30), 400.0)]


def _actuals(plan=None):
    return Actuals({"Alice": _SERIES[-1]}, {"Alice": _SERIES}, plan)


def test_past_months_book_real_hours_and_the_rest_is_spread_by_working_days():
    mf = monthly_forecast([_ALICE], year_span(2026), actuals=_actuals())
    cum = mf.cumulative_costs
    assert cum[2] == pytest.approx(100 * 100)  # Mar 31 reading
    assert cum[5] == pytest.approx(400 * 100)  # Jun 30 reading
    # Apr/May are interpolated between the two readings (Apr 30 is 30 of 91 days).
    assert cum[3] == pytest.approx(100 * (100 + 300 * 30 / 91))
    # 600 h remain; July holds 22 of the 126 working days left.
    assert workdays_between(date(2026, 7, 1), date(2026, 12, 31)) == 126
    assert cum[6] == pytest.approx(100 * (400 + 600 * 22 / 126))
    assert cum[11] == pytest.approx(100 * 1000)
    assert sum(mf.hours) == pytest.approx(1000)


def test_simulation_has_no_spread_before_the_reading():
    sim = monthly_simulation(
        [_ALICE], year_span(2026), iterations=50, seed=1, actuals=_actuals()
    )
    assert sim.band(10)[5] == sim.band(90)[5] == pytest.approx(40_000)
    assert sim.band(50)[11] == pytest.approx(100_000)


def test_remaining_hours_follow_the_plan_when_it_ends_early():
    # Plan stops on Sep 1, so everything left must land by the end of August.
    plan = AllocationPlan(
        (
            PlanEntry("Alice", date(2026, 1, 1), 1.0),
            PlanEntry("Alice", date(2026, 9, 1), 0.0),
        )
    )
    cum = monthly_forecast(
        [_ALICE], year_span(2026), actuals=_actuals(plan)
    ).cumulative_costs
    assert cum[7] == pytest.approx(100_000)  # Aug
    assert cum[8] == pytest.approx(cum[7])  # nothing new in Sep+


def test_no_actuals_is_unchanged():
    assert monthly_forecast(_team(), year_span(2026), actuals=None) == monthly_forecast(
        _team(), year_span(2026)
    )


def test_monthly_cli_books_actuals_only_when_given():
    from pathlib import Path

    from click.testing import CliRunner

    from budgie.budgie import cli

    here = Path(__file__).parent
    args = ["monthly", "--people", str(here / "team.csv"), "--seed", "1"]
    plain = CliRunner().invoke(cli, args)
    booked = CliRunner().invoke(cli, [*args, "--actuals", str(here / "actuals.csv")])
    assert plain.exit_code == 0 and booked.exit_code == 0, booked.output
    assert "Estimate at completion" not in plain.output
    assert "Estimate at completion" in booked.output


def test_spent_at_is_linear_from_dec_31_and_flat_after_the_last_reading():
    series = [(date(2026, 1, 31), 310.0), (date(2026, 3, 2), 400.0)]  # 31 days, then 30
    assert spent_at(series, date(2025, 12, 31), year_span(2026)) == 0.0
    assert spent_at(series, date(2026, 1, 11), year_span(2026)) == pytest.approx(110.0)
    assert spent_at(series, date(2026, 2, 15), year_span(2026)) == pytest.approx(
        355.0
    )  # 14 of 30 days
    assert spent_at(series, date(2026, 6, 1), year_span(2026)) == 400.0
