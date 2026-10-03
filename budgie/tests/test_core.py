import numpy as np
import pytest

from budgie.core.calendar import (
    GROSS_ANNUAL_HOURS,
    federal_holiday_workdays,
    productive_hours,
    year_span,
)
from budgie.core.forecast import forecast
from budgie.core.montecarlo import simulate
from budgie.core.person import HoursEstimate, Person


def test_productive_hours_matches_definition():
    # 40 hrs/week x 52 - 11 federal holidays x 8 = 1992.
    ph = productive_hours(year_span(2026))
    assert ph.gross_hours == GROSS_ANNUAL_HOURS == 2080
    assert federal_holiday_workdays(year_span(2026)) == 11
    assert ph.productive_hours == 1992


def test_pto_reduces_available_hours():
    ph = productive_hours(year_span(2026), pto_days=15)
    assert ph.available_hours == ph.productive_hours - 15 * 8


def test_hours_estimate_rejects_bad_order():
    with pytest.raises(ValueError):
        HoursEstimate(low=100, mode=50, high=200)


def test_constant_estimate_samples_are_flat():
    est = HoursEstimate.constant(1800)
    samples = est.sample(np.random.default_rng(0), size=1000)
    assert np.all(samples == 1800)


def test_from_utilization_scales_ceiling():
    est = HoursEstimate.from_utilization(2000, 0.5, 0.75, 1.0)
    assert (est.low, est.mode, est.high) == (1000, 1500, 2000)


def test_deterministic_forecast_totals():
    team = [
        Person("A", 100, HoursEstimate.constant(1000)),
        Person("B", 50, HoursEstimate.constant(2000)),
    ]
    f = forecast(team)
    assert f.total_hours == 3000
    assert f.total_cost == 100 * 1000 + 50 * 2000


def test_montecarlo_is_seed_reproducible():
    team = [Person("A", 100, HoursEstimate(900, 1000, 1100))]
    a = simulate(team, iterations=5000, seed=7)
    b = simulate(team, iterations=5000, seed=7)
    np.testing.assert_array_equal(a.total_costs, b.total_costs)
    pct = a.percentiles()
    assert pct[10] < pct[50] < pct[90]


def test_simulate_requires_people():
    with pytest.raises(ValueError):
        simulate([], iterations=10)
