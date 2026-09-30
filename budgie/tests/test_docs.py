"""The API reference lists every engine module.

autodoc only renders the modules docs/api.md names, so a new ``budgie/core``
module would otherwise be missing from the docs without the build noticing.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_api_reference_covers_every_core_module():
    modules = {p.stem for p in (ROOT / "budgie" / "core").glob("*.py")} - {"__init__"}
    api = (ROOT / "docs" / "api.md").read_text()
    missing = sorted(
        m for m in modules if f".. automodule:: budgie.core.{m}\n" not in api
    )
    assert not missing, f"add to docs/api.md: {missing}"
