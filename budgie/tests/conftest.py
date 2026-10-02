"""Shared test setup.

Colour off before anything imports rich: CLI tests assert on rendered text,
and a FORCE_COLOR in the environment (some agent shells export it) splits
that text with ANSI codes. The console singleton reads it at import time, so
a fixture would be too late.
"""

import os

os.environ.pop("FORCE_COLOR", None)

from datetime import date

import pytest

# Pinned so a test that scaffolds or defaults a year does not depend on when it runs.
_PINNED_TODAY = date(2026, 6, 15)


@pytest.fixture(autouse=True)
def _pinned_today(monkeypatch):
    from budgie import budgie as cli_module
    from budgie import tui

    monkeypatch.setattr(cli_module, "_today", lambda: _PINNED_TODAY)
    monkeypatch.setattr(tui, "_today", lambda: _PINNED_TODAY)
