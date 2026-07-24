import pytest

from budgie.core.calendar import productive_hours
from budgie.core.monthly import (
    cumulative,
    load_monthly_actuals,
    month_weights,
    monthly_available_hours,
    monthly_forecast,
    monthly_simulation,
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
    w = month_weights(2026)
    assert len(w) == 12
    assert sum(w) == pytest.approx(1.0)
    # February is shorter than March -- an even 1/12 split would be wrong.
    assert w[1] < w[2]


def test_monthly_hours_reconcile_to_annual():
    annual = productive_hours(2026).available_hours
    months = monthly_available_hours(2026)
    assert sum(months) == pytest.approx(annual)


def test_monthly_forecast_reconciles_to_annual_total():
    people = _team()
    mf = monthly_forecast(people, 2026)
    expected = sum(p.expected_cost() for p in people)
    assert mf.total_cost == pytest.approx(expected)
    assert mf.cumulative_costs[-1] == pytest.approx(expected)
    assert len(mf.costs) == 12


def test_simulation_bands_widen_and_are_ordered():
    sim = monthly_simulation(_team(), 2026, iterations=4000, seed=7)
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
        monthly_simulation([], 2026, iterations=10)


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
