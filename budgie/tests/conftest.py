"""Shared test setup.

Colour off before anything imports rich: CLI tests assert on rendered text,
and a FORCE_COLOR in the environment (some agent shells export it) splits
that text with ANSI codes. The console singleton reads it at import time, so
a fixture would be too late.
"""

import os

os.environ.pop("FORCE_COLOR", None)
