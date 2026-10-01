from datetime import date
from pathlib import Path

import numpy as np
import pytest

from budgie.core.budget import Budget, coerce_budget, load_budget
from budgie.core.costs import (
    CostItem,
    by_category,
    load_costs,
    monthly_totals,
    sample_total,
    total_cost,
)
from budgie.core.forecast import forecast
from budgie.core.montecarlo import simulate
from budgie.core.person import HoursEstimate, Person

TESTS_DIR = Path(__file__).resolve().parent


def _one_off(amount=1000, month=3, **kw):
    return CostItem(name="X", amount=amount, when=date(2026, month, 15), **kw)


# --- non-labor costs ------------------------------------------------------


def test_one_off_totals_once():
    item = _one_off(12000)
    assert item.months_charged == 1
    assert item.total == 12000


def test_recurring_charges_from_its_month_to_december():
    item = CostItem(name="Cloud", amount=2000, when=date(2026, 1, 1), recurring=True)
    assert item.months_charged == 12
    assert item.total == 24000
    # Starting in October only charges Oct-Dec.
    q4 = CostItem(name="Cloud", amount=2000, when=date(2026, 10, 1), recurring=True)
    assert q4.months_charged == 3
    assert q4.total == 6000


def test_rejects_inconsistent_range():
    with pytest.raises(ValueError):
        _one_off(1000, low=2000, high=3000)  # amount below low


def test_rejects_negative_amount():
    with pytest.raises(ValueError):
        _one_off(-5)


def test_certain_item_samples_flat():
    draws = _one_off(1000).sample(np.random.default_rng(0), 100)
    assert np.all(draws == 1000)


def test_uncertain_item_samples_within_range():
    item = _one_off(1000, low=800, high=1500)
    draws = item.sample(np.random.default_rng(0), 2000)
    assert draws.min() >= 800
    assert draws.max() <= 1500


def test_monthly_totals_place_costs_in_the_right_month():
    items = [
        _one_off(1000, month=3),
        CostItem(name="Sub", amount=100, when=date(2026, 11, 1), recurring=True),
    ]
    months = monthly_totals(items, 2026)
    assert months[2] == 1000  # March
    assert months[10] == 100  # Nov
    assert months[11] == 100  # Dec
    assert months[0] == 0
    assert sum(months) == total_cost(items)


def test_costs_from_another_year_are_ignored():
    items = [CostItem(name="Old", amount=500, when=date(2025, 3, 1))]
    assert sum(monthly_totals(items, 2026)) == 0


def test_load_costs_and_categories():
    items = load_costs(TESTS_DIR / "costs_items.csv")
    assert len(items) == 5
    cats = by_category(items)
    assert cats["materials"] == 40000
    assert cats["services"] == 33500  # 24000 recurring + 9500 one-off
    assert total_cost(items) == 81500


def test_load_costs_requires_columns(tmp_path):
    csv = tmp_path / "c.csv"
    csv.write_text("name,amount\nX,10\n")
    with pytest.raises(ValueError):
        load_costs(csv)


# --- integration with forecast and Monte Carlo ---------------------------


def _team():
    return [Person("A", 100, HoursEstimate.constant(1000))]


def test_forecast_separates_labor_from_non_labor():
    costs = [_one_off(5000)]
    f = forecast(_team(), costs=costs)
    assert f.labor_cost == 100_000
    assert f.non_labor_cost == 5000
    assert f.total_cost == 105_000


def test_costs_shift_the_simulated_distribution():
    without = simulate(_team(), iterations=3000, seed=3)
    with_costs = simulate(_team(), iterations=3000, seed=3, costs=[_one_off(5000)])
    assert with_costs.mean == pytest.approx(without.mean + 5000)


def test_uncertain_costs_widen_the_distribution():
    certain = simulate(_team(), iterations=4000, seed=3, costs=[_one_off(5000)])
    uncertain = simulate(
        _team(), iterations=4000, seed=3, costs=[_one_off(5000, low=1000, high=20000)]
    )
    assert uncertain.std > certain.std


def test_sample_total_sums_lines():
    items = [_one_off(1000), _one_off(2000)]
    draws = sample_total(items, np.random.default_rng(0), 50)
    assert np.all(draws == 3000)


# --- budget revisions -----------------------------------------------------


def test_flat_budget_has_no_revisions():
    b = Budget.flat(800000)
    assert b.original == b.latest == 800000
    assert not b.has_revisions
    assert b.net_change == 0


def test_revisions_apply_from_their_date():
    b = load_budget(TESTS_DIR / "budget.csv")
    assert b.original == 800000
    assert b.latest == 835000
    assert b.has_revisions
    assert b.net_change == 35000
    assert b.amount_on(date(2026, 4, 30)) == 800000
    assert b.amount_on(date(2026, 5, 1)) == 850000
    assert b.amount_on(date(2026, 9, 30)) == 850000
    assert b.amount_on(date(2026, 12, 31)) == 835000


def test_before_first_revision_uses_the_original():
    b = load_budget(TESTS_DIR / "budget.csv")
    # A budget set later still governs the earlier part of the year.
    assert b.amount_on(date(2020, 1, 1)) == 800000


def test_monthly_amounts_step():
    b = load_budget(TESTS_DIR / "budget.csv")
    months = b.monthly_amounts(2026)
    assert months[0] == 800000  # Jan
    assert months[4] == 850000  # May
    assert months[11] == 835000  # Dec


def test_coerce_accepts_number_list_and_path():
    assert coerce_budget(500).latest == 500
    assert coerce_budget(TESTS_DIR / "budget.csv").latest == 835000
    listed = coerce_budget(
        [{"date": "2026-01-01", "amount": 100}, {"date": "2026-06-01", "amount": 150}]
    )
    assert listed.original == 100
    assert listed.latest == 150


def test_budget_needs_at_least_one_revision():
    with pytest.raises(ValueError):
        Budget(())
