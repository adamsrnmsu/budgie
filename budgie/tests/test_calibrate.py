"""budgie calibrate: the backtest, on hand-built projects."""

import json
from datetime import timedelta

import pytest
from click.testing import CliRunner

from budgie.budgie import cli
from budgie.core.calendar import year_span
from budgie.core.calibrate import calibrate
from budgie.core.plan import load_plan
from budgie.core.project import load_snapshot
from budgie.core.workspace import forget_workspaces

YAML = (
    "year: 2026\niterations: 1000\nseed: 7\n"
    "inputs:\n  people: people.csv\n  plan: plan.csv\n  weekly: weekly.csv\n"
)


@pytest.fixture(autouse=True)
def _clear():
    forget_workspaces()
    yield
    forget_workspaces()


def make(root, scale=1.0, weeks=None, plan_extra="", actual_plan=None):
    """One $100/h person, 1.0 FTE all year, +-5%.

    Weekly readings are ``scale`` x the hours ``actual_plan`` (default: the
    project's plan) has accrued by each week's Sunday.
    """
    weeks = range(4, 24) if weeks is None else weeks
    root.mkdir(parents=True, exist_ok=True)
    (root / "budgie.yaml").write_text(YAML)
    (root / "people.csv").write_text("name,hourly_cost,under,over\nAnn,100,5,5\n")
    (root / "plan.csv").write_text(
        "name,effective_date,fte\nAnn,2026-01-01,1.0\n" + plan_extra
    )
    plan = load_plan(root / "plan.csv")
    span = year_span(2026, "01-01")
    rows = ["name,week,hours_to_date"]
    for w in weeks:
        monday = span.first - timedelta(days=span.first.weekday())
        sunday = monday + timedelta(weeks=w - 1, days=6)
        hours = scale * plan.allocated_hours("Ann", span, 0.0, through=sunday)
        rows.append(f"Ann,{w},{hours:.4f}")
    (root / "weekly.csv").write_text("\n".join(rows) + "\n")
    return root


def run(root, **kw):
    return calibrate(load_snapshot(root), **kw)


def test_actuals_on_plan_sit_inside_the_band(tmp_path):
    cal = run(make(tmp_path / "p"))
    t = cal.total
    assert t.pairs == 20 * 19 // 2 and t.enough  # every (d, later t)
    assert t.inside == 1.0 and t.below == 0 and t.above == 0
    assert abs(t.median_error_pct) < 0.01
    assert all(s.enough for s in cal.horizons)


def test_spend_running_hot_lands_above_p90(tmp_path):
    t = run(make(tmp_path / "p", scale=1.3)).total
    assert t.above > 0.5 and t.below == 0
    assert t.median_error > 0


def test_few_readings_is_not_enough_history(tmp_path):
    cal = run(make(tmp_path / "p", weeks=range(4, 8)))  # 4 readings: 6 pairs
    assert cal.total.pairs == 6 and not cal.total.enough
    assert cal.total.inside is None and cal.total.median_error is None


def test_plan_rows_dated_after_the_forecast_are_not_used(tmp_path):
    # From April the plan halves, and the readings follow the halved plan. At
    # an early d the forecast only knows 1.0 FTE, so it expects more spend than
    # arrived: its P50 at a May target sits above the actual.
    root = make(tmp_path / "p", plan_extra="Ann,2026-04-01,0.5\n")
    early = [
        p
        for p in run(root).pairs
        if p.forecast_date.month < 3 and p.target_date.month >= 5
    ]
    assert early
    assert all(p.p50 > p.actual for p in early)


def test_target_beyond_someones_last_reading_is_skipped(tmp_path):
    root = make(tmp_path / "p")
    (root / "people.csv").write_text(
        "name,hourly_cost,under,over\nAnn,100,5,5\nBo,50,5,5\n"
    )
    (root / "plan.csv").write_text(
        (root / "plan.csv").read_text() + "Bo,2026-01-01,1.0\n"
    )
    (root / "weekly.csv").write_text(
        (root / "weekly.csv").read_text() + "Bo,4,100\nBo,5,200\n"
    )
    cal = run(root)
    # Bo stops after week 5: Ann's later readings are never a target.
    assert {p.target_date.isocalendar().week for p in cal.pairs} == {5}


def test_cli_text_and_blocks(tmp_path, monkeypatch):
    make(tmp_path / "p")
    monkeypatch.chdir(tmp_path)
    res = CliRunner().invoke(
        cli, ["calibrate", "--project", "p", "--iterations", "500"]
    )
    assert res.exit_code == 0, res.output
    assert "Inside" in res.output and "190" in res.output
    forget_workspaces()
    res = CliRunner().invoke(
        cli, ["calibrate", "--project", "p"], env={"PI_BLOCKS": "1"}
    )
    lines = [json.loads(x) for x in res.output.splitlines() if x.startswith("{")]
    assert {b["block"] for b in lines} >= {"figures", "table"}
