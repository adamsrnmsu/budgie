"""Small rich presentation helpers shared by the front-ends."""

import logging

from rich.logging import RichHandler

from budgie import blocks
from budgie.singletons import console, logger


def display_startup_message():
    # No banner (the overview panel is bare `budgie`'s). With PI_BLOCKS stdout
    # is blocks only and the log handler writes to stderr. Re-pointed on every call so a later plain run in the
    # same process (tests) goes back to stdout.
    for h in logging.getLogger().handlers:
        if isinstance(h, RichHandler):
            h.console = console if not blocks.wanted() else _stderr_console()
    logger.info("Budgie started!")


def _stderr_console():
    from rich.console import Console

    return Console(stderr=True)
