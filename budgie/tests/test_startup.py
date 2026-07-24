"""
Guards on CLI startup cost.

``budgie --help`` used to take seconds because importing the CLI module pulled
in the whole engine -- pandas alone cost about half a second. Every engine and
rendering import now lives inside the command that needs it, and these tests
fail if one creeps back up to module scope.

They run in a subprocess because the test session itself has already imported
most of these modules, so ``sys.modules`` in-process proves nothing.
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


def _modules_after(statement: str) -> set[str]:
    """Top-level module names loaded after running ``statement`` in a subprocess."""
    code = (
        f"import sys\n{statement}\n"
        "print('\\n'.join(sorted({m.split('.')[0] for m in sys.modules})))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    return set(out.stdout.split())


def test_importing_the_cli_stays_light():
    loaded = _modules_after("import budgie.budgie")
    assert not loaded & set(_FORBIDDEN_ON_IMPORT), (
        "these were imported just to build the command tree: "
        f"{sorted(loaded & set(_FORBIDDEN_ON_IMPORT))}"
    )


def test_help_does_not_load_the_engine():
    # Click renders --help without invoking the group callback, so not even the
    # rich console should be constructed.
    loaded = _modules_after(
        "from click.testing import CliRunner\n"
        "from budgie.budgie import cli\n"
        "assert CliRunner().invoke(cli, ['--help']).exit_code == 0"
    )
    assert "budgie.core" not in loaded
    assert not loaded & set(_FORBIDDEN_ON_IMPORT)


def test_pandas_is_gone_entirely():
    # The loaders read small flat CSVs with the stdlib csv module now; nothing
    # in the package should reach for pandas again.
    loaded = _modules_after(
        "import budgie.budgie, budgie.core.loader, budgie.core.plan, "
        "budgie.core.budget, budgie.core.actuals, budgie.core.costs, "
        "budgie.core.monthly, budgie.core.allocation"
    )
    assert "pandas" not in loaded
