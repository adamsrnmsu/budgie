from datetime import date

from budgie.burn_chart import BUDGET, FAN, LABEL, PLAN, SPENT, render
from budgie.core.burn import BurnSeries
from budgie.core.csvio import last_day_of_month
from budgie.core.scaffold import init_workspace
from budgie.core.workspace import forget_workspaces
from budgie.tui import BudgieTUI

MONTHS = tuple(last_day_of_month(2026, m) for m in range(1, 13))


def series(**kw) -> BurnSeries:
    base = dict(
        months=MONTHS,
        spent=tuple(float(i * 10_000) if i < 6 else None for i in range(12)),
        spent_as_of=(date(2026, 6, 30), 50_000.0),
        plan=tuple(float(i * 10_000) for i in range(12)),
        budget=(100_000.0,) * 12,
        p10=tuple(float(i * 8_000) for i in range(12)),
        p50=tuple(float(i * 9_000) for i in range(12)),
        p90=tuple(float(i * 10_000 + 10_000) for i in range(12)),
        reading_dates=(date(2026, 6, 30),),
        as_of=date(2026, 6, 30),
    )
    return BurnSeries(**{**base, **kw})


def test_known_points_land_in_their_cells():
    lines = render(series(), 80, 12)
    assert len(lines) == 12
    plot = [ln[LABEL:] for ln in lines[:10]]
    # budget is the flat top line (max value 120k is the fan's P90, so 100k is just below)
    assert BUDGET in plot[1] and BUDGET * 20 in plot[1]
    # last month's plan (110k) sits at the right edge, in the top rows
    assert plot[0][-1] in (FAN, PLAN) or plot[1][-1] == BUDGET
    # spent stops at the latest reading: bottom row filled to ~half, empty after
    bottom = plot[-1]
    assert bottom[0] == SPENT or bottom[0] == PLAN
    assert SPENT in bottom and bottom[-1] != SPENT
    assert FAN in "".join(plot)
    assert lines[0].lstrip().startswith("$")  # top tick, in $k
    assert lines[-2].count("J") >= 1  # month axis
    assert SPENT in lines[-1] and "P10-P90" in lines[-1]  # legend


def test_no_fan_no_budget_no_readings_do_not_crash():
    s = series(p10=(), p50=(), p90=(), budget=(None,) * 12)
    lines = render(s, 40, 9)
    assert "P10-P90" not in lines[-1] and len(lines) == 9
    empty = series(
        spent=(None,) * 12,
        spent_as_of=None,
        plan=(None,) * 12,
        budget=(None,) * 12,
        p10=(),
        p50=(),
        p90=(),
        reading_dates=(),
        as_of=None,
        note="no hours readings yet",
    )
    assert render(empty, 80, 9)[0] == "no burn to draw yet"


def test_narrow_width_is_clamped_to_40():
    assert all(len(ln) <= 40 for ln in render(series(), 10, 8))


async def _chart_text(tmp_path, monkeypatch, size):
    init_workspace(tmp_path, year=2026)
    monkeypatch.chdir(tmp_path)
    forget_workspaces()
    app = BudgieTUI()
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        chart = app.query_one("#burn_chart")
        return str(chart.render())


async def test_forecast_tab_draws_burn_chart_80(tmp_path, monkeypatch):
    text = await _chart_text(tmp_path, monkeypatch, (80, 24))
    assert "spent" in text and "budget" in text


async def test_forecast_tab_draws_burn_chart_120(tmp_path, monkeypatch):
    text = await _chart_text(tmp_path, monkeypatch, (120, 40))
    assert "spent" in text
