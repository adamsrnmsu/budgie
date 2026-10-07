"""budgie doctor: read only; exit 1 only on a fail."""

from datetime import date

import pytest
from click.testing import CliRunner

from budgie.budgie import cli
from budgie.core import doctor as dr
from budgie.core.scaffold import init_workspace
from budgie.core.workspace import forget_workspaces, load_workspace


@pytest.fixture(autouse=True)
def _clear():
    forget_workspaces()
    yield
    forget_workspaces()


@pytest.fixture
def project(tmp_path):
    init_workspace(tmp_path, year=2026)
    return tmp_path


def run(project, *args):
    return CliRunner().invoke(cli, ["doctor", *args], catch_exceptions=False)


def checks(project):
    return dr.project_checks(load_workspace(project / "budgie.yaml"), date(2026, 6, 15))


def by(cs, text):
    return [c for c in cs if text in c.what]


def test_environment_warns_not_fails(tmp_path):
    cs = dr.environment_checks(env={}, prefix=str(tmp_path))
    assert by(cs, "is not")[0].status == dr.WARN
    assert by(cs, "$EDITOR")[0].status == dr.WARN
    assert by(cs, "$EDITOR")[0].fix
    assert dr.environment_checks(env={"EDITOR": "vi"})[-1].status == dr.OK


def test_hidden_pth_warns_with_chflags(tmp_path, monkeypatch):
    pth = tmp_path / "__editable__.budgie.pth"
    pth.write_text("x")
    monkeypatch.setattr(dr.site, "getsitepackages", lambda: [str(tmp_path)])
    monkeypatch.setattr(dr, "_hidden", lambda p: True)
    c = by(dr.environment_checks(env={"EDITOR": "x"}), "hidden")[0]
    assert c.status == dr.WARN and c.fix == f"chflags nohidden {pth}"


def test_no_project_is_one_sample_warn(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = run(tmp_path)
    assert r.exit_code == 0
    assert "budgie init NAME" in r.output


def test_several_projects_listed_not_picked(tmp_path, monkeypatch):
    for n in ("a", "b"):
        init_workspace(tmp_path / "budget" / n, year=2026)
    monkeypatch.chdir(tmp_path)
    r = run(tmp_path)
    assert "several projects (a, b)" in r.output
    assert "plan.csv loads" not in r.output


def test_unknown_project_name_fails(project, monkeypatch):
    monkeypatch.chdir(project)
    r = run(project, "--project", "nope")
    assert r.exit_code == 1 and "no project called nope" in r.output


def test_fresh_init_has_no_budget_or_reading_source_warning(project):
    assert not (project / "actuals.csv").exists()
    cs = checks(project)
    assert not by(cs, "pinned")
    assert not by(cs, "weekly wins")


def test_pinned_budget_beats_csv(project):
    with (project / "budgie.yaml").open("a") as f:
        f.write("budget: 500000\n")
    c = by(checks(project), "pinned")[0]
    assert c.status == dr.WARN
    assert "500,000" in c.what and "budget.csv (425,000)" in c.what


def test_bad_input_fails_with_one_line(project, monkeypatch):
    (project / "people.csv").write_text("nonsense\n1\n")
    monkeypatch.chdir(project)
    r = run(project)
    assert r.exit_code == 1 and "people.csv:" in r.output
    assert "fix: edit" in r.output


def test_bad_budget_names_the_file_once(project):
    (project / "budget.csv").write_text("nonsense\n1\n")
    c = by(checks(project), "budget.csv")[0]
    assert c.status == dr.FAIL and c.what.startswith("budget.csv")
    assert "budget.csv: budget.csv" not in c.what


def test_plan_name_missing_from_people_fails(project):
    with (project / "plan.csv").open("a") as f:
        f.write("Zed,2026-01-01,0.5\n")
    c = by(checks(project), "not in people.csv")[0]
    assert c.status == dr.FAIL and "Zed" in c.what


def test_weekly_and_actuals_and_staleness(project):
    (project / "actuals.csv").write_text("name,month,hours\nAlice,1,10\n")
    (project / "weekly.csv").write_text("name,week,hours_to_date\nAlice,10,100\n")
    cs = checks(project)
    assert by(cs, "weekly wins")[0].status == dr.WARN
    stale = by(cs, "weekly reading")[0]
    assert stale.status == dr.WARN and "this week's reading" in stale.fix


def test_plan_gap_months_warn(project):
    (project / "plan.csv").write_text(
        "name,effective_date,fte\nAlice,2026-01-01,0.9\nAlice,2026-07-01,0\n"
        "Bob,2026-01-01,0.5\nBob,2026-07-01,0\n"
    )
    c = by(checks(project), "allocates nobody")[0]
    assert c.status == dr.WARN and "2026-07" in c.what and "2026-06" not in c.what


def test_writes_nothing(project, monkeypatch):
    monkeypatch.chdir(project)
    before = {p: p.stat().st_mtime_ns for p in project.rglob("*") if p.is_file()}
    run(project)
    after = {p: p.stat().st_mtime_ns for p in project.rglob("*") if p.is_file()}
    assert before == after
