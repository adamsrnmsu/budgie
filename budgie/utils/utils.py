"""Small rich presentation helpers shared by the front-ends."""

from budgie.singletons import banner, console, logger


def display_startup_message():
    console.print(banner(), style="bold blue")
    logger.info("Budgie started!")
