"""
Budgie main
"""

from budgie.singletons import console, logger, header
import pandas as pd
from pathlib import Path
import click
from rich.table import Table

THIS_FILE = Path(__file__).resolve()
THIS_DIR = THIS_FILE.parent


@click.group()
def cli():
    """
    Main CLI Entrypoint for budgie
    """
    pass


def display_startup_message():
    console.print(header, style="bold blue")
    logger.info("Budgie started!")


def display_dataframe(df, style):
    table = Table(show_header=True, header_style="bold magenta")
    for column in df.columns:
        table.add_column(column)
    for _, row in df.iterrows():
        table.add_row(*[str(item) for item in row])
    console.print(table, style=style)

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
