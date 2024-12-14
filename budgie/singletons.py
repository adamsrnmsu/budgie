import logging

import pyfiglet
from rich.console import Console
from rich.logging import RichHandler

# Singleton for rich console
console = Console()

# Singleton for rich logger
logging.basicConfig(
    level="NOTSET", format="%(message)s", datefmt="[%X]", handlers=[RichHandler()]
)
logger = logging.getLogger("rich")
header = pyfiglet.figlet_format("Budgie", font="slant")
