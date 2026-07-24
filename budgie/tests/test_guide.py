"""The landing screen, the walkthrough, and the per-file topics."""

import pytest
from click.testing import CliRunner

from budgie.budgie import cli
from budgie.core.guide import COMMAND_GROUPS, PHASES, TOPICS, topic_names
from budgie.core.scaffold import DEFAULT_PROJECT_DIR, init_workspace
from budgie.core.workspace import INPUTS, forget_workspaces


@pytest.fixture(autouse=True)
def _clear_workspace_cache():
    forget_workspaces()
    yield
    forget_workspaces()


def _run(args, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    forget_workspaces()
    return CliRunner().invoke(cli, args)


# -- the data itself ----------------------------------------------------


def test_every_command_in_the_listing_actually_exists():
    # A renamed command must not leave a dead entry on the landing screen.
    listed = {name for _h, _b, pairs in COMMAND_GROUPS for name, _s in pairs}
    assert listed <= set(cli.commands), listed - set(cli.commands)


def test_every_command_appears_in_the_listing():
    # And a new command must not be invisible.
    listed = {name for _h, _b, pairs in COMMAND_GROUPS for name, _s in pairs}
    assert set(cli.commands) <= listed, set(cli.commands) - listed


def test_every_topic_maps_to_a_real_input():
    assert {t.key for t in TOPICS} == set(INPUTS)


def test_topics_name_the_file_and_its_consumers():
    for topic in TOPICS:
        assert topic.filename == INPUTS[topic.key][0]
        assert topic.used_by == INPUTS[topic.key][2]


def test_phases_are_numbered_in_order():
    assert [p.number for p in PHASES] == list(range(1, len(PHASES) + 1))


# -- rendering ----------------------------------------------------------


def test_bare_budgie_shows_the_grouped_overview(tmp_path, monkeypatch):
    result = _run([], tmp_path, monkeypatch)

    assert result.exit_code == 0, result.output
    for heading, _blurb, _pairs in COMMAND_GROUPS:
        assert heading in result.output
    # And it points somewhere useful rather than just listing commands.
    assert "budgie init" in result.output


def test_help_flag_shows_the_same_overview(tmp_path, monkeypatch):
    bare = _run([], tmp_path, monkeypatch)
    flagged = _run(["--help"], tmp_path, monkeypatch)

    assert flagged.exit_code == 0, flagged.output
    assert "Start here" in flagged.output
    assert flagged.output == bare.output


def test_overview_suggests_forecast_once_you_have_a_project(tmp_path, monkeypatch):
    init_workspace(tmp_path, year=2026)
    result = _run([], tmp_path, monkeypatch)

    assert "budgie forecast" in result.output
    assert "budgie init" not in result.output


def test_guide_lists_the_phases(tmp_path, monkeypatch):
    result = _run(["guide"], tmp_path, monkeypatch)

    assert result.exit_code == 0, result.output
    for phase in PHASES:
        assert phase.title in result.output


def test_guide_topic_shows_columns_and_rules(tmp_path, monkeypatch):
    result = _run(["guide", "plan"], tmp_path, monkeypatch)

    assert result.exit_code == 0, result.output
    assert "effective_date" in result.output
    assert "APPEND, never edit" in result.output


def test_guide_topic_accepts_the_filename_too(tmp_path, monkeypatch):
    # `budgie guide people.csv` is what someone will type after seeing status.
    by_key = _run(["guide", "people"], tmp_path, monkeypatch)
    by_file = _run(["guide", "people.csv"], tmp_path, monkeypatch)

    assert by_file.exit_code == 0
    assert by_file.output == by_key.output


def test_unknown_topic_lists_the_real_ones(tmp_path, monkeypatch):
    result = _run(["guide", "nonsense"], tmp_path, monkeypatch)

    assert result.exit_code != 0
    for name in topic_names():
        assert name in result.output


# -- init into a subfolder ----------------------------------------------


def test_init_creates_a_subfolder_not_clutter(tmp_path, monkeypatch):
    result = _run(["init"], tmp_path, monkeypatch)

    assert result.exit_code == 0, result.output
    assert (tmp_path / DEFAULT_PROJECT_DIR / "budgie.yaml").is_file()
    # Nothing loose in the directory the user was standing in.
    assert [p.name for p in tmp_path.iterdir()] == [DEFAULT_PROJECT_DIR]


def test_init_takes_a_name(tmp_path, monkeypatch):
    result = _run(["init", "fy27"], tmp_path, monkeypatch)

    assert result.exit_code == 0, result.output
    assert (tmp_path / "fy27" / "budgie.yaml").is_file()


def test_init_here_still_works(tmp_path, monkeypatch):
    result = _run(["init", "--here"], tmp_path, monkeypatch)

    assert result.exit_code == 0, result.output
    assert (tmp_path / "budgie.yaml").is_file()


def test_init_rejects_a_name_and_here_together(tmp_path, monkeypatch):
    result = _run(["init", "fy27", "--here"], tmp_path, monkeypatch)

    assert result.exit_code != 0
    assert "not both" in result.output


# -- finding the project from one level up ------------------------------


def test_commands_find_the_single_project_below(tmp_path, monkeypatch):
    _run(["init"], tmp_path, monkeypatch)
    result = _run(["status"], tmp_path, monkeypatch)

    assert result.exit_code == 0, result.output
    assert DEFAULT_PROJECT_DIR in result.output


def test_two_projects_below_are_not_guessed_between(tmp_path, monkeypatch):
    init_workspace(tmp_path / "a", year=2026)
    init_workspace(tmp_path / "b", year=2026)

    result = _run(["status"], tmp_path, monkeypatch)

    # Ambiguous: better to say there's no project than to pick the wrong budget.
    assert "budgie init" in result.output


def test_a_project_above_still_wins_over_one_below(tmp_path, monkeypatch):
    init_workspace(tmp_path, year=2026)  # here
    init_workspace(tmp_path / "nested", year=2026)  # and below

    result = _run(["status"], tmp_path, monkeypatch)

    assert result.exit_code == 0, result.output
    assert str(tmp_path.resolve()) in result.output.replace("\n", "")
