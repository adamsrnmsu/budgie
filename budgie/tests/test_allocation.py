import pytest

from budgie.core.allocation import Allocation, load_allocations
from budgie.emails import render_email


def test_fte_converts_to_hours():
    # 0.25 FTE against 1992 available hours = 498 allocated.
    a = Allocation(name="Alice", fte=0.25, hours_spent=180, available_hours=1992)
    assert a.allocated_hours == pytest.approx(498)
    assert a.hours_remaining == pytest.approx(318)
    assert a.fraction_used == pytest.approx(180 / 498)
    assert not a.is_over_budget


def test_over_budget_detected():
    a = Allocation(name="David", fte=0.10, hours_spent=205, available_hours=1992)
    assert a.hours_remaining < 0
    assert a.is_over_budget


def test_zero_allocation_has_no_division_error():
    a = Allocation(name="Ghost", fte=0.0, hours_spent=0, available_hours=1992)
    assert a.allocated_hours == 0
    assert a.fraction_used == 0.0


def test_load_allocations_requires_columns(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("name,fte\nAlice,0.5\n")  # missing hours_spent
    with pytest.raises(ValueError):
        load_allocations(bad, available_hours=1992)


def test_render_email_over_budget_has_warning():
    a = Allocation(
        name="David",
        fte=0.10,
        hours_spent=205,
        available_hours=1992,
        email="david@example.com",
    )
    draft = render_email(a, year=2026)
    assert draft.to == "david@example.com"
    assert "OVER your allocation" in draft.body
    assert "David" in draft.body
    assert "2026" in draft.subject
