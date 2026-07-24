from rich.table import Table

from budgie.singletons import console, header, logger


def create_table(df, style, display=True):
    table = Table(show_header=True, header_style="bold magenta")
    for column in df.columns:
        table.add_column(column)
    for _, row in df.iterrows():
        table.add_row(*[str(item) for item in row])
    if display:
        console.print(table, style=style)
    return table


def display_startup_message():
    console.print(header, style="bold blue")
    logger.info("Budgie started!")
