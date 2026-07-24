"""
Guards on CLI startup cost.

``budgie --help`` used to take seconds because importing the CLI module pulled
in the whole engine -- pandas alone cost about half a second. Every engine and
rendering import now lives inside the command that needs it, and these tests
fail if one creeps back up to module scope.

They run in a subprocess because the test session itself has already imported
most of these modules, so ``sys.modules`` in-process proves nothing. They also
run in an empty directory, because the landing screen looks for a project and
finding one would change what gets imported.
"""

from __future__ import annotations

import subprocess
import sys

# Heavy third-party imports that no command-tree construction should need.
_FORBIDDEN_ON_IMPORT = (
    "numpy",
    "holidays",
    "matplotlib",
    "textual",
    "yaml",
    "pyfiglet",
)

# The engine proper. Rendering help means reading the workspace and the guide,
# but it must never mean loading the math.
_ENGINE_MODULES = (
    "budgie.core.montecarlo",
    "budgie.core.forecast",
    "budgie.core.loader",
    "budgie.core.monthly",
    "budgie.core.calendar",
    "budgie.core.plan",
)


def _modules_after(statement: str, cwd=None) -> set[str]:
    """Full module names loaded after running ``statement`` in a subprocess."""
    code = f"import sys\n{statement}\nprint('\\n'.join(sorted(sys.modules)))"
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
    )
    return set(out.stdout.split())


def _top_level(modules: set[str]) -> set[str]:
    return {m.split(".")[0] for m in modules}


def test_importing_the_cli_stays_light(tmp_path):
    loaded = _modules_after("import budgie.budgie", cwd=tmp_path)
    offenders = _top_level(loaded) & set(_FORBIDDEN_ON_IMPORT)
    assert not offenders, (
        f"these were imported just to build the command tree: {sorted(offenders)}"
    )


def test_importing_the_cli_loads_no_engine_module(tmp_path):
    loaded = _modules_after("import budgie.budgie", cwd=tmp_path)
    assert not loaded & set(_ENGINE_MODULES)


def test_help_does_not_load_the_engine(tmp_path):
    # The landing screen is rich-rendered and reads the workspace, so those do
    # get imported -- but none of the math, and nothing heavy.
    loaded = _modules_after(
        "from click.testing import CliRunner\n"
        "from budgie.budgie import cli\n"
        "assert CliRunner().invoke(cli, ['--help']).exit_code == 0",
        cwd=tmp_path,
    )
    assert not loaded & set(_ENGINE_MODULES)
    assert not _top_level(loaded) & set(_FORBIDDEN_ON_IMPORT)


def test_pandas_is_gone_entirely(tmp_path):
    # The loaders read small flat CSVs with the stdlib csv module now; nothing
    # in the package should reach for pandas again.
    loaded = _modules_after(
        "import budgie.budgie, budgie.core.loader, budgie.core.plan, "
        "budgie.core.budget, budgie.core.actuals, budgie.core.costs, "
        "budgie.core.monthly, budgie.core.allocation",
        cwd=tmp_path,
    )
    assert "pandas" not in _top_level(loaded)
