import logging

import pyfiglet
from rich.console import Console
from rich.logging import RichHandler


# Singleton for rich logger
logging.basicConfig(
    level="NOTSET", format="%(message)s", datefmt="[%X]", handlers=[RichHandler()]
)
logger = logging.getLogger("rich")

# Singleton for rich console
console = Console()

# header for budgie
header = pyfiglet.figlet_format("Budgie", font="slant")
