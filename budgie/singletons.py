"""
Shared presentation singletons.

This is where rich gets wired into logging. Modules under ``budgie/core/`` use
plain ``logging.getLogger(__name__)`` and never import rich -- their records
propagate to the root logger configured here, so the engine stays UI-free while
its logs still come out rich-formatted whenever a front-end is running.

Importing this module is deliberately cheap-ish, but the ASCII banner is not:
``pyfiglet.figlet_format`` parses a font file on every call, so the banner is
built on first use by :func:`banner` rather than at import.
"""

import logging
from functools import lru_cache

from rich.console import Console
from rich.logging import RichHandler

# Root handler is rich. Level is INFO (not NOTSET) so noisy third-party DEBUG
# logging -- e.g. matplotlib's font manager -- doesn't flood our output.
logging.basicConfig(
    level="INFO",
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
)
logger = logging.getLogger("budgie")

# matplotlib chatters at INFO (categorical-units notices) and floods at DEBUG
# (font manager). Neither is ours; keep it to real warnings.
logging.getLogger("matplotlib").setLevel(logging.WARNING)

# Singleton for rich console
console = Console()


@lru_cache(maxsize=1)
def banner() -> str:
    """The Budgie ASCII-art header, rendered once on first use."""
    import pyfiglet

    return pyfiglet.figlet_format("Budgie", font="slant")


def set_verbose(verbose: bool) -> None:
    """Turn on DEBUG for budgie's own loggers only.

    Third-party libraries stay at INFO -- matplotlib's font manager alone emits
    hundreds of DEBUG records per figure and would bury everything useful.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.getLogger("budgie").setLevel(level)
    logging.getLogger("budgie.core").setLevel(level)
    # Module loggers are named by import path (budgie.core.plan, ...), so
    # setting the package logger covers them all.
    logging.getLogger(__name__.rsplit(".", 1)[0]).setLevel(level)
