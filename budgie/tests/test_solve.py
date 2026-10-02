from datetime import date

import pytest

from budgie.core.calendar import hours_per_workday, workdays_between
from budgie.core.plan import AllocationPlan, PlanEntry
from budgie.core.solve import PlanCosting, entries_for, solve

YEAR = 2026
PER_DAY = hours_per_workday(YEAR)  # 1992 h over 250 working days
H2 = list(range(7, 13))  # Jul..Dec


def _costing(*entries, as_of=None, spent=None, non_labor=0.0):
    plan = AllocationPlan(
        entries
        or (
            PlanEntry("Alice", date(YEAR, 1, 1), 1.0),
            PlanEntry("Bob", date(YEAR, 1, 1), 0.5),
        )
    )
    return PlanCosting(
        plan=plan,
        rates={"Alice": 100.0, "Bob": 50.0, "Carol": 80.0},
        year=YEAR,
        non_labor=non_labor,
        spent=spent or {},
        as_of=as_of,
    )


def _applied(costing, edits):
    return AllocationPlan(costing.plan.entries + tuple(entries_for(costing, edits)))


def test_cost_is_rate_times_plan_hours_plus_non_labor():
    c = _costing(non_labor=1000)
    assert c.cost() == pytest.approx(1992 * 100 + 996 * 50 + 1000)
    assert c.grid("Bob") == pytest.approx([0.5] * 12)


def test_one_person_hits_target_exactly():
    c = _costing()
    target = c.cost() - 20_000
    sol = solve(c, {("Bob", m) for m in H2}, target, mode="even")
    assert sol.gap == pytest.approx(0)
    assert c.cost(_applied(c, sol.fte)) == pytest.approx(target)
    # even: every month moves by the same amount
    assert len({round(v, 9) for v in sol.fte.values()}) == 1


def test_proportional_spread_scales_everyone_by_the_same_factor():
    c = _costing()
    target = c.cost() - 30_000
    cells = {(n, m) for n in ("Alice", "Bob") for m in H2}
    sol = solve(c, cells, target)
    assert c.cost(_applied(c, sol.fte)) == pytest.approx(target)
    assert sol.fte[("Alice", 7)] / 1.0 == pytest.approx(sol.fte[("Bob", 7)] / 0.5)


def test_cap_clamps_and_reports_the_gap_left():
    c = _costing()
    sol = solve(c, {("Bob", m) for m in H2}, c.cost() + 1e9)
    assert max(sol.fte.values()) == pytest.approx(1.0)
    assert sol.gap > 0
    assert c.cost(_applied(c, sol.fte)) + sol.gap == pytest.approx(c.cost() + 1e9)


def test_clamped_cells_hand_their_share_to_the_rest():
    c = _costing()
    # Alice is already at the cap, so only Bob can absorb an increase.
    cells = {(n, m) for n in ("Alice", "Bob") for m in H2}
    sol = solve(c, cells, c.cost() + 10_000)
    assert sol.gap == pytest.approx(0)
    assert sol.fte[("Alice", 7)] == pytest.approx(1.0)
    assert c.cost(_applied(c, sol.fte)) == pytest.approx(c.cost() + 10_000)


def test_proportional_says_why_zero_people_stayed_at_zero():
    c = _costing(
        PlanEntry("Alice", date(YEAR, 1, 1), 1.0),
        PlanEntry("Carol", date(YEAR, 1, 1), 0.0),
    )
    cells = {(n, m) for n in ("Alice", "Carol") for m in H2}
    sol = solve(c, cells, c.cost() + 10_000)
    assert sol.gap == pytest.approx(10_000)
    assert "even" in sol.note
    assert solve(c, cells, c.cost() + 10_000, mode="even").gap == pytest.approx(0)


def test_proportional_from_zero_falls_back_to_even():
    c = _costing(PlanEntry("Carol", date(YEAR, 1, 1), 0.0))
    sol = solve(c, {("Carol", m) for m in H2}, 50_000)
    assert sol.note
    assert c.cost(_applied(c, sol.fte)) == pytest.approx(50_000)


def test_past_months_are_locked_and_spent_replaces_them():
    c = _costing(as_of=date(YEAR, 3, 15), spent={"Alice": 100.0})
    assert not c.editable(2)
    assert c.editable(3)  # days left after the 15th
    with pytest.raises(ValueError):
        solve(c, {("Alice", 1)}, 0)
    # Alice's past is her 100 spent hours, not the plan's Jan 1 - Mar 15.
    future = c.cost() - (996 * 50)  # minus Bob's whole year
    assert future == pytest.approx(
        100 * 100
        + 100 * PER_DAY * workdays_between(date(YEAR, 3, 16), date(YEAR, 12, 31))
    )


def test_current_month_edit_starts_the_day_after_as_of():
    c = _costing(as_of=date(YEAR, 3, 15))
    (first, *_) = entries_for(c, {("Bob", 3): 0.0})
    assert first.effective_date == date(YEAR, 3, 16)


def test_committed_rows_cost_what_the_solver_said():
    # Month-by-month plans, a mid-year as_of and repeated values: every way
    # the rows can disagree with the solution shows up as a cost mismatch.
    ftes = [0.5, 0.5, 0.7, 0.7, 0.7, 0.2, 0.4, 0.4, 0.9, 0.9, 0.6, 0.6]
    entries = [
        PlanEntry(n, date(YEAR, m, 1), f * s)
        for n, s in (("Alice", 1.0), ("Bob", 0.8), ("Carol", 0.6))
        for m, f in enumerate(ftes, 1)
    ]
    c = _costing(*entries, as_of=date(YEAR, 6, 10))
    cells = {(n, m) for n in ("Alice", "Bob", "Carol") for m in range(6, 13)}
    for mode in ("proportional", "even"):
        sol = solve(c, cells, c.cost() - 25_000, mode=mode)
        assert c.cost(_applied(c, sol.fte)) == pytest.approx(sol.cost)


def test_equal_edits_in_a_row_still_beat_an_older_month_start_row():
    c = _costing(
        PlanEntry("Bob", date(YEAR, 1, 1), 0.5),
        PlanEntry("Bob", date(YEAR, 8, 1), 0.9),
    )
    plan = _applied(c, {("Bob", 7): 0.3, ("Bob", 8): 0.3})
    assert c.with_plan(plan).grid("Bob")[6:9] == pytest.approx([0.3, 0.3, 0.9])


def test_edit_overrides_an_older_mid_month_change():
    c = _costing(
        PlanEntry("Carol", date(YEAR, 1, 1), 0.2),
        PlanEntry("Carol", date(YEAR, 7, 15), 0.5),
    )
    plan = _applied(c, {("Carol", 7): 0.8})
    after = c.with_plan(plan)
    assert after.grid("Carol")[6] == pytest.approx(0.8)  # all of July
    assert after.grid("Carol")[7] == pytest.approx(0.5)  # August restored
    assert after.grid("Carol")[5] == pytest.approx(0.2)  # June untouched
