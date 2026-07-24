from pathlib import Path

from click.testing import CliRunner

from budgie.budgie import cli

TESTS_DIR = Path(__file__).resolve().parent


def test_forecast_runs():
    runner = CliRunner()
    result = runner.invoke(
        cli, ["forecast", "--people", str(TESTS_DIR / "team.csv"), "--seed", "1"]
    )
    assert result.exit_code == 0, result.output
    # Deterministic table and Monte Carlo summary should both render.
    assert "Deterministic forecast" in result.output
    assert "Monte Carlo" in result.output
