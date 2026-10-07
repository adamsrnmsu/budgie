"""PI_BLOCKS contract: perch's tui-blocks spec, 'The format (contract)'."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from budgie import blocks
from budgie.core.scaffold import init_workspace

TESTS = Path(__file__).resolve().parent
TONES = {"good", "warn", "bad", "dim"}


def _strs(v, n=None):
    return (
        isinstance(v, list)
        and all(isinstance(x, str) for x in v)
        and (n is None or len(v) == n)
    )


def check(b):
    """The spec's field table, as a checker. Returns True when b conforms."""
    if b.get("pi") != 1 or not (b.get("tone") is None or b["tone"] in TONES):
        return False
    kind = b.get("block")
    if kind == "heading":
        return b.get("level") in (1, 2, 3) and isinstance(b.get("text"), str)
    if kind == "text":
        return isinstance(b.get("text"), str)
    if kind == "figures":
        return isinstance(b.get("items"), list) and all(
            isinstance(f.get("label"), str)
            and isinstance(f.get("value"), str)
            and isinstance(f.get("note", ""), str)
            and f.get("tone") in (None, *TONES)
            for f in b["items"]
        )
    if kind == "table":
        cols = b.get("columns")
        return (
            _strs(cols)
            and isinstance(b.get("rows"), list)
            and all(_strs(r, len(cols)) for r in b["rows"])
            and (
                b.get("align") is None
                or (_strs(b["align"], len(cols)) and set(b["align"]) <= {"l", "r"})
            )
            and isinstance(b.get("title", ""), str)
        )
    if kind == "list":
        return _strs(b.get("items"))
    return False


def run(args, cwd, blocks_on=True):
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    env.pop("PI_BLOCKS", None)
    if blocks_on:
        env["PI_BLOCKS"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "budgie.budgie", *args],
        check=False,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )


def parsed(proc):
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert lines
    out = [json.loads(line) for line in lines]  # every line is JSON: no banner
    assert all(check(b) for b in out), out
    return out


@pytest.fixture
def project(tmp_path):
    init_workspace(tmp_path, year=2026)
    return tmp_path


def test_checker_rejects_bad_blocks():
    assert not check(
        {"pi": 1, "block": "table", "columns": ["a"], "rows": [["x", "y"]]}
    )
    assert not check({"pi": 1, "block": "text", "text": "x", "tone": "loud"})


def test_wanted_reads_env(monkeypatch):
    monkeypatch.delenv("PI_BLOCKS", raising=False)
    assert not blocks.wanted()
    monkeypatch.setenv("PI_BLOCKS", "1")
    assert blocks.wanted()


def test_forecast_blocks(tmp_path):
    proc = run(
        [
            "forecast",
            "--people",
            str(TESTS / "team.csv"),
            "--seed",
            "1",
            "--costs",
            str(TESTS / "costs_items.csv"),
            "--budget",
            "1000000",
        ],
        tmp_path,
    )
    out = parsed(proc)
    kinds = [b["block"] for b in out]
    assert {"table", "figures", "text"} <= set(kinds)
    assert [t["title"] for t in out if t["block"] == "table"] == [
        "Deterministic forecast",
        "Non-labor costs",
    ]
    fig = next(b for b in out if b["block"] == "figures")
    assert [f["label"] for f in fig["items"]] == ["P10", "P50", "P90", "mean", "std"]
    signal = out[-1]
    assert signal["block"] == "text" and signal["tone"] in TONES
    assert "banner" not in proc.stdout.lower() and "Budgie started" not in proc.stdout
    assert "Budgie started" not in proc.stderr  # INFO is -v only


def test_status_blocks(project):
    out = parsed(run(["status"], project))
    assert any(b["block"] == "figures" for b in out)
    assert any(b["block"] == "table" and b["columns"][1] == "File" for b in out)
    assert out[-1] == {
        "pi": 1,
        "block": "text",
        "tone": "dim",
        "text": f"Settings from {project / 'budgie.yaml'}",
    }


def test_emails_blocks(project):
    (project / "allocations.csv").write_text(
        "name,fte,hours_spent,email\nSlarti,0.5,100,s@example.com\n"
    )
    out = parsed(
        run(
            ["emails", "--out-dir", "emails", "--no-preview", "--as-of", "2026-06-30"],
            project,
        )
    )
    assert out[1]["block"] == "list" and out[1]["items"]  # the scaffold writes 3
    assert out[0]["block"] == "text" and out[0]["text"].startswith(
        f"Wrote {len(out[1]['items'])} draft(s)"
    )


def test_plain_output_unchanged_without_env(tmp_path):
    proc = run(
        ["forecast", "--people", str(TESTS / "team.csv"), "--seed", "1"],
        tmp_path,
        blocks_on=False,
    )
    assert "Deterministic forecast" in proc.stdout and "Monte Carlo" in proc.stdout


def _values(b):
    """Every string a block shows, for the drift guard."""
    if b["block"] in ("heading", "text"):
        return [b["text"]]
    if b["block"] == "figures":
        return [f[k] for f in b["items"] for k in ("label", "value", "note") if k in f]
    if b["block"] == "list":
        return b["items"]
    return [b["title"]] * ("title" in b) + [c for r in b["rows"] for c in r if c]


def _plain(proc):
    """Plain stdout with ANSI stripped and whitespace collapsed."""
    assert proc.returncode == 0, proc.stderr
    return re.sub(r"\s+", " ", re.sub(r"\x1b\[[0-9;]*m", "", proc.stdout))


@pytest.mark.parametrize(
    "args",
    [
        [
            "forecast",
            "--people",
            str(TESTS / "team.csv"),
            "--seed",
            "1",
            "--costs",
            str(TESTS / "costs_items.csv"),
            "--budget",
            "1000000",
        ],
        [
            "forecast",
            "--people",
            str(TESTS / "team.csv"),
            "--seed",
            "1",
            "--actuals",
            str(TESTS / "actuals.csv"),
            "--as-of",
            "2026-03-31",
        ],
        ["status"],
    ],
    ids=["forecast", "forecast-eac", "status"],
)
def test_blocks_twins_match_plain_output(project, args, monkeypatch):
    """Drift guard: each ``_*_blocks`` twin shows the values its ``_print_*`` does."""
    monkeypatch.setenv("COLUMNS", "400")  # no rich line-wrapping inside cells
    blocks_out = parsed(run(args, project))
    plain = _plain(run(args, project, blocks_on=False))
    missing = [v for b in blocks_out for v in _values(b) if v not in plain]
    assert not missing, missing
