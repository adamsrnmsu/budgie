import logging

import pyfiglet
from rich.console import Console
from rich.logging import RichHandler

# Singleton for rich logger. Level is INFO (not NOTSET) so noisy third-party
# DEBUG logging -- e.g. matplotlib's font manager -- doesn't flood our output.
logging.basicConfig(
    level="INFO", format="%(message)s", datefmt="[%X]", handlers=[RichHandler()]
)
logger = logging.getLogger("rich")

# Singleton for rich console
console = Console()

# header for budgie
header = pyfiglet.figlet_format("Budgie", font="slant")
