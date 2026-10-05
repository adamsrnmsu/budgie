"""Booked actuals and trailing averages, worked by hand.

Alice books 40 h every week, her week-N reading (the Sunday of ISO week N, 2026)
being 40*N. Week 1 ends Sun Jan 4, so the curve is 40 h over Jan 1-4 (10 h/day
from the zero point, Dec 31), then 40/7 h a day.
  Jan (ends Sat Jan 31): 160 at Sun Jan 25 + 6 days of 40/7 = 160 + 240/7.
  Feb (ends Sat Feb 28): 320 at Feb 22 + 240/7; so Feb booked = 160 exactly.
Bob has one reading, week 6 (Sun Feb 8): 240 h. Carol has none.
"""

import pytest

from budgie.core.booked import (
    completed_months,
    full_time_month_hours,
    full_time_week_hours,
    trailing_hours,
)
from budgie.core.project import load_snapshot
from budgie.core.scaffold import init_workspace
from budgie.core.workspace import forget_workspaces


@pytest.fixture(autouse=True)
def _clear_workspace_cache():
    forget_workspaces()
    yield
    forget_workspaces()


def snap_with(tmp_path, alice_weeks, bob=None):
    init_workspace(tmp_path, year=2026)
    rows = [f"Alice,{w},{40 * w}" for w in alice_weeks]
    rows += [f"Bob,{w},{h}" for w, h in (bob or [])]
    (tmp_path / "weekly.csv").write_text(
        "name,week,hours_to_date\n" + "\n".join(rows) + "\n"
    )
    return load_snapshot(tmp_path)


def test_jan_and_feb_are_complete_through_week_13(tmp_path):
    snap = snap_with(tmp_path, range(1, 14))
    months = completed_months(snap)["Alice"]
    assert months[0] == pytest.approx(160 + 240 / 7)
    assert months[1] == pytest.approx(160)
    assert months[2] is None  # Mar 31 is after the Mar 29 reading
    assert months[3:] == [None] * 9


def test_march_completes_once_a_reading_reaches_mar_31(tmp_path):
    snap = snap_with(tmp_path, range(1, 15))  # week 14 = Sun Apr 5
    months = completed_months(snap)["Alice"]
    assert months[2] is not None
    assert months[3] is None  # Apr 30 is after Apr 5
    # Mar: 40/week x 31 days / 7 = 177.14
    assert months[2] == pytest.approx(40 * 31 / 7)


def test_no_readings_means_nothing_complete(tmp_path):
    snap = snap_with(tmp_path, range(1, 14))
    assert completed_months(snap).get("Bob", [None] * 12) == [None] * 12
    assert trailing_hours(snap, 4).get("Bob") is None


def test_trailing_averages(tmp_path):
    snap = snap_with(tmp_path, range(1, 14))
    for w in (2, 4, 8):
        assert trailing_hours(snap, w)["Alice"] == pytest.approx(40)


def test_a_window_before_the_year_starts_is_none(tmp_path):
    # Bob's only reading is Feb 8: 4 weeks back is Jan 11 (fine), 8 is Dec 14.
    snap = snap_with(tmp_path, range(1, 14), bob=[(6, 240)])
    assert trailing_hours(snap, 4)["Bob"] is not None
    assert trailing_hours(snap, 8)["Bob"] is None


def test_trailing_average_follows_a_change_in_pace(tmp_path):
    # 40 a week to week 11 (440), then 20 a week to week 13 (480).
    init_workspace(tmp_path, year=2026)
    rows = [f"Alice,{w},{40 * w}" for w in range(1, 12)] + [
        "Alice,12,460",
        "Alice,13,480",
    ]
    (tmp_path / "weekly.csv").write_text(
        "name,week,hours_to_date\n" + "\n".join(rows) + "\n"
    )
    snap = load_snapshot(tmp_path)
    assert trailing_hours(snap, 2)["Alice"] == pytest.approx(20)
    assert trailing_hours(snap, 4)["Alice"] == pytest.approx((480 - 360) / 4)


def test_full_time_hours_match_budgies_own_year(tmp_path):
    snap = snap_with(tmp_path, [1])
    months = full_time_month_hours(snap)
    assert len(months) == 12
    assert sum(months) == pytest.approx(2080, rel=0.05)
    assert full_time_week_hours(snap) == pytest.approx(40, rel=0.05)
