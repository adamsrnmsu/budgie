"""Input mistakes say which file and which line, and the CLI says it in one line."""

import pytest
from click.testing import CliRunner

from budgie.budgie import cli
from budgie.core.actuals import load_weekly_actuals
from budgie.core.allocation import load_allocations
from budgie.core.budget import load_budget
from budgie.core.calendar import productive_hours, year_span
from budgie.core.costs import load_costs
from budgie.core.csvio import read_rows
from budgie.core.loader import load_people
from budgie.core.plan import load_plan
from budgie.core.scaffold import init_workspace
from budgie.core.workspace import forget_workspaces

PH = productive_hours(year_span(2026))


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return path


# --- the file and the row ---------------------------------------------------


def test_a_bad_date_names_the_file_and_line(tmp_path):
    plan = _write(
        tmp_path,
        "plan.csv",
        "name,effective_date,fte\nAlice,2026-01-01,0.9\nBob,2026-13-01,0.5\n",
    )
    with pytest.raises(ValueError) as caught:
        load_plan(plan)
    assert str(caught.value) == (
        "plan.csv line 3: could not read '2026-13-01' as a date; "
        "use YYYY-MM-DD (e.g. 2026-03-15)"
    )


def test_a_bad_number_names_the_file_and_line(tmp_path):
    costs = _write(tmp_path, "costs.csv", "name,amount,date\nLaptops,12k,2026-02-01\n")
    with pytest.raises(
        ValueError, match=r"^costs\.csv line 2: amount: expected a number"
    ):
        load_costs(costs)


def test_budget_dates_name_the_file_and_line(tmp_path):
    budget = _write(
        tmp_path, "budget.csv", "effective_date,amount\n2026-01-01,1000\nsoon,2000\n"
    )
    with pytest.raises(ValueError, match=r"^budget\.csv line 3: could not read 'soon'"):
        load_budget(budget)


def test_a_missing_column_names_the_file(tmp_path):
    people = _write(tmp_path, "people.csv", "name,rate\nAlice,95\n")
    with pytest.raises(ValueError) as caught:
        load_people(people)
    assert str(caught.value) == "people.csv: missing column hourly_cost"


def test_missing_columns_are_listed(tmp_path):
    plan = _write(tmp_path, "plan.csv", "name\nAlice\n")
    with pytest.raises(ValueError) as caught:
        load_plan(plan)
    assert str(caught.value) == "plan.csv: missing columns effective_date, fte"


def test_line_numbers_count_physical_lines(tmp_path):
    # A quoted cell spanning two lines still leaves the next row on line 4.
    path = _write(tmp_path, "x.csv", 'name,note\nA,"two\nlines"\nB,x\n')
    rows = read_rows(path)
    assert [r.where for r in rows] == ["x.csv line 3", "x.csv line 4"]


def test_an_empty_people_file_says_so(tmp_path):
    people = _write(tmp_path, "people.csv", "name,hourly_cost\n")
    with pytest.raises(ValueError) as caught:
        load_people(people, productive_hours=PH)
    assert str(caught.value) == "people.csv has no people"


# --- absurd values are refused, with the file and the row -------------------


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            "name,hourly_cost\nAlice,95\nBob,-110\n",
            "people.csv line 3: hourly_cost cannot be negative, got -110",
        ),
        (
            "name,hourly_cost\nAlice,95\n,110\n",
            "people.csv line 3: name is blank",
        ),
        (
            "name,hourly_cost\nAlice,95\nBob,110\nalice,90\n",
            "people.csv line 4: alice is already on line 2; one row per person",
        ),
        (
            "name,hourly_cost,util_low,util_mode,util_high\nAlice,95,80,90,98\n",
            (
                "people.csv line 2: util_low must be 0 to 1, got 80 "
                "(looks like a percentage -- use 0.80 for 80%)"
            ),
        ),
        (
            "name,hourly_cost,util_low,util_mode,util_high\nAlice,95,-0.1,0.9,0.98\n",
            "people.csv line 2: util_low must be 0 to 1, got -0.1",
        ),
        (
            "name,hourly_cost,util_low,util_mode,util_high\nAlice,95,0.9,0.8,0.98\n",
            (
                "people.csv line 2: need util_low <= util_mode <= util_high, "
                "got 0.9, 0.8, 0.98"
            ),
        ),
        (
            "name,hourly_cost,hours_low,hours_mode,hours_high\nAlice,95,1800,1600,1900\n",
            (
                "people.csv line 2: need hours_low <= hours_mode <= hours_high, "
                "got 1800, 1600, 1900"
            ),
        ),
        (
            "name,hourly_cost,hours_low,hours_mode,hours_high\nAlice,95,-5,1600,1900\n",
            "people.csv line 2: hours_low cannot be negative, got -5",
        ),
        (
            "name,hourly_cost,under,over\nAlice,95,10,5\nBob,110,10,-5\n",
            (
                "people.csv line 3: under must be 0-100 and over at least 0 "
                "(percent of planned hours), got under=10, over=-5"
            ),
        ),
        (
            "name,hourly_cost,under,over\nAlice,95,-10,5\n",
            (
                "people.csv line 2: under must be 0-100 and over at least 0 "
                "(percent of planned hours), got under=-10, over=5"
            ),
        ),
    ],
)
def test_people_values_are_checked(tmp_path, text, message):
    people = _write(tmp_path, "people.csv", text)
    with pytest.raises(ValueError) as caught:
        load_people(people, productive_hours=PH)
    assert str(caught.value) == message


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (
            "Bob,2026-01-01,5",
            (
                "plan.csv line 3: fte must be 0 to 1, got 5 "
                "(FTE is a share of full time: 0 to 1)"
            ),
        ),
        (
            "Bob,2026-01-01,-0.5",
            (
                "plan.csv line 3: fte must be 0 to 1, got -0.5 "
                "(FTE is a share of full time: 0 to 1)"
            ),
        ),
        (",2026-01-01,0.5", "plan.csv line 3: name is blank"),
    ],
)
def test_plan_values_are_checked(tmp_path, row, message):
    plan = _write(
        tmp_path, "plan.csv", f"name,effective_date,fte\nAlice,2026-01-01,0.9\n{row}\n"
    )
    with pytest.raises(ValueError) as caught:
        load_plan(plan)
    assert str(caught.value) == message


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            "name,week,hours_to_date\nAlice,5,100\nAlice,99,200\n",
            "weekly.csv line 3: 2026 has no ISO week 99",
        ),
        (
            "name,week,hours_to_date\nAlice,5,100\nAlice,8,200\nAlice,9,150\n",
            (
                "weekly.csv line 4: Alice: hours_to_date fell from 200 (2026-02-22) "
                "to 150 (2026-03-01). These readings must be cumulative, not per-week."
            ),
        ),
    ],
)
def test_weekly_errors_name_the_file_and_line(tmp_path, text, message):
    weekly = _write(tmp_path, "weekly.csv", text)
    with pytest.raises(ValueError) as caught:
        load_weekly_actuals(weekly, year_span(2026))
    assert str(caught.value) == message


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (
            "Bad,2026-02-01,50,60,80",
            "costs.csv line 3: Bad: need low <= amount <= high, got (60.0, 50.0, 80.0)",
        ),
        (
            "Neg,2026-02-01,-5,,",
            "costs.csv line 3: Neg: amount cannot be negative",
        ),
    ],
)
def test_cost_values_name_the_file_and_line(tmp_path, row, message):
    costs = _write(
        tmp_path,
        "costs.csv",
        f"name,date,amount,low,high\nOk,2026-01-01,10,,\n{row}\n",
    )
    with pytest.raises(ValueError) as caught:
        load_costs(costs)
    assert str(caught.value) == message


@pytest.mark.parametrize("fte", ["5", "-0.5"])
def test_allocation_fte_is_checked(tmp_path, fte):
    alloc = _write(tmp_path, "allocations.csv", f"name,fte\nAlice,0.5\nBob,{fte}\n")
    with pytest.raises(ValueError) as caught:
        load_allocations(alloc, 1600.0)
    assert str(caught.value) == (
        f"allocations.csv line 3: fte must be 0 to 1, got {float(fte):g} "
        "(FTE is a share of full time: 0 to 1)"
    )


def test_sensible_edges_still_load(tmp_path):
    people = _write(
        tmp_path,
        "people.csv",
        "name,hourly_cost,util_low,util_mode,util_high\nAlice,0,0,0,1\n",
    )
    assert load_people(people, productive_hours=PH)[0].hourly_cost == 0
    plan = _write(
        tmp_path,
        "plan.csv",
        "name,effective_date,fte\nAlice,2026-01-01,1\nAlice,2026-06-01,0\n",
    )
    assert len(load_plan(plan).entries) == 2


# --- the CLI says it in one line ----------------------------------------------


@pytest.fixture
def project(tmp_path, monkeypatch):
    forget_workspaces()
    init_workspace(tmp_path, year=2026)
    monkeypatch.chdir(tmp_path)
    yield tmp_path
    forget_workspaces()


def _run(*args):
    return CliRunner().invoke(cli, list(args))


def test_a_bad_date_is_one_line_with_a_pointer(project):
    (project / "plan.csv").write_text(
        "name,effective_date,fte\nAlice,2026-01-01,0.9\nBob,2026-13-01,0.85\n"
    )
    result = _run("forecast", "--seed", "1")
    assert result.exit_code == 1
    assert not isinstance(result.exception, ValueError)  # handled, no traceback
    lines = result.output.splitlines()
    assert (
        "error: plan.csv line 3: could not read '2026-13-01' as a date; "
        "use YYYY-MM-DD (e.g. 2026-03-15)"
    ) in lines
    assert lines[-1] == "see: budgie guide plan"


def test_a_bad_week_is_one_line_with_a_pointer(project):
    (project / "weekly.csv").write_text("name,week,hours_to_date\nAlice,99,100\n")
    result = _run("forecast", "--weekly", "weekly.csv")
    assert result.exit_code == 1
    assert "error: weekly.csv line 2: 2026 has no ISO week 99" in result.output


def test_a_missing_column_points_at_the_people_guide(project):
    (project / "people.csv").write_text("name,rate\nAlice,95\n")
    result = _run("forecast")
    assert result.exit_code == 1
    assert result.output.splitlines()[-2:] == [
        "error: people.csv: missing column hourly_cost",
        "see: budgie guide people",
    ]


def test_an_empty_team_is_named_not_a_simulate_error(project):
    (project / "people.csv").write_text("name,hourly_cost\n")
    result = _run("forecast")
    assert result.exit_code == 1
    assert "error: people.csv has no people" in result.output
    assert "simulate()" not in result.output


def test_a_missing_file_is_one_line(project):
    result = _run("forecast", "--people", "nope.csv")
    assert result.exit_code == 1
    assert result.output.splitlines()[-1] == "error: no such file: nope.csv"


def test_verbose_keeps_the_traceback(project):
    (project / "people.csv").write_text("name,hourly_cost\n")
    result = _run("-v", "forecast")
    assert isinstance(result.exception, ValueError)


def _one_line_error(result, *needles):
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    lines = [x for x in result.output.splitlines() if x.startswith("error:")]
    assert len(lines) == 1
    assert all(n in lines[0] for n in needles)


def test_broken_yaml_is_one_line_naming_the_file(project):
    (project / "budgie.yaml").write_text("budget: [1,\n")
    _one_line_error(_run("forecast"), "budgie.yaml")


def test_a_non_mapping_yaml_is_one_line_naming_the_file(project):
    (project / "budgie.yaml").write_text("- a\n- b\n")
    _one_line_error(_run("forecast"), "budgie.yaml", "key: value")


def test_broken_scenarios_yaml_is_one_line_naming_the_file(project):
    (project / "scenarios.yaml").write_text("scenarios: [1,\n")
    _one_line_error(_run("scenario", "--config", "scenarios.yaml"), "scenarios.yaml")


def test_an_unreadable_file_is_one_line_naming_the_file(project):
    (project / "plan.csv").chmod(0)
    try:
        _one_line_error(_run("forecast"), "plan.csv")
    finally:
        (project / "plan.csv").chmod(0o644)


def test_a_directory_where_a_file_belongs_is_one_line(project):
    (project / "scen").mkdir()
    _one_line_error(_run("scenario", "--config", "scen"), "scen")
