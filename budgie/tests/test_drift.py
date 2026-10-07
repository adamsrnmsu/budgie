"""since last week: the forecast at the previous reading vs the latest."""

from budgie.core.drift import drift_line, since_last_reading
from budgie.core.project import load_snapshot
from budgie.core.scaffold import init_workspace
from budgie.core.workspace import forget_workspaces
from budgie.tui import BudgieTUI


def _project(tmp_path, weekly):
    init_workspace(tmp_path, year=2026)
    first = (tmp_path / "people.csv").read_text().splitlines()[1].split(",")[0]
    rows = "\n".join(f"{first},{w},{h}" for w, h in weekly)
    (tmp_path / "weekly.csv").write_text(f"name,week,hours_to_date\n{rows}\n")
    return load_snapshot(tmp_path)


def test_two_readings_give_the_booked_difference_and_a_p50_move(tmp_path):
    snap = _project(tmp_path, [(10, 100), (11, 146)])
    d = since_last_reading(snap, 2000, 7)
    assert d.hours_booked == 46  # 146 - 100, one person, no "now minus 7 days"
    assert d.over_before is not None and 0 <= d.over_after <= 1
    assert since_last_reading(snap, 2000, 7) == d  # same seed: no MC noise
    line = drift_line(d)
    assert line.startswith("since last week: P50 ") and "46 h booked" in line
    assert "over budget" in line


def test_one_reading_gives_no_line(tmp_path):
    assert since_last_reading(_project(tmp_path, [(10, 100)]), 2000, 7) is None


async def test_tui_shows_the_line_only_with_two_readings(tmp_path, monkeypatch):
    for weekly, shown in (([(10, 100), (11, 146)], True), ([(10, 100)], False)):
        d = tmp_path / str(shown)
        _project(d, weekly)
        monkeypatch.chdir(d)
        forget_workspaces()
        app = BudgieTUI()
        async with app.run_test() as pilot:
            await pilot.pause()
            text = str(app.query_one("#forecast_headline").render())
            assert ("since last week:" in text) is shown
