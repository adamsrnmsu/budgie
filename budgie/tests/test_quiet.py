"""Quiet CLI: no banner, INFO only with -v, one sample-data marker."""

import json

import pytest

from budgie.core.scaffold import init_workspace
from budgie.tests.test_blocks import TESTS, run

MARKER = "sample data — budgie init NAME to start your own"


@pytest.fixture
def project(tmp_path):
    init_workspace(tmp_path, year=2026)
    return tmp_path


def test_project_forecast_is_quiet(project):
    p = run(["forecast", "--seed", "1"], project, blocks_on=False)
    assert p.returncode == 0, p.stderr
    for text in (p.stdout, p.stderr):
        assert "Budgie started" not in text and "Loaded" not in text
        assert "____" not in text  # figlet banner
    assert "sample data" not in p.stdout + p.stderr


def test_verbose_brings_info_back(project):
    p = run(["-v", "forecast", "--seed", "1"], project, blocks_on=False)
    assert "Budgie started" in p.stdout + p.stderr


def test_sample_marker_once_on_stderr(tmp_path):
    p = run(["forecast", "--seed", "1"], tmp_path, blocks_on=False)
    assert p.returncode == 0, p.stderr
    assert (p.stdout + p.stderr).count(MARKER) == 1
    assert MARKER in p.stderr and MARKER not in p.stdout


def test_sample_marker_survives_quiet(tmp_path):
    p = run(["-q", "forecast", "--seed", "1"], tmp_path, blocks_on=False)
    assert p.stderr.count(MARKER) == 1


def test_explicit_files_no_marker(tmp_path):
    p = run(
        ["forecast", "--people", str(TESTS / "team.csv"), "--seed", "1"],
        tmp_path,
        blocks_on=False,
    )
    assert p.returncode == 0, p.stderr


def test_blocks_stdout_stays_json_on_sample(tmp_path):
    p = run(["forecast", "--seed", "1"], tmp_path)
    assert p.returncode == 0, p.stderr
    for line in p.stdout.splitlines():
        json.loads(line)
    assert p.stderr.count(MARKER) == 1


def test_blocks_verbose_logs_go_to_stderr(tmp_path):
    p = run(["-v", "forecast", "--seed", "1"], tmp_path)
    assert "Budgie started" in p.stderr and "Budgie started" not in p.stdout
    for line in p.stdout.splitlines():
        json.loads(line)
