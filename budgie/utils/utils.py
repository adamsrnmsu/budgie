from rich.table import Table

from budgie.singletons import console, header, logger


def display_dataframe(df, style):
    table = Table(show_header=True, header_style="bold magenta")
    for column in df.columns:
        table.add_column(column)
    for _, row in df.iterrows():
        table.add_row(*[str(item) for item in row])
    console.print(table, style=style)


def display_startup_message():
    console.print(header, style="bold blue")
    logger.info("Budgie started!")
