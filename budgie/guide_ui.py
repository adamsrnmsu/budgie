"""
Rich rendering for the help overview and the walkthrough.

A thin adapter over :mod:`budgie.core.guide`, which holds the actual content.
Kept out of ``budgie.py`` because the CLI module is already long, and out of
``core/`` because it imports rich.

Everything here is reachable from ``budgie`` with no arguments, so it must stay
cheap: rich only, no engine imports, no pyfiglet. That keeps the no-argument
path at roughly a tenth of a second.
"""

from __future__ import annotations

from budgie.core.guide import COMMAND_GROUPS, PHASES, TOPICS_BY_KEY, Topic, topic_names
from budgie.singletons import console

# One accent colour, used for anything the user is meant to type.
_CMD = "bold cyan"
_HEAD = "bold"
_DIM = "dim"


def _indented(text: str, left: int, style: str = "") -> None:
    """Print wrapped prose that keeps its indent on continuation lines.

    ``console.print(f"    {text}")`` only indents the first line -- rich wraps
    the rest back to column zero, which turns a tidy list into a ragged one.
    """
    from rich.padding import Padding

    body = f"[{style}]{text}[/{style}]" if style else text
    console.print(Padding(body, (0, 0, 0, left)), highlight=False)


def render_overview(in_project: bool, project_root=None) -> None:
    """The landing screen: what Budgie is, and what to run next."""
    from rich.panel import Panel
    from rich.table import Table

    console.print()
    console.print(
        Panel(
            "Forecast what a team will cost, with honest confidence bounds "
            "around the number.\nA terminal alternative to spreadsheet "
            "budgeting.",
            title="[bold]Budgie[/bold]",
            subtitle=(
                f"[{_DIM}]project: {project_root}[/{_DIM}]"
                if in_project
                else f"[{_DIM}]no project here[/{_DIM}]"
            ),
            border_style="green",
            padding=(1, 2),
        )
    )

    # The single most useful next action, which depends on where they are.
    if in_project:
        console.print(
            f"  Next: [{_CMD}]budgie status[/{_CMD}] to see your inputs, or "
            f"[{_CMD}]budgie forecast[/{_CMD}] for the numbers."
        )
    else:
        console.print(
            f"  Next: [{_CMD}]budgie init my-budget[/{_CMD}] to start a "
            f"project, then [{_CMD}]cd budget/my-budget[/{_CMD}]."
        )
    console.print(
        f"  New here? [{_CMD}]budgie guide[/{_CMD}] walks you through building "
        f"a budget in five steps."
    )
    console.print()

    for heading, blurb, names in COMMAND_GROUPS:
        table = Table(box=None, show_header=False, padding=(0, 2, 0, 2), pad_edge=False)
        table.add_column(style=_CMD, no_wrap=True)
        table.add_column(overflow="fold")
        for name, summary in names:
            table.add_row(name, summary)
        console.print(f"[{_HEAD}]{heading}[/{_HEAD}]  [{_DIM}]{blurb}[/{_DIM}]")
        console.print(table)
        console.print()

    console.print(
        f"  [{_DIM}]budgie COMMAND --help[/{_DIM}] for a command's options   "
        f"[{_DIM}]-v[/{_DIM}] to see what it's doing"
    )
    console.print()


def render_walkthrough(in_project: bool) -> None:
    """All phases, in order, with the current one hinted at."""
    from rich.panel import Panel

    console.print()
    console.print(
        Panel(
            "Building a budget, in order. Each step is small and the ones "
            "marked optional can wait.",
            title="[bold]Budgie walkthrough[/bold]",
            border_style="green",
            padding=(1, 2),
        )
    )

    for phase in PHASES:
        # Phase 1 is done the moment they have a project.
        done = in_project and phase.number == 1
        mark = "[green]✓[/green]" if done else f"[{_HEAD}]{phase.number}[/{_HEAD}]"
        console.print()
        console.print(f"  {mark}  [{_HEAD}]{phase.title}[/{_HEAD}]")
        _indented(phase.goal, 5, style=_DIM)
        console.print()
        for step in phase.steps:
            style = _CMD if step.is_command else "yellow"
            console.print(f"       [{style}]{step.action}[/{style}]")
            _indented(step.why, 9, style=_DIM)
        console.print()

    console.print(
        f"  Then: [{_CMD}]budgie guide <file>[/{_CMD}] for how to fill in any "
        f"one input."
    )
    console.print(f"  [{_DIM}]files: {', '.join(topic_names())}[/{_DIM}]")
    console.print()


def render_topic(topic: Topic, path=None) -> None:
    """How to fill in one input file."""
    from rich.panel import Panel
    from rich.syntax import Syntax
    from rich.table import Table

    tag = f"  [{_DIM}](optional)[/{_DIM}]" if topic.optional else ""
    console.print()
    console.print(
        Panel(
            topic.purpose,
            title=f"[bold]{topic.filename}[/bold] — {topic.title}{tag}",
            border_style="green",
            padding=(1, 2),
        )
    )

    if path is not None:
        state = (
            "[green]exists[/green]"
            if path.is_file()
            else f"[{_DIM}]not created yet[/{_DIM}]"
        )
        console.print(f"  {path}  {state}")
        console.print()

    table = Table(box=None, show_header=True, header_style=_HEAD, padding=(0, 2, 0, 2))
    table.add_column("Column", style=_CMD, no_wrap=True)
    table.add_column("Meaning", overflow="fold")
    for column, meaning in topic.columns:
        table.add_row(column, meaning)
    console.print(table)
    console.print()

    lexer = "yaml" if topic.filename.endswith((".yaml", ".yml")) else "csv"
    console.print(f"  [{_HEAD}]Example[/{_HEAD}]")
    console.print(
        Panel(
            Syntax(topic.example, lexer, background_color="default"),
            border_style=_DIM,
            padding=(0, 2),
        )
    )

    if topic.rules:
        from rich.padding import Padding

        console.print(f"  [{_HEAD}]Worth knowing[/{_HEAD}]")
        # A two-column table rather than a padded string: it's the only way to
        # get a hanging indent, so wrapped text lines up under the first word
        # instead of under the bullet.
        bullets = Table(box=None, show_header=False, padding=(0, 1, 0, 0))
        bullets.add_column(width=1, no_wrap=True)
        bullets.add_column(overflow="fold")
        for rule in topic.rules:
            bullets.add_row("•", rule)
        console.print(Padding(bullets, (0, 0, 0, 4)), highlight=False)
        console.print()

    used = "  ".join(f"[{_CMD}]budgie {c}[/{_CMD}]" for c in topic.used_by)
    console.print(f"  Read by: {used}")
    console.print()


def render_unknown_topic(name: str) -> None:
    """A wrong topic name should list the right ones, not just complain."""
    console.print(f"[red]No guide for {name!r}.[/red]")
    console.print(f"Try one of: [{_CMD}]{', '.join(topic_names())}[/{_CMD}]")
    console.print(f"Or [{_CMD}]budgie guide[/{_CMD}] for the walkthrough.")


def topic_for(name: str) -> Topic | None:
    return TOPICS_BY_KEY.get(name.lower().removesuffix(".csv").removesuffix(".yaml"))
