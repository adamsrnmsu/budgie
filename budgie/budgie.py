"""
Budgie main
"""

from pathlib import Path

import click
import pandas as pd

from budgie.singletons import console, header, logger
from budgie.utils.utils import display_dataframe

THIS_FILE = Path(__file__).resolve()
THIS_DIR = THIS_FILE.parent

def display_startup_message():
    console.print(header, style="bold blue")
    logger.info("Budgie started!")


@click.group()
def cli():
    """
    Main CLI Entrypoint for budgie
    """
    pass


@click.command()
@click.option(
    "--cost_info",
    help="File path to where your costs are",
    default="tests/costs.csv",
    required=True,
)
def main(cost_info):
    display_startup_message()
    logger.info(f"Cost info: {cost_info}")
    logger.info(f"Cost info: {THIS_FILE}")

    cost_path = Path(THIS_DIR / cost_info)
    cost_frame = pd.read_csv(cost_path)

    display_dataframe(cost_frame, style="bold green")


if __name__ == "__main__":
    cli.add_command(main)
    cli()
