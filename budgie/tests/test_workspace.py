"""Project workspace: discovery, resolution, and the init scaffold."""

import pytest
from click.testing import CliRunner

from budgie.budgie import cli
from budgie.core.scaffold import init_workspace
from budgie.core.workspace import (
    CONFIG_NAME,
    INPUTS,
    find_workspace,
    forget_workspaces,
    load_workspace,
)


@pytest.fixture(autouse=True)
def _clear_workspace_cache():
    # find_workspace() is cached per directory; tests move between tmp dirs.
    forget_workspaces()
    yield
    forget_workspaces()


def _write_config(directory, body):
    path = directory / CONFIG_NAME
    path.write_text(body)
    return path


def test_scaffold_writes_a_loadable_project(tmp_path):
    written, skipped = init_workspace(tmp_path, year=2026)

    assert skipped == []
    assert {p.name for p in written} >= {CONFIG_NAME, "people.csv", "allocations.csv"}
    # The generated files are real data, not placeholders: they load.
    workspace = load_workspace(tmp_path / CONFIG_NAME)
    assert workspace.setting("year") == 2026
    assert all(item.exists for item in workspace.inputs())


def test_init_never_overwrites_without_force(tmp_path):
    init_workspace(tmp_path, year=2026)
    (tmp_path / "people.csv").write_text(
        "name,hourly_cost,util_low,util_mode,util_high\nZed,1,1,1,1\n"
    )

    _written, skipped = init_workspace(tmp_path, year=2026)

    assert (tmp_path / "people.csv").read_text().count("Zed") == 1
    assert any(p.name == "people.csv" for p in skipped)


def test_init_with_force_replaces_files(tmp_path):
    init_workspace(tmp_path, year=2026)
    (tmp_path / "people.csv").write_text("name,hourly_cost\n")

    init_workspace(tmp_path, year=2026, overwrite=True)

    assert "Alice" in (tmp_path / "people.csv").read_text()


def test_workspace_is_found_from_a_subdirectory(tmp_path):
    init_workspace(tmp_path, year=2026)
    nested = tmp_path / "reports" / "q3"
    nested.mkdir(parents=True)

    workspace = find_workspace(nested)

    assert workspace is not None
    assert workspace.root == tmp_path.resolve()


def test_no_workspace_returns_none(tmp_path):
    assert find_workspace(tmp_path) is None


def test_configured_paths_are_relative_to_the_config(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "roster.csv").write_text("name,hourly_cost\n")
    _write_config(tmp_path, "inputs:\n  people: data/roster.csv\n")

    workspace = find_workspace(tmp_path)

    assert workspace.path_for("people") == (tmp_path / "data" / "roster.csv").resolve()
    assert workspace.resolve("people").endswith("roster.csv")


def test_missing_input_resolves_to_none_rather_than_failing(tmp_path):
    _write_config(tmp_path, "year: 2026\n")
    workspace = find_workspace(tmp_path)

    # Declaring a project shouldn't make every command demand every file.
    assert workspace.resolve("costs") is None
    assert workspace.setting("year") == 2026


def test_an_unknown_input_key_is_rejected(tmp_path):
    _write_config(tmp_path, "inputs:\n  peeple: people.csv\n")
    with pytest.raises(ValueError, match="unknown inputs"):
        find_workspace(tmp_path)


def test_a_numeric_budget_in_the_config_is_a_setting_not_a_path(tmp_path):
    _write_config(tmp_path, "budget: 500000\n")
    assert find_workspace(tmp_path).setting("budget") == 500000


def _run_in(directory, monkeypatch, args):
    """Invoke the CLI with ``directory`` as the working directory."""
    monkeypatch.chdir(directory)
    forget_workspaces()
    return CliRunner().invoke(cli, args)


def test_commands_use_the_project_when_run_inside_it(tmp_path, monkeypatch):
    init_workspace(tmp_path, year=2026)
    # A distinctive name proves the project's file was read, not the sample.
    (tmp_path / "people.csv").write_text(
        "name,hourly_cost,util_low,util_mode,util_high\nZaphod,200,0.5,0.5,0.5\n"
    )

    result = _run_in(tmp_path, monkeypatch, ["forecast"])

    assert result.exit_code == 0, result.output
    assert "Zaphod" in result.output


def test_a_project_setting_supplies_the_default(tmp_path, monkeypatch):
    _write_config(tmp_path, "year: 2031\npto: 12\n")

    result = _run_in(tmp_path, monkeypatch, ["assumptions"])

    assert result.exit_code == 0, result.output
    assert "Assumptions in force for 2031" in result.output
    assert "12 days" in result.output
    assert "Where numbers come from" in result.output
    assert "edit the module" not in " ".join(result.output.split())


def test_an_explicit_option_still_beats_the_project(tmp_path, monkeypatch):
    init_workspace(tmp_path, year=2026)
    other = tmp_path / "other.csv"
    other.write_text(
        "name,hourly_cost,util_low,util_mode,util_high\nFord,150,0.5,0.5,0.5\n"
    )

    result = _run_in(tmp_path, monkeypatch, ["forecast", "--people", str(other)])

    assert result.exit_code == 0, result.output
    assert "Ford" in result.output
    assert "Alice" not in result.output


def test_commands_fall_back_to_samples_with_no_project(tmp_path, monkeypatch):
    result = _run_in(tmp_path, monkeypatch, ["forecast", "--seed", "1"])

    assert result.exit_code == 0, result.output
    assert "Deterministic forecast" in result.output


def test_status_explains_itself_when_there_is_no_project(tmp_path, monkeypatch):
    result = _run_in(tmp_path, monkeypatch, ["status"])

    assert result.exit_code == 0, result.output
    assert "budgie init" in result.output


def test_init_then_every_command_runs(tmp_path, monkeypatch):
    # The scaffold's whole job: `budgie init` and everything works immediately.
    monkeypatch.chdir(tmp_path)
    forget_workspaces()
    assert CliRunner().invoke(cli, ["init", "."]).exit_code == 0

    for args in (
        ["status"],
        ["forecast"],
        ["hours"],
        ["plan"],
        ["monthly", "--iterations", "200"],
        ["scenario"],
        ["assumptions"],
    ):
        forget_workspaces()
        result = CliRunner().invoke(cli, args)
        assert result.exit_code == 0, f"{args} failed:\n{result.output}"


def test_emails_uses_the_project_allocations(tmp_path, monkeypatch):
    # `emails` kept its own sample default, so _input() saw a truthy override
    # and the project's allocations.csv was never read.
    init_workspace(tmp_path, year=2026)
    (tmp_path / "allocations.csv").write_text(
        "name,fte,hours_spent,email\nSlartibartfast,0.5,100,slarti@example.com\n"
    )

    result = _run_in(
        tmp_path,
        monkeypatch,
        ["emails", "--out-dir", str(tmp_path / "out"), "--as-of", "2026-06-30"],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "out" / "slartibartfast.eml").exists()


def test_hours_uses_the_project_allocations(tmp_path, monkeypatch):
    init_workspace(tmp_path, year=2026)
    (tmp_path / "allocations.csv").write_text(
        "name,fte,hours_spent\nSlartibartfast,0.5,100\n"
    )

    result = _run_in(tmp_path, monkeypatch, ["hours"])

    assert result.exit_code == 0, result.output
    assert "Slartibartfast" in result.output


def test_monthly_uses_the_project_costs_like_forecast(tmp_path, monkeypatch):
    init_workspace(tmp_path, year=2026)
    args = ["monthly", "--iterations", "200", "--seed", "1"]
    header = "name,category,date,amount,low,high,recurring\n"
    (tmp_path / "costs.csv").write_text(header)
    without = _run_in(tmp_path, monkeypatch, args)
    (tmp_path / "costs.csv").write_text(
        header + "Zorp hosting,hosting,2026-01-01,123457,,,yes\n"
    )

    result = _run_in(tmp_path, monkeypatch, args)

    assert result.exit_code == 0, result.output
    assert result.output != without.output


def test_inputs_used_by_names_tui_for_every_input_it_reads():
    tui_reads = {
        "people",
        "allocations",
        "plan",
        "costs",
        "budget",
        "actuals",
        "weekly",
    }
    for key, (_f, _d, used_by) in INPUTS.items():
        assert ("tui" in used_by) == (key in tui_reads), key
