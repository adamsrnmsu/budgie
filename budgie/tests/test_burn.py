"""burn_series: the monthly chart series, in labor dollars (the conftest world of perch)."""

from datetime import date

import pytest

from budgie.core.burn import BurnSeries, burn_series
from budgie.core.project import load_snapshot


def week(n: int) -> date:
    return date.fromisocalendar(2026, n, 7)


def _write(path):
    (path / "budgie.yaml").write_text("year: 2026\nbudget: 100000\nseed: 1\n")
    (path / "people.csv").write_text(
        "name,hourly_cost,hours_low,hours_mode,hours_high\n"
        "Alice,100,900,1000,1100\nBob,50,900,1000,1100\n"
    )
    (path / "allocations.csv").write_text(
        "name,fte,hours_spent\nAlice,0.5,0\nBob,0.5,0\n"
    )
    (path / "weekly.csv").write_text(
        "name,week,hours_to_date\n"
        "Alice,4,40\nAlice,8,100\nAlice,12,160\nAlice,16,200\nBob,8,80\nBob,16,120\n"
    )
    (path / "costs.csv").write_text(
        "name,category,date,amount,low,high,recurring\n"
        "Laptops,materials,2026-03-15,5000,,,no\n"
    )


@pytest.fixture
def snap(tmp_path):
    _write(tmp_path)
    return load_snapshot(tmp_path)


def test_months_and_readings(snap):
    b = burn_series(snap)
    assert isinstance(b, BurnSeries)
    assert len(b.months) == 12
    assert (b.months[0], b.months[-1]) == (date(2026, 1, 31), date(2026, 12, 31))
    assert b.as_of == week(16) == date(2026, 4, 19)
    assert b.reading_dates == (week(4), week(8), week(12), week(16))


def test_spent_is_booked_dollars_through_as_of_then_none(snap):
    b = burn_series(snap)
    assert b.spent_as_of == (date(2026, 4, 19), 26000.0)  # 200 h x 100 + 120 h x 50
    # 01-31: Alice 40 + 60 x 6/28 = 52.857 h; Bob 80 x 31/53 = 46.792 h
    assert b.spent[0] == pytest.approx(7625.34, abs=0.01)
    # 02-28: 11,285.71 + 4,214.29
    assert b.spent[1] == pytest.approx(15500.0, abs=0.01)
    # 03-31: Alice 160 + 40 x 9/28 = 172.857 h; Bob 80 + 40 x 37/56 = 106.429 h
    assert b.spent[2] == pytest.approx(22607.14, abs=0.01)
    assert all(v is None for v in b.spent[3:])  # 04-30 is after as_of


def test_budget_is_the_labor_budget_every_month(snap):
    assert burn_series(snap).budget == (95000.0,) * 12  # 100,000 - 5,000 of cost lines


def test_plan_reaches_the_allocation_at_year_end_and_never_goes_flat(snap):
    b = burn_series(snap)
    # 996 h each at the end: Alice 99,600 + Bob 49,800. Before as_of is not flat after it.
    assert snap.planned_through("Alice", date(2026, 12, 31)) == pytest.approx(996)
    assert b.plan[-1] == pytest.approx(149400.0)
    assert all(b.plan[i] < b.plan[i + 1] for i in range(11))


def test_fan_is_ordered_and_booked_months_have_no_spread(snap):
    b = burn_series(snap)
    assert len(b.p10) == len(b.p50) == len(b.p90) == 12
    assert all(lo <= mid <= hi for lo, mid, hi in zip(b.p10, b.p50, b.p90, strict=True))
    for i in range(3):  # Jan to Mar are booked hours
        assert b.p10[i] == pytest.approx(b.p90[i])
    assert b.p50[-1] > 26000.0
    assert b.p90[-1] > b.p10[-1]  # the fan opens after as_of


def test_the_snapshot_method_is_the_function(snap):
    assert snap.burn_series() == burn_series(snap)


def test_no_readings_gives_a_note_and_no_fan(tmp_path):  # review-focus 1
    _write(tmp_path)
    (tmp_path / "weekly.csv").unlink()
    b = burn_series(load_snapshot(tmp_path))
    assert b.as_of is None and b.spent_as_of is None and b.reading_dates == ()
    assert all(v is None for v in b.spent)
    assert b.p10 == b.p50 == b.p90 == ()
    assert b.note == "no hours readings yet"
    assert b.budget == (95000.0,) * 12  # the budget and plan still draw
