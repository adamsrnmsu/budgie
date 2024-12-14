"""
Budgie main
"""

from pathlib import Path

import click
import pandas as pd
from budgie.singletons import logger
from budgie.utils.utils import display_dataframe, display_startup_message

THIS_FILE = Path(__file__).resolve()
THIS_DIR = THIS_FILE.parent


@click.group()
def cli():
    """
    Main CLI Entrypoint for budgie
    """
    pass


@click.command()
@click.option(
    "--show_costs",
    help="File path to where your costs are",
    default="tests/costs.csv",
    required=True,
)
def show_costs(cost_info):
    """
    Main function for budgie
    """
    display_startup_message()
    logger.info(f"Cost info: {cost_info}")
    logger.info(f"Cost info: {THIS_FILE}")

    cost_path = Path(THIS_DIR / cost_info)
    cost_frame = pd.read_csv(cost_path)

    display_dataframe(cost_frame, style="bold green")

cli.add_command(show_costs)

if __name__ == "__main__":
    cli()
