"""
Budgie main
"""

from pathlib import Path

import click
import pandas as pd
from budgie.singletons import console, logger
from budgie.utils.utils import create_table, display_startup_message
from rich.panel import Panel
from rich.layout import Layout


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
    logger.info(f"Cost info: {cost_info}")
    logger.info(f"Cost info: {THIS_FILE}")

    cost_path = Path(THIS_DIR / cost_info)
    cost_frame = pd.read_csv(cost_path)

    cost_table = create_table(cost_frame, style="bold green")
    fig = example_termplotlib()
    console.print(create_create_layout(fig))

def create_create_layout(fig):
    """
    Create a layout with multiple panels
    """
    # Create multiple panels
    panel1 = Panel(fig, title="Panel 1", style="bold red")
    panel2 = Panel("This is panel 2", title="Panel 2")
    panel3 = Panel("This is panel 3", title="Panel 3")

    # Layout to arrange panels in a column
    layout = Layout()

    # Split layout into a top panel and a bottom navigation panel
    layout.split_row(
    Layout(Panel("This is the top content area", expand=True), name="main"),  # Expand to fill available space
    Layout(Panel("Navigation Panel"), size=20)  # Bottom panel with fixed size
    )

    # Nested layout in the "main" section
    layout["main"].split_column(
    Layout(Panel("Top part of main area"), size=5),
    Layout(Panel("Bottom part of main area", expand=True))
    )
    return layout
    


def example_termplotlib():
    """
    Example of using termplotlib
    """
    import termplotlib as tpl
    import numpy as np

    x = np.linspace(0, 2 * np.pi, 10)
    y = np.sin(x)

    #logger.info(f"X: {type(x)}")
    
    fig = tpl.figure()
    fig.plot(x, y, label="data", width=50, height=15)
    #fig.show()  
    return fig


cli.add_command(budge)

if __name__ == "__main__":
    cli()
