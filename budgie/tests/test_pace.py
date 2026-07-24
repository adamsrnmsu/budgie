"""Required-pace and per-person PTO tests."""

from datetime import date

import pytest

from budgie.core.allocation import Allocation, load_allocations
from budgie.core.burndown import burndown
from budgie.core.calendar import productive_hours, resolve_ceiling
from budgie.core.loader import load_people


def _alloc(fte=0.25, spent=0.0, available=1992.0):
    return Allocation(
        name="Alice", fte=fte, hours_spent=spent, available_hours=available
    )


def test_required_pace_converts_remaining_hours_to_a_weekly_rate():
    # 0.25 FTE of 1992 h = 498 h allocated; 180 spent leaves 318.
    status = burndown(_alloc(spent=180), 2026, as_of=date(2026, 6, 30))
    pace = status.required_pace

    assert pace.hours_remaining == pytest.approx(318)
    # Jul-Dec 2026: real working days, not 26 x 5.
    assert 120 < pace.workdays_remaining < 135
    assert pace.hours_per_week == pytest.approx(
        318 / (pace.workdays_remaining / 5), rel=1e-9
    )
    # ~12 h/week is a bit under a third of a full-time week.
    assert 0.25 < pace.fte < 0.35


def test_required_pace_matches_the_allocation_when_nothing_is_spent():
    # Spending nothing all year means the whole allocation is still ahead of
    # you, so the pace needed for the rest of the year is above the FTE you
    # were planned at.
    status = burndown(_alloc(fte=0.5, spent=0), 2026, as_of=date(2026, 6, 30))
    assert status.required_pace.fte > 0.5


def test_required_pace_is_zero_once_the_allocation_is_gone():
    status = burndown(_alloc(spent=600), 2026, as_of=date(2026, 6, 30))
    pace = status.required_pace

    assert pace.is_exhausted
    assert pace.hours_per_week == 0.0
    assert pace.fte == 0.0


def test_required_pace_flags_an_impossible_ask():
    # 1.0 FTE with nothing spent by December cannot be recovered.
    status = burndown(_alloc(fte=1.0, spent=0), 2026, as_of=date(2026, 12, 1))
    assert status.required_pace.is_impossible


def test_required_pace_runs_out_of_days_at_year_end():
    status = burndown(_alloc(spent=100), 2026, as_of=date(2026, 12, 31))
    pace = status.required_pace

    assert pace.workdays_remaining == 0
    assert pace.out_of_time
    assert pace.hours_per_week == 0.0


def test_per_person_pto_overrides_the_team_default(tmp_path):
    csv = tmp_path / "allocations.csv"
    csv.write_text(
        "name,fte,hours_spent,pto_days\n"
        "Alice,1.0,0,10\n"  # her own PTO
        "Bob,1.0,0,\n"  # blank -> team default
    )
    ph = productive_hours(2026, pto_days=20)
    alice, bob = load_allocations(csv, available_hours=ph)

    assert alice.available_hours == pytest.approx(1992 - 10 * 8)
    assert bob.available_hours == pytest.approx(1992 - 20 * 8)


def test_pto_is_prorated_by_fte_not_charged_in_full():
    # The whole point of item 13: a quarter-time person surrenders a quarter of
    # their PTO to this project, not all of it.
    ph = productive_hours(2026, pto_days=15)
    quarter_time = Allocation(
        name="Alice", fte=0.25, hours_spent=0, available_hours=ph.available_hours
    )

    assert quarter_time.allocated_hours == pytest.approx(0.25 * 1872)
    # Charging all 120 PTO hours to the project would give a smaller figure.
    assert quarter_time.allocated_hours > 0.25 * ph.productive_hours - ph.pto_hours


def test_people_csv_honours_a_per_person_pto_column(tmp_path):
    csv = tmp_path / "team.csv"
    csv.write_text(
        "name,hourly_cost,util_low,util_mode,util_high,pto_days\n"
        "Alice,100,0.9,0.9,0.9,0\n"
        "Bob,100,0.9,0.9,0.9,25\n"
    )
    ph = productive_hours(2026, pto_days=0)
    alice, bob = load_people(csv, productive_hours=ph)

    assert alice.hours.point > bob.hours.point
    assert bob.hours.point == pytest.approx(0.9 * (1992 - 25 * 8))


def test_a_plain_ceiling_rejects_a_per_person_pto_column():
    # A bare number has already had PTO subtracted, so a per-person figure
    # can't be resolved against it -- better to say so than to double-count.
    with pytest.raises(ValueError, match="ProductiveHours"):
        resolve_ceiling(1992.0, pto_days=10)


def test_plain_ceiling_still_works_without_per_person_pto():
    assert resolve_ceiling(1992.0, pto_days=None) == 1992.0
