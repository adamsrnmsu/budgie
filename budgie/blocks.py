"""Blocks: the output format Budgie prints when ``perch tui`` asks.

With ``PI_BLOCKS=1`` a command prints one JSON object per stdout line instead
of rich output. Plain dicts, no UI: this module lives beside ``budgie.py`` (a
presentation format), not in ``core/``. The contract is perch's
docs/superpowers/specs/2026-10-02-tui-blocks-design.md; Budgie never imports
perch, so this is its own small emitter.
"""

import json
import os
import sys

ENV = "PI_BLOCKS"


def wanted() -> bool:
    """True when the caller (the TUI) asked for blocks."""
    return os.environ.get(ENV) == "1"


def _block(kind: str, **fields) -> dict:
    return {
        "pi": 1,
        "block": kind,
        **{k: v for k, v in fields.items() if v is not None},
    }


def heading(text: str, level: int = 2) -> dict:
    return _block("heading", level=level, text=text)


def text(text: str, tone: str | None = None) -> dict:
    return _block("text", text=text, tone=tone)


def figure(label: str, value: str, note: str | None = None, tone: str | None = None):
    """One tile of a ``figures`` block."""
    tile = {"label": label, "value": value, "note": note, "tone": tone}
    return {k: v for k, v in tile.items() if v is not None}


def figures(items: list[dict]) -> dict:
    return _block("figures", items=items)


def table(columns, rows, title=None, align=None) -> dict:
    return _block("table", title=title, columns=columns, rows=rows, align=align)


def bullets(items: list[str]) -> dict:
    """A ``list`` block (named so it does not shadow the builtin)."""
    return _block("list", items=items)


def emit(blocks) -> None:
    """One JSON line per block on stdout."""
    for b in blocks:
        sys.stdout.write(json.dumps(b, ensure_ascii=False) + "\n")
    sys.stdout.flush()
