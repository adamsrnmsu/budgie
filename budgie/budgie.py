"""
Budgie main
"""

from pathlib import Path

import click
import pandas as pd
from budgie.singletons import console, logger
from budgie.utils.utils import create_table, display_startup_message
import termplotlib as tpl
import numpy as np


THIS_FILE = Path(__file__).resolve()
THIS_DIR = THIS_FILE.parent



@click.group()
def cli():
    """
    Main CLI Entrypoint for budgie
    We assign functions fro the CLI to run here
    """
    pass


@click.command()
@click.option(
    "--cost_info",
    help="File path to where your costs are",
    default="tests/costs.csv",
    required=True,
)
def budge(cost_info):
    """
    Main function for budgie
    """
    display_startup_message()
    cost_path = Path(THIS_DIR / cost_info)
    
    logger.info(f"Cost info from: {cost_info}")
    
    cost_frame = pd.read_csv(cost_path)
    
    # Create a dictionary to hold all cost information
    cost_objects = {}

    cost_objects["cost_table"] = create_table(cost_frame, style="bold green", display=False)
    cost_objects["term_plot"] = example_termplotlib()
    

def example_termplotlib():
    """
    Example of using termplotlib
    """
    x = np.linspace(0, 2 * np.pi, 10)
    y = np.sin(x)
    
    fig = tpl.figure()
    fig.plot(x, y, label="data", width=50, height=15)
    return fig


cli.add_command(budge)

if __name__ == "__main__":
    cli()
