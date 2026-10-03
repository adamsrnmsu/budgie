"""
Budgie CLI.

Thin front-end over the presentation-independent engine in ``budgie.core``. Each
command loads inputs, calls the engine, and renders results with rich (and
optionally matplotlib figures). No budgeting math lives here.

**Nothing heavy is imported at module scope.** Click has to import this file just
to build the command tree, so every engine and rendering import lives inside the
command that needs it. Importing numpy, holidays and rich up here put roughly a
second between typing ``budgie`` and seeing the help text.
"""

import csv
from datetime import date
from pathlib import Path

import click

# Stoplight glyph + rich color per signal, keyed by Signal.name so rendering the
# table never has to import the engine's enum.
_SIGNAL_STYLE = {
    "GREEN": ("●", "green", "GOOD"),
    "YELLOW": ("●", "yellow", "CAUTION"),
    "RED": ("●", "red", "BAD"),
    "BLUE": ("●", "blue", "NO CHANGE"),
}

THIS_FILE = Path(__file__).resolve()
THIS_DIR = THIS_FILE.parent


def _style(signal) -> tuple[str, str, str]:
    """(glyph, rich color, word) for a :class:`budgie.core.signals.Signal`."""
    return _SIGNAL_STYLE[signal.name]


def _sample(name: str) -> str:
    """Path to a bundled sample file, used when there's no workspace."""
    return str(THIS_DIR / "tests" / name)


# Which project `--project` named, if any. Process-global because every command
# resolves its inputs through the helpers below rather than passing a workspace
# around, and the flag has to reach all of them. Set once at parse time by
# `_project_option`, so nothing else can quietly change which budget is in play.
_SELECTED_PROJECT: str | None = None


def _remember_project(ctx, param, value):
    """Record ``--project`` at parse time (the option exposes no value)."""
    global _SELECTED_PROJECT
    if value:
        _SELECTED_PROJECT = value
    return value


def _forget_project() -> None:
    """Clear the selection at the start of each invocation.

    A one-shot CLI process would never notice, but anything that calls `cli`
    more than once in a process -- the test suite, an embedding front-end --
    would otherwise carry one command's `--project` into the next and quietly
    read the wrong budget.
    """
    global _SELECTED_PROJECT
    _SELECTED_PROJECT = None


_project_option = click.option(
    "--project",
    default=None,
    callback=_remember_project,
    expose_value=False,
    help="Which project under budget/ to use, when there is more than one.",
)


def _workspace():
    """The workspace this invocation should use, honouring ``--project``."""
    from budgie.core.workspace import find_workspace

    return find_workspace(project=_SELECTED_PROJECT)


def _input(key: str, override, sample: str):
    """Resolve an input path: explicit option > workspace file > bundled sample.

    Click options all default to None now, so "the user said nothing" is
    distinguishable from "the user asked for the default" -- that's what lets a
    workspace supply the default without the option always overriding it.
    """
    if override:
        return str(override)
    workspace = _workspace()
    if workspace:
        resolved = workspace.resolve(key)
        if resolved:
            return resolved
    return _sample(sample)


def _actuals_options(func):
    """The spend-reading options shared by `forecast` and `monthly`."""
    for option in reversed(
        [
            click.option(
                "--actuals",
                "actuals_csv",
                default=None,
                type=click.Path(exists=True),
                help="Tidy CSV (name,month,hours) of real monthly spend; turns the forecast "
                "into an estimate at completion [default: the project's, else none].",
            ),
            click.option(
                "--weekly",
                "weekly_csv",
                default=None,
                type=click.Path(exists=True),
                help="CSV (name,week,hours_to_date) of cumulative hours through an ISO week; "
                "wins over --actuals [default: the project's, else none].",
            ),
            click.option(
                "--as-of",
                type=click.DateTime(formats=["%Y-%m-%d"]),
                default=None,
                help="Ignore spend readings dated after this [default: use each person's latest].",
            ),
            click.option(
                "--ignore-actuals",
                is_flag=True,
                default=None,
                help="Forecast the full-year plan even if the project has actuals.",
            ),
        ]
    ):
        func = option(func)
    return func


def _workspace_input(key: str):
    """The project's file for ``key`` if it exists, else None.

    Used for genuinely optional inputs (actuals, costs) where falling back to a
    bundled sample would silently invent data.
    """
    workspace = _workspace()
    return workspace.resolve(key) if workspace else None


def _plan_for_allocations(plan_csv):
    """``(path, plan)`` for hours/emails -- ``(None, None)`` when there's no plan.

    Project file or nothing, never the bundled sample: the sample plan names
    different people than the sample allocations, so falling back to it would
    invent a team.
    """
    plan_csv = plan_csv or _workspace_input("plan")
    if not plan_csv:
        return None, None
    from budgie.core.plan import load_plan

    return plan_csv, load_plan(plan_csv)


def _on_plan(people, span, ph):
    """The team with hours from the project's plan.csv, warnings printed.

    The same rule the Snapshot (and so the TUI and perch) applies: the plan
    sets the hours, people.csv the rate and spread. Project plan or nothing,
    as for ``hours``. Without a plan the team comes back unchanged.
    """
    from budgie.core.allocation import pto_overrides
    from budgie.core.project import people_on_plan
    from budgie.singletons import console

    _, plan = _plan_for_allocations(None)
    alloc_csv = _workspace_input("allocations") if plan else None
    people, warnings = people_on_plan(
        people, plan, span, ph.pto_days, pto_overrides(alloc_csv) if alloc_csv else None
    )
    for warning in warnings:
        console.print(f"[yellow]⚠ {warning}[/yellow]")
    return people


def _no_project_message() -> str:
    """What to say when no workspace resolved.

    Three different problems wear the same "no workspace" result, and they want
    different advice: a name that matched nothing, a choice nobody made, and no
    projects at all. Telling someone who has two budgets to run `budgie init` is
    just wrong, and so is saying it to someone who merely typo'd a name.
    """
    from budgie.core.workspace import available_projects

    projects = available_projects()
    names = "\n".join(f"  [bold]{p.name}[/bold]" for p in projects)

    if _SELECTED_PROJECT:
        missing = f"No project called [bold]{_SELECTED_PROJECT}[/bold]."
        return f"{missing}\n\nThere is:\n{names}" if projects else missing
    if len(projects) > 1:
        return (
            f"Several projects to choose from:\n{names}\n\n"
            "Pick one with [bold]--project NAME[/bold], or cd into it."
        )
    return "Run [bold]budgie init[/bold] to start a project with your own numbers."


def _budget_arg(override):
    """Resolve --budget: explicit value > a number in budgie.yaml > budget.csv."""
    if override is not None:
        return override
    from budgie.core.project import budget_source

    return budget_source(_workspace())


def _setting(key: str, override, default):
    """Resolve a scalar setting: explicit option > workspace > built-in default."""
    if override is not None:
        return override
    workspace = _workspace()
    if workspace:
        return workspace.setting(key, default)
    return default


SAMPLE_YEAR = 2026  # the bundled sample files are dated in 2026


def _today() -> date:
    # Local calendar date is what a budget year is measured in.
    return date.today()  # noqa: DTZ011


def _span(year):
    """The money year: --year, else the project's ``year``, else the year that
    contains today -- or the samples' 2026 when there is no project at all."""
    from budgie.core.calendar import current_year, year_span

    workspace = _workspace()
    start = workspace.setting("year_start", "01-01") if workspace else "01-01"
    default = current_year(start, _today()) if workspace else SAMPLE_YEAR
    return year_span(_setting("year", year, default), start)


# Mistakes in the inputs, not bugs: these get one line instead of a traceback.
_INPUT_ERRORS = (ValueError, FileNotFoundError, KeyError, csv.Error)


class _Budgie(click.Group):
    """The group, plus one place that turns an input mistake into one line.

    Every command reads hand-edited files, so a typo is the common failure and a
    traceback the wrong answer to it. ``-v`` keeps the traceback for debugging.
    """

    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except _INPUT_ERRORS as exc:
            if ctx.params.get("verbose"):
                raise
            _fail(exc)
            ctx.exit(1)


def _fail(exc: Exception) -> None:
    """``error: <message>``, then ``see: budgie guide <topic>`` if a file is named."""
    from budgie.core.workspace import INPUTS

    if isinstance(exc, FileNotFoundError) and exc.filename:
        message, filename = f"no such file: {exc.filename}", Path(exc.filename).name
    else:
        # KeyError's str() is the repr of the key; everything else is the message.
        message = f"missing {exc}" if isinstance(exc, KeyError) else str(exc)
        # Loader messages lead with the file: "plan.csv line 3: ...".
        filename = message.split(" ", 1)[0].rstrip(":")
    click.secho(f"error: {message}", fg="red", err=True)
    topic = {name: key for key, (name, *_) in INPUTS.items()}.get(filename)
    if topic:
        click.echo(f"see: budgie guide {topic}", err=True)


@click.group(cls=_Budgie, invoke_without_command=True, add_help_option=False)
@click.option(
    "-v", "--verbose", is_flag=True, help="Show DEBUG logging from budgie's internals."
)
@click.option(
    "-h", "--help", "show_help", is_flag=True, help="Show this message and exit."
)
@click.pass_context
def cli(ctx, verbose, show_help):
    """Budgie -- the ultimate budget companion."""
    from budgie.singletons import set_verbose

    # Runs before the subcommand's own options are parsed, so this clears the
    # previous invocation's selection without discarding this one's.
    _forget_project()
    set_verbose(verbose)

    # Click's own group help is a flat alphabetical list, which tells a new user
    # nothing about what to run second. `budgie` and `budgie --help` both render
    # the grouped overview instead; subcommands keep click's normal --help.
    if show_help or ctx.invoked_subcommand is None:
        from budgie.core.workspace import find_workspace
        from budgie.guide_ui import render_overview

        workspace = find_workspace()
        render_overview(
            in_project=workspace is not None,
            project_root=workspace.root if workspace else None,
        )
        ctx.exit()


@click.command()
@click.option(
    "--people",
    "people_csv",
    default=None,
    help="CSV of team members (name, hourly_cost, and util_*/hours_* columns) "
    "[default: the project's, else bundled sample].",
)
@click.option(
    "--year",
    default=None,
    type=int,
    help="Year (fiscal when the project sets year_start) "
    "[default: the project's, else this year].",
)
@click.option(
    "--pto",
    default=None,
    type=float,
    help="PTO/sick days to subtract per person [default: 0].",
)
@click.option(
    "--iterations",
    default=None,
    type=int,
    help="Monte Carlo iterations [default: 10000].",
)
@click.option(
    "--seed", default=None, type=int, help="RNG seed for reproducible simulation."
)
@click.option(
    "--plots/--no-plots",
    default=False,
    help="Write montecarlo.png and forecast.png figures.",
)
@click.option(
    "--out-dir",
    default=".",
    show_default=True,
    help="Directory for figure output when --plots is set.",
)
@click.option(
    "--costs",
    "costs_csv",
    default=None,
    type=click.Path(exists=True),
    help="CSV of non-labor costs (materials, licences, travel) to include.",
)
@click.option(
    "--budget",
    "budget_arg",
    default=None,
    help="Budget to signal against: a number, or a CSV of dated revisions.",
)
@_actuals_options
@_project_option
def forecast(
    people_csv,
    year,
    pto,
    iterations,
    seed,
    plots,
    out_dir,
    costs_csv,
    budget_arg,
    actuals_csv,
    weekly_csv,
    as_of,
    ignore_actuals,
):
    """Forecast team cost with productive-hours + Monte Carlo simulation.

    With spend readings (actuals.csv or weekly.csv) this is an estimate at
    completion: hours already booked, plus a forecast of only the time left.
    """
    from budgie.core.calendar import productive_hours
    from budgie.core.costs import load_costs
    from budgie.core.forecast import forecast as run_forecast
    from budgie.core.loader import load_people
    from budgie.core.montecarlo import simulate
    from budgie.singletons import console, logger
    from budgie.utils.utils import display_startup_message

    display_startup_message()

    # A named --people file is its own team: the project's plan is not for it.
    on_plan = people_csv is None
    people_csv = _input("people", people_csv, "team.csv")
    costs_csv = costs_csv or _workspace_input("costs")
    span = _span(year)
    pto = _setting("pto", pto, 0.0)
    iterations = _setting("iterations", iterations, 10_000)
    seed = _setting("seed", seed, None)
    budget_arg = _budget_arg(budget_arg)

    ph = productive_hours(span, pto_days=pto)
    logger.info(
        f"Productive hours {span.label}: {ph.productive_hours:.0f}"
        + (
            f" (available after {pto:g} PTO days: {ph.available_hours:.0f})"
            if pto
            else ""
        )
    )

    people = load_people(people_csv, productive_hours=ph)
    if on_plan:
        people = _on_plan(people, span, ph)
    costs = load_costs(costs_csv, span=span) if costs_csv else []
    # Loaded up front so its log line lands with the other loading messages
    # rather than interleaving after the tables.
    budget = _budget_from(budget_arg) if budget_arg else None

    # Estimate at completion: with spend readings, the elapsed part of each
    # person's plan is replaced by what they actually booked. Everything below
    # just receives the adjusted people. A file named on the command line beats
    # the project's, whichever kind it is.
    people, readings, _ = _with_actuals(
        people, span, actuals_csv, weekly_csv, as_of, ignore_actuals
    )

    det = run_forecast(people, costs=costs)
    sim = simulate(people, iterations=iterations, seed=seed, costs=costs)
    pct = sim.percentiles()

    if readings:
        _print_eac_note(readings, len(people))
    _print_forecast_table(det, readings)
    if costs:
        _print_costs_table(det)
    _print_montecarlo_summary(sim, pct)
    if budget is not None:
        _print_signal(sim, budget)

    if plots:
        from budgie.plots import forecast_bars, montecarlo_histogram

        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        hist = montecarlo_histogram(sim, out / "montecarlo.png")
        bars = forecast_bars(det, out / "forecast.png")
        console.print(f"[bold]Wrote[/bold] {hist} and {bars}")


def _with_actuals(people, span, actuals_csv, weekly_csv, as_of, ignore_actuals):
    """``(people, readings, observations)``: the team adjusted to the estimate at
    completion, the reading each adjustment used, and the full series.

    With spend readings, the elapsed part of each person's plan is replaced by
    what they actually booked. A file named on the command line beats the
    project's, whichever kind it is. No readings (or ``ignore_actuals``) returns
    the team untouched and empty readings.
    """
    if ignore_actuals:
        return people, {}, {}
    from budgie.core.project import load_observations, readings_files

    actuals_csv, weekly_csv = readings_files(_workspace(), actuals_csv, weekly_csv)
    observations = load_observations(span, actuals_csv, weekly_csv)
    if not observations:
        return people, {}, {}
    from budgie.core.eac import at_completion

    # Project file or nothing, as for `hours`: a sample plan would invent a team.
    _, plan = _plan_for_allocations(None)
    eac = at_completion(
        people,
        observations,
        span,
        as_of=as_of.date() if as_of else None,
        plan=plan,
    )
    return eac.people, eac.readings, observations


def _print_eac_note(readings, team_size):
    """One line saying the table is an estimate at completion, and as of when."""
    from budgie.singletons import console

    dates = sorted({when for when, _ in readings.values()})
    as_of = f"{dates[0]}" if len(dates) == 1 else f"{dates[0]} to {dates[-1]}"
    note = f"[bold]Estimate at completion[/bold] — hours booked as of {as_of}"
    note += ", plus a forecast of the time left."
    if len(readings) < team_size:
        note += (
            f" [dim]{len(readings)} of {team_size} people have readings;"
            " the rest are the full-year plan.[/dim]"
        )
    console.print(note)


def _print_forecast_table(det, readings=None):
    """The per-person table. ``readings`` (name -> (date, spent)) adds Spent."""
    from rich.table import Table

    from budgie.singletons import console

    # With no readings this must render exactly as it did before EAC existed.
    eac = bool(readings)
    table = Table(
        show_header=True,
        header_style="bold magenta",
        title="Estimate at completion" if eac else "Deterministic forecast",
    )
    table.add_column("Name")
    table.add_column("$/hr", justify="right")
    if eac:
        table.add_column("Spent", justify="right")
    table.add_column("At completion" if eac else "Hours", justify="right")
    table.add_column("Cost", justify="right")
    for item in det.line_items:
        spent = []
        if eac:
            reading = readings.get(item.name)
            spent = [f"{reading[1]:,.0f}" if reading else "[dim]—[/dim]"]
        table.add_row(
            item.name,
            f"${item.hourly_cost:,.0f}",
            *spent,
            f"{item.hours:,.0f}",
            f"${item.cost:,.0f}",
        )
    table.add_section()
    # Labor only -- this table's rows are people, so its total must be the sum
    # of those rows. Non-labor is totalled in its own table.
    total_spent = sum(hours for _, hours in (readings or {}).values())
    table.add_row(
        "[bold]Total[/bold]",
        "",
        *([f"[bold]{total_spent:,.0f}[/bold]"] if eac else []),
        f"[bold]{det.total_hours:,.0f}[/bold]",
        f"[bold]${det.labor_cost:,.0f}[/bold]",
    )
    console.print(table)


def _budget_from(arg):
    """A --budget argument is either a number or a path to a revisions CSV."""
    from budgie.core.budget import coerce_budget

    try:
        return coerce_budget(float(arg))
    except ValueError:
        return coerce_budget(Path(arg))


def _print_costs_table(det):
    from rich.table import Table

    from budgie.core.costs import by_category
    from budgie.singletons import console

    table = Table(
        show_header=True, header_style="bold magenta", title="Non-labor costs"
    )
    table.add_column("Item")
    table.add_column("Category")
    table.add_column("When")
    table.add_column("Total", justify="right")
    for item in det.cost_items:
        when = f"{item.when:%b %-d}" + (" (monthly)" if item.recurring else "")
        table.add_row(item.name, item.category, when, f"${item.total:,.0f}")
    table.add_section()
    for category, amount in sorted(by_category(det.cost_items).items()):
        table.add_row(f"[dim]{category}[/dim]", "", "", f"[dim]${amount:,.0f}[/dim]")
    table.add_section()
    table.add_row(
        "[bold]Non-labor[/bold]", "", "", f"[bold]${det.non_labor_cost:,.0f}[/bold]"
    )
    table.add_row(
        "[bold]Labor + non-labor[/bold]", "", "", f"[bold]${det.total_cost:,.0f}[/bold]"
    )
    console.print(table)


def _print_signal(sim, budget):
    from budgie.core.signals import evaluate
    from budgie.singletons import console

    # Signal against the budget as it stands now, not the original baseline.
    result = evaluate(sim, budget.latest)
    _, color, word = _style(result.signal)
    if budget.has_revisions:
        console.print(
            f"[dim]Budget: original ${budget.original:,.0f} → current "
            f"${budget.latest:,.0f} ({budget.net_change:+,.0f} over "
            f"{len(budget.revisions)} revisions)[/dim]"
        )
    console.print(f"[{color}]●[/{color}] [bold]{word}[/bold] — {result.rationale}")


def _print_montecarlo_summary(sim, pct):
    from budgie.singletons import console

    console.print(
        f"[bold]Monte Carlo[/bold] ({sim.iterations:,} sims):  "
        f"P10 [green]${pct[10]:,.0f}[/green]  |  "
        f"P50 [green]${pct[50]:,.0f}[/green]  |  "
        f"P90 [green]${pct[90]:,.0f}[/green]"
    )
    console.print(f"mean ${sim.mean:,.0f}   std ${sim.std:,.0f}")


@click.command()
@click.option(
    "--people",
    "people_csv",
    default=None,
    help="CSV of team members (name, hourly_cost, and util_*/hours_* columns) "
    "[default: the project's, else bundled sample].",
)
@_project_option
def tui(people_csv):
    """Launch the interactive TUI to explore forecasts live."""
    from budgie.tui import run

    # No _input() here: the TUI finds the project itself, so passing a resolved
    # sample path would stop it ever seeing the project's people.csv.
    run(people_csv)


@click.command()
@click.option(
    "--allocations",
    "alloc_csv",
    default=None,
    help="CSV of allocations (name, fte, hours_spent, optional email/pto_days) "
    "[default: the project's, else bundled sample].",
)
@click.option(
    "--year",
    default=None,
    type=int,
    help="Year (fiscal when the project sets year_start) "
    "[default: the project's, else this year].",
)
@click.option(
    "--pto",
    default=None,
    type=float,
    help="PTO/sick days subtracted from the ceiling [default: 0].",
)
@click.option(
    "--plan",
    "plan_csv",
    default=None,
    help="CSV of allocation changes (name, effective_date, fte); when present it "
    "sets allocated hours instead of the flat fte [default: the project's, else none].",
)
@_project_option
def hours(alloc_csv, year, pto, plan_csv):
    """Show each person's allocated / spent / remaining hours from their FTE."""
    from budgie.core.allocation import load_allocations
    from budgie.core.calendar import productive_hours
    from budgie.singletons import console, logger
    from budgie.utils.utils import display_startup_message

    display_startup_message()
    alloc_csv = _input("allocations", alloc_csv, "allocations.csv")
    span = _span(year)
    pto = _setting("pto", pto, 0.0)

    from budgie.core.project import (
        load_observations,
        readings_files,
        spent_to_date,
        with_readings,
    )

    ph = productive_hours(span, pto_days=pto)
    plan_csv, plan = _plan_for_allocations(plan_csv)
    allocs = load_allocations(alloc_csv, available_hours=ph, plan=plan)
    # The project's latest reading is the spent figure, as in `emails`.
    readings = load_observations(span, *readings_files(_workspace()))
    allocs = with_readings(allocs, spent_to_date(readings))
    logger.info(f"Available hours {span.label}: {ph.available_hours:,.0f} (1.0 FTE)")
    _print_hours_table(allocs)
    if plan_csv:
        console.print(
            f"[dim]Allocated hours come from {Path(plan_csv).name}; "
            "FTE is the year average.[/dim]"
        )


@click.command()
@click.option(
    "--allocations",
    "alloc_csv",
    default=None,
    help="CSV of allocations (name, fte, hours_spent, optional email/pto_days) "
    "[default: the project's, else bundled sample].",
)
@click.option(
    "--year",
    default=None,
    type=int,
    help="Year (fiscal when the project sets year_start) "
    "[default: the project's, else this year].",
)
@click.option(
    "--pto",
    default=None,
    type=float,
    help="PTO/sick days subtracted from the ceiling [default: 0].",
)
@click.option(
    "--out-dir",
    default="emails",
    show_default=True,
    help="Directory to write per-person email drafts into.",
)
@click.option(
    "--preview/--no-preview",
    default=True,
    help="Print the first draft to the terminal.",
)
@click.option(
    "--html/--plain",
    "as_html",
    default=True,
    show_default=True,
    help="Outlook-ready .eml drafts with an embedded burn-down chart, or plain .txt.",
)
@click.option(
    "--as-of",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="Date to measure burn-down against [default: today].",
)
@click.option(
    "--actuals",
    "actuals_csv",
    default=None,
    type=click.Path(exists=True),
    help="Tidy CSV (name,month,hours) of real monthly spend, for a true burn-down curve.",
)
@click.option(
    "--weekly",
    "weekly_csv",
    default=None,
    type=click.Path(exists=True),
    help="CSV (name,week,hours_to_date) of cumulative hours through an ISO week.",
)
@click.option(
    "--plan",
    "plan_csv",
    default=None,
    help="CSV of allocation changes (name, effective_date, fte); when present it "
    "sets allocated hours instead of the flat fte [default: the project's, else none].",
)
@_project_option
def emails(
    alloc_csv,
    year,
    pto,
    out_dir,
    preview,
    as_html,
    as_of,
    actuals_csv,
    weekly_csv,
    plan_csv,
):
    """Generate a personalized hours-remaining email draft for each person.

    Writes draft files only -- nothing is sent.
    """
    from budgie.core.allocation import load_allocations
    from budgie.core.calendar import productive_hours
    from budgie.emails import render_email, write_drafts
    from budgie.singletons import console
    from budgie.utils.utils import display_startup_message

    display_startup_message()
    alloc_csv = _input("allocations", alloc_csv, "allocations.csv")
    span = _span(year)
    pto = _setting("pto", pto, 0.0)
    from budgie.core.project import readings_files

    actuals_csv, weekly_csv = readings_files(_workspace(), actuals_csv, weekly_csv)

    ph = productive_hours(span, pto_days=pto)
    _, plan = _plan_for_allocations(plan_csv)
    allocs = load_allocations(alloc_csv, available_hours=ph, plan=plan)

    statuses = _burndown_statuses(allocs, span, as_of, actuals_csv, weekly_csv, plan)

    if as_html:
        paths, charts_dir = _write_html_emails(statuses, span, out_dir)
    else:
        paths, charts_dir = write_drafts(statuses, span.label, out_dir), None

    console.print(
        f"[bold]Wrote {len(paths)} draft(s)[/bold] to {out_dir}/ (review before sending)"
    )
    for path in paths:
        console.print(f"  • {path}")
    if charts_dir:
        console.print(f"[dim]Burn-down charts in {charts_dir}/[/dim]")

    if preview and statuses:
        # The plain-text body is the readable one in a terminal, and it is the
        # .eml's own text/plain part -- so previewing it is honest either way.
        console.rule("Preview" + (" (text part of the .eml)" if as_html else ""))
        console.print(
            render_email(
                statuses[0].allocation, span.label, pace=statuses[0].required_pace
            ).as_text()
        )


def _burndown_statuses(
    allocs, span, as_of, actuals_csv=None, weekly_csv=None, plan=None
):
    """Build a BurndownStatus per person, using real spend readings if given.

    Both mail formats need this now: the plain-text draft carries the required
    pace, which is measured against the working days left after the as-of date.
    """
    from budgie.core.burndown import burndown
    from budgie.core.project import load_observations

    # Real spend readings turn the interpolated burn-down into a true curve.
    observations = load_observations(span, actuals_csv, weekly_csv)

    as_of_date = as_of.date() if as_of else None
    statuses = []
    for alloc in allocs:
        obs = observations.get(alloc.name)
        # Never chart a reading dated after the as-of date.
        if obs and as_of_date:
            obs = [o for o in obs if o[0] <= as_of_date]
        statuses.append(
            burndown(
                alloc,
                span,
                as_of=as_of_date,
                observations=obs,
                plan=plan,
            )
        )
    return statuses


def _write_html_emails(statuses, span, out_dir):
    """Render a burn-down chart per person and write Outlook-ready .eml drafts."""
    from budgie.emails import slug, write_eml_drafts
    from budgie.plots import burndown_chart

    out = Path(out_dir)
    charts_dir = out / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    charts = {}
    for status in statuses:
        name = status.allocation.name
        chart_path = burndown_chart(status, charts_dir / f"{slug(name)}.png")
        charts[name] = chart_path.read_bytes()

    return write_eml_drafts(statuses, span.label, out, charts=charts), charts_dir


def _print_hours_table(allocs):
    from rich.table import Table

    from budgie.singletons import console

    table = Table(
        show_header=True, header_style="bold magenta", title="FTE hours remaining"
    )
    table.add_column("Name")
    table.add_column("FTE", justify="right")
    table.add_column("Allocated", justify="right")
    table.add_column("Spent", justify="right")
    table.add_column("Remaining", justify="right")
    table.add_column("Used", justify="right")
    for a in allocs:
        remaining = f"{a.hours_remaining:,.0f}"
        if a.is_over_budget:
            remaining = f"[bold red]{remaining}[/bold red]"
        elif a.fraction_used >= 0.9:
            remaining = f"[yellow]{remaining}[/yellow]"
        table.add_row(
            a.name,
            f"{a.fte:.2f}",
            f"{a.allocated_hours:,.0f}",
            f"{a.hours_spent:,.0f}",
            remaining,
            f"{a.fraction_used:.0%}",
        )
    console.print(table)


@click.command()
@click.option(
    "--config",
    "config_path",
    default=None,
    help="YAML config describing a budget and named scenarios to compare "
    "[default: the project's, else bundled sample].",
)
@_project_option
def scenario(config_path):
    """Compare what-if scenarios side by side, with a stoplight vs the budget."""
    from budgie.core.scenario import run_scenarios
    from budgie.singletons import console, logger
    from budgie.utils.utils import display_startup_message

    display_startup_message()
    config_path = _input("scenarios", config_path, "scenarios.yaml")

    results, budget = run_scenarios(config_path)
    logger.info(f"Budget target: ${budget:,.0f}   (baseline: {results[0].name})")
    _print_scenario_table(results, budget)
    console.print("\n[bold]Signals[/bold]")
    for r in results:
        _, color, word = _style(r.signal.signal)
        console.print(
            f"  [{color}]●[/{color}] [bold]{r.name}[/bold] — {word}: {r.signal.rationale}"
        )


def _print_scenario_table(results, budget):
    from rich.table import Table

    from budgie.singletons import console

    table = Table(
        show_header=True, header_style="bold magenta", title="Scenario comparison"
    )
    table.add_column("")
    table.add_column("Scenario")
    table.add_column("Total (P50 det.)", justify="right")
    table.add_column("vs base", justify="right")
    table.add_column("P90", justify="right")
    table.add_column("P(over budget)", justify="right")
    for r in results:
        _, color, _word = _style(r.signal.signal)
        delta = "—" if r.cost_delta == 0 else f"{r.cost_delta:+,.0f}"
        table.add_row(
            f"[{color}]●[/{color}]",
            r.name,
            f"${r.forecast.total_cost:,.0f}",
            delta,
            f"${r.sim.percentile(90):,.0f}",
            f"{r.signal.prob_over_budget:.0%}",
        )
    console.print(table)


@click.command()
@click.option(
    "--people",
    "people_csv",
    default=None,
    help="CSV of team members [default: the project's, else bundled sample].",
)
@click.option(
    "--year",
    default=None,
    type=int,
    help="Year (fiscal when the project sets year_start) "
    "[default: the project's, else this year].",
)
@click.option(
    "--pto", default=None, type=float, help="PTO/sick days per person [default: 0]."
)
@click.option(
    "--iterations",
    default=None,
    type=int,
    help="Monte Carlo iterations [default: 10000].",
)
@click.option("--seed", default=None, type=int, help="RNG seed.")
@click.option(
    "--budget",
    "budget_arg",
    default=None,
    help="Budget for the fan chart: a number, or a CSV of dated revisions.",
)
@click.option(
    "--costs",
    "costs_csv",
    default=None,
    type=click.Path(exists=True),
    help="CSV of non-labor costs to include in the monthly totals.",
)
@click.option(
    "--plots/--no-plots", default=False, help="Write fan.png and monthly.png."
)
@click.option(
    "--out-dir", default=".", show_default=True, help="Directory for figures."
)
@_actuals_options
@_project_option
def monthly(
    people_csv,
    year,
    pto,
    iterations,
    seed,
    budget_arg,
    costs_csv,
    plots,
    out_dir,
    actuals_csv,
    weekly_csv,
    as_of,
    ignore_actuals,
):
    """Break the year into months: cost per month and a cumulative fan chart.

    With spend readings (actuals.csv or weekly.csv) the months already past carry
    the hours actually booked, and only the rest of the year is simulated.
    """
    from budgie.core.calendar import productive_hours
    from budgie.core.costs import load_costs
    from budgie.core.loader import load_people
    from budgie.core.monthly import monthly_forecast, monthly_simulation
    from budgie.singletons import console, logger
    from budgie.utils.utils import display_startup_message

    display_startup_message()
    # A named --people file is its own team: the project's plan is not for it.
    on_plan = people_csv is None
    people_csv = _input("people", people_csv, "team.csv")
    span = _span(year)
    pto = _setting("pto", pto, 0.0)
    iterations = _setting("iterations", iterations, 10_000)
    seed = _setting("seed", seed, None)
    budget_arg = _budget_arg(budget_arg)

    ph = productive_hours(span, pto_days=pto)
    people = load_people(people_csv, productive_hours=ph)
    if on_plan:
        people = _on_plan(people, span, ph)
    costs = load_costs(costs_csv, span=span) if costs_csv else []
    budget = _budget_from(budget_arg) if budget_arg else None

    people, readings, observations = _with_actuals(
        people, span, actuals_csv, weekly_csv, as_of, ignore_actuals
    )
    actuals = None
    if readings:
        from budgie.core.monthly import Actuals

        # Project file or nothing, as for `hours`: a sample plan would invent a team.
        _, plan = _plan_for_allocations(None)
        actuals = Actuals(readings, observations, plan)
        _print_eac_note(readings, len(people))

    mf = monthly_forecast(
        people,
        span,
        pto_days=pto,
        costs=costs,
        actuals=actuals,
    )
    sim = monthly_simulation(
        people,
        span,
        pto_days=pto,
        iterations=iterations,
        seed=seed,
        costs=costs,
        actuals=actuals,
    )
    logger.info(
        f"{len(people)} people, {span.label} split into months by working-day share"
    )
    _print_monthly_table(mf, sim, budget.latest if budget else None)

    if plots:
        from budgie.plots import fan_chart, monthly_cost_bars

        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        f1 = fan_chart(sim, out / "fan.png", budget=budget)
        f2 = monthly_cost_bars(mf, out / "monthly.png")
        console.print(f"[bold]Wrote[/bold] {f1} and {f2}")


def _print_monthly_table(mf, sim, budget):
    from rich.table import Table

    from budgie.core.monthly import month_names
    from budgie.singletons import console

    p10, p50, p90 = sim.band(10), sim.band(50), sim.band(90)
    table = Table(
        show_header=True,
        header_style="bold magenta",
        title=f"Monthly breakdown {mf.span.label}",
    )
    table.add_column("Month")
    table.add_column("Hours", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("Cumulative", justify="right")
    table.add_column("P10", justify="right")
    table.add_column("P90", justify="right")
    cum = mf.cumulative_costs
    for i, name in enumerate(month_names(mf.span)):
        over = budget is not None and p50[i] > budget
        cumulative_cell = f"${cum[i]:,.0f}"
        if over:
            cumulative_cell = f"[red]{cumulative_cell}[/red]"
        table.add_row(
            name,
            f"{mf.hours[i]:,.0f}",
            f"${mf.costs[i]:,.0f}",
            cumulative_cell,
            f"${p10[i]:,.0f}",
            f"${p90[i]:,.0f}",
        )
    table.add_section()
    table.add_row(
        "[bold]Year[/bold]",
        f"[bold]{sum(mf.hours):,.0f}[/bold]",
        f"[bold]${mf.total_cost:,.0f}[/bold]",
        "",
        f"${p10[-1]:,.0f}",
        f"${p90[-1]:,.0f}",
    )
    console.print(table)


def _interactive() -> bool:
    """Whether there's a terminal to prompt at."""
    import sys

    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        # A closed or substituted stdin isn't a terminal either.
        return False


def _ask_project_name(default: str) -> str:
    """Prompt for the project name, falling back to ``default``.

    Only asks when there's a terminal to ask: piped into a script or run from
    CI, an interactive prompt would abort on EOF and turn `budgie init` into
    something you can't automate.
    """
    if not _interactive():
        return default
    name = click.prompt("Project name", default=default, show_default=True)
    return name.strip() or default


@click.command()
@click.argument("name", required=False)
@click.option(
    "--year", default=None, type=int, help="Year to scaffold for [default: this year]."
)
@click.option(
    "--year-start",
    default="01-01",
    show_default=True,
    help='First day of the money year: "01-01" calendar, "10-01" federal fiscal '
    "(--year 2027 is then Oct 2026-Sep 2027).",
)
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite files that already exist (off by default -- init never "
    "silently replaces your numbers).",
)
@click.option(
    "--here",
    is_flag=True,
    help="Scaffold into the current directory instead of under budget/.",
)
def init(name, year, year_start, force, here):
    """Create a Budgie project: a folder with budgie.yaml and starter inputs.

    Projects live together under budget/, so NAME picks which one -- budget/fy27
    for `budgie init fy27`. Asked for if you don't pass it. Keeping them in one
    place is what lets you hold next year's budget and this one at the same
    time, and what the TUI browses. Use --here to put the files loose in the
    current directory instead.
    """
    from budgie.core.calendar import current_year, year_start_month
    from budgie.core.scaffold import DEFAULT_PROJECT_NAME, PROJECTS_DIR, init_workspace
    from budgie.core.workspace import CONFIG_NAME, forget_workspaces
    from budgie.singletons import console
    from budgie.utils.utils import display_startup_message

    display_startup_message()
    try:
        year_start_month(year_start)
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="--year-start") from None
    year = year or current_year(year_start, _today())
    if here and name:
        raise click.UsageError("give a name or --here, not both")

    if here:
        target = Path(".")
    else:
        chosen = name or _ask_project_name(DEFAULT_PROJECT_NAME)
        target = Path(PROJECTS_DIR) / chosen

    written, skipped = init_workspace(
        target, year=year, overwrite=force, year_start=year_start
    )
    forget_workspaces()

    root = Path(target).resolve()
    console.print(f"[bold]Project at[/bold] {root}")
    for path in written:
        console.print(f"  [green]+[/green] {path.name}")
    for path in skipped:
        console.print(f"  [dim]· {path.name} (already there, left alone)[/dim]")
    if skipped and not force:
        console.print("[dim]Pass --force to overwrite the existing files.[/dim]")

    if not here:
        console.print(f"\n[bold cyan]cd {target}[/bold cyan] to work in it.")

    console.print(
        f"\nEdit the CSVs, then run [bold]budgie status[/bold] to check them.\n"
        f"Settings like year, PTO and budget live in [bold]{CONFIG_NAME}[/bold]."
    )


@click.command("delete")
@click.argument("name", required=False)
@click.option(
    "--yes",
    is_flag=True,
    help="Skip the confirmation prompt (for scripts -- there is no undo).",
)
def delete_project_cmd(name, yes):
    """Delete a project and everything in it. There is no undo.

    NAME is a project under budget/. Without it, the one project here is used --
    and if there are several, they're listed rather than guessed between, since
    deleting the wrong budget is not a recoverable mistake.
    """
    from budgie.core.scaffold import delete_project
    from budgie.core.workspace import available_projects, forget_workspaces
    from budgie.singletons import console
    from budgie.utils.utils import display_startup_message

    display_startup_message()
    projects = available_projects()
    if not projects:
        console.print("[yellow]No projects here to delete.[/yellow]")
        raise SystemExit(1)

    if name:
        chosen = next((p for p in projects if p.name == name), None)
        if chosen is None:
            listed = "\n".join(f"  [bold]{p.name}[/bold]" for p in projects)
            console.print(
                f"[red]No project called {name}.[/red]\n\nThere is:\n{listed}"
            )
            raise SystemExit(1)
    elif len(projects) > 1:
        listed = "\n".join(f"  [bold]{p.name}[/bold]" for p in projects)
        console.print(
            f"Several projects here -- name the one to delete:\n{listed}\n\n"
            "[dim]budgie delete NAME[/dim]"
        )
        raise SystemExit(1)
    else:
        chosen = projects[0]

    files = sum(1 for p in chosen.root.rglob("*") if p.is_file())
    console.print(
        f"[bold]{chosen.name}[/bold] — {chosen.root}\n"
        f"{files} file(s), including your numbers. [red]This cannot be undone.[/red]"
    )
    # An explicit --yes is the scriptable path; otherwise make them type it.
    # `click.confirm` on a y/N default is too easy to hit by reflex for
    # something with no undo, so the project's own name is the confirmation.
    if not yes:
        if not _interactive():
            console.print(
                "[yellow]Not a terminal -- pass --yes to delete without asking.[/yellow]"
            )
            raise SystemExit(1)
        typed = click.prompt(
            f"Type {chosen.name!r} to confirm", default="", show_default=False
        )
        if typed.strip() != chosen.name:
            console.print("[yellow]Left alone.[/yellow]")
            raise SystemExit(1)

    try:
        removed = delete_project(chosen.root)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc
    forget_workspaces()
    console.print(f"[green]Deleted[/green] {chosen.name} ({len(removed)} file(s)).")


@click.command()
@click.argument("topic", required=False)
def guide(topic):
    """Walk through building a budget, or explain one input file.

    With no argument: the five phases, in order, from nothing to a forecast you
    can act on. With a topic (people, allocations, plan, costs, budget, actuals,
    weekly, scenarios): the columns for that file, an example, and the rules the
    engine applies to it.
    """
    from budgie.core.workspace import find_workspace
    from budgie.guide_ui import (
        render_topic,
        render_unknown_topic,
        render_walkthrough,
        topic_for,
    )

    workspace = find_workspace()
    if topic is None:
        render_walkthrough(in_project=workspace is not None)
        return

    found = topic_for(topic)
    if found is None:
        render_unknown_topic(topic)
        raise SystemExit(1)
    # Showing the real path turns "here's the format" into "here's your file".
    render_topic(found, path=workspace.path_for(found.key) if workspace else None)


@click.command()
@_project_option
def status():
    """Show the current project: which inputs exist, and what feeds what."""
    from budgie.singletons import console
    from budgie.utils.utils import display_startup_message

    display_startup_message()
    workspace = _workspace()
    if workspace is None:
        console.print(
            "[yellow]No budgie.yaml found[/yellow] above "
            f"{Path.cwd()}.\n"
            "Commands are running against the bundled sample data in "
            f"{THIS_DIR / 'tests'}.\n\n" + _no_project_message()
        )
        return

    _print_status_table(workspace)
    missing = [i for i in workspace.inputs() if not i.exists]
    if missing:
        console.print(
            f"[dim]{len(missing)} input(s) not created yet. That's fine -- each "
            f"is only needed by the commands listed against it.[/dim]"
        )
    console.print(f"[dim]Settings from {workspace.config_path}[/dim]")


def _print_status_table(workspace):
    from rich.table import Table

    from budgie.singletons import console

    settings = workspace.settings
    if settings:
        console.print(
            "  ".join(f"[bold]{k}[/bold] {v}" for k, v in sorted(settings.items()))
        )

    table = Table(
        show_header=True,
        header_style="bold magenta",
        title=f"Project inputs — {workspace.root}",
    )
    table.add_column("")
    table.add_column("File")
    table.add_column("Rows", justify="right")
    table.add_column("What it is")
    table.add_column("Used by", style="dim")
    for item in workspace.inputs():
        mark = "[green]✓[/green]" if item.exists else "[dim]·[/dim]"
        name = item.path.name if item.exists else f"[dim]{item.path.name}[/dim]"
        rows = "" if item.rows is None else f"{item.rows}"
        table.add_row(
            mark,
            name,
            rows,
            item.description,
            " ".join(item.used_by),
        )
    console.print(table)


@click.command()
@click.option(
    "--year",
    default=None,
    type=int,
    help="Year (fiscal when the project sets year_start) "
    "[default: the project's, else this year].",
)
@click.option(
    "--pto",
    default=None,
    type=float,
    help="PTO/sick days, to show its effect on the ceiling [default: 0].",
)
@_project_option
def assumptions(year, pto):
    """Print every modelling assumption, its current value, and where it lives.

    Budgie's numbers all fall out of a handful of choices. This shows them in
    one place so you can check them against how your organisation actually
    counts time and money, rather than inferring them from the outputs.
    """
    from budgie.core.calendar import (
        GROSS_ANNUAL_HOURS,
        HOURS_PER_DAY,
        HOURS_PER_WEEK,
        PTO_RULE,
        WEEKS_PER_YEAR,
        explain_pto,
        federal_holiday_workdays,
        productive_hours,
        workdays_in_year,
    )
    from budgie.core.monthly import month_names, month_weights
    from budgie.utils.utils import display_startup_message

    display_startup_message()
    span = _span(year)
    pto = _setting("pto", pto, 0.0)

    ph = productive_hours(span, pto_days=pto)
    weights, names = month_weights(span), month_names(span)
    first, last = span.first, span.last

    # (assumption, current value, where it is set).
    rows = [
        _row(
            "Working week",
            f"{HOURS_PER_WEEK:g} h over {WEEKS_PER_YEAR:g} weeks"
            f" = {GROSS_ANNUAL_HOURS:,.0f} h gross",
            "core/calendar.py",
        ),
        _row(
            "Working day",
            f"{HOURS_PER_DAY:g} h -- converts holiday and PTO days to hours",
            "core/calendar.py",
        ),
        _row(
            "Holidays",
            f"{federal_holiday_workdays(span)} US federal holidays fall Mon-Fri"
            f" in {span.label} (-{ph.holiday_hours:,.0f} h)",
            "core/calendar.py (holidays pkg)",
        ),
        _row(
            "Productive hours",
            f"{ph.productive_hours:,.0f} h -- gross minus holidays",
            "core/calendar.py",
        ),
        _row(
            "PTO",
            f"{pto:g} days (-{ph.pto_hours:,.0f} h)"
            f" -> available {ph.available_hours:,.0f} h",
            "--pto, or a pto_days column",
        ),
        _row("PTO vs part-time", PTO_RULE, "core/calendar.py: PTO_RULE"),
        _row("", explain_pto(ph), ""),
        _row(
            "Working days",
            f"{workdays_in_year(span)} in {span.label}; day-level math spreads"
            " available hours across exactly these",
            "core/calendar.py",
        ),
        _row(
            "Month weights",
            "by working-day share, not 1/12"
            f" ({names[0]} {weights[0]:.1%} ... {names[1]} {weights[1]:.1%})",
            "core/monthly.py",
        ),
        _row(
            "Hours uncertainty",
            "triangular(low, mode, high); the deterministic forecast uses the mode",
            "core/person.py",
        ),
        _row(
            "Cost uncertainty",
            "non-labor lines with low/high sample triangularly too;"
            " blank means known exactly",
            "core/costs.py",
        ),
        _row(
            "Estimate at completion",
            "with actuals, forecast replaces the past with each person's latest"
            " reading; the remainder is their plan x the share of working days"
            " left after it. Spent hours are costed at the current rate;"
            " non-labor lines are not adjusted",
            "core/eac.py, --ignore-actuals",
        ),
        _row(
            "Allocated hours",
            "from plan.csv when the project has one, walked day by day; the FTE"
            " shown is the year average, and anyone the plan doesn't mention"
            " keeps their flat fte from allocations.csv",
            "core/allocation.py, --plan",
        ),
        _row(
            "Burn-down pace",
            f"expectation is a straight line from 0 on {first:%b} {first.day}"
            f" to the full allocation on {last:%b} {last.day}",
            "core/burndown.py",
        ),
        _row(
            "Required pace",
            "remaining hours spread evenly over the working days left,"
            " then divided by a 40 h week to give FTE",
            "core/burndown.py",
        ),
        _row(
            "Signals",
            "GREEN <=10% chance over budget, YELLOW <=40%, RED above;"
            " BLUE if a baseline moved <=2%",
            "core/signals.py",
        ),
        _row(
            "Budget revisions",
            "signals compare against the LATEST revision, not the original",
            "core/budget.py",
        ),
    ]
    _print_assumptions_table(span.label, rows)


def _row(name: str, value: str, source: str) -> tuple[str, str, str]:
    """One row of the assumptions table."""
    return (name, value, source)


def _print_assumptions_table(label, rows):
    from rich.table import Table

    from budgie.singletons import console

    table = Table(
        show_header=True,
        header_style="bold magenta",
        title=f"Assumptions in force for {label}",
        show_lines=False,
    )
    table.add_column("Assumption", style="bold")
    table.add_column("Value")
    table.add_column("Set in", style="dim")
    for name, value, source in rows:
        table.add_row(name, value, source)
    console.print(table)
    console.print(
        "[dim]Change any of these by passing the matching option, or edit the "
        "module named in the last column.[/dim]"
    )


@click.command()
@click.option(
    "--plan",
    "plan_csv",
    default=None,
    help="CSV of allocation changes (name, effective_date, fte) "
    "[default: the project's, else bundled sample].",
)
@click.option(
    "--year",
    default=None,
    type=int,
    help="Year (fiscal when the project sets year_start) "
    "[default: the project's, else this year].",
)
@click.option(
    "--pto", default=None, type=float, help="PTO/sick days per person [default: 0]."
)
@_project_option
def plan(plan_csv, year, pto):
    """Show allocated hours from a date-resolution allocation plan.

    Each row applies from its effective date until the next row for that person,
    so joining mid-year, leaving, and re-planning are all just appended rows.
    """
    from budgie.core.allocation import pto_overrides
    from budgie.core.plan import load_plan
    from budgie.utils.utils import display_startup_message

    display_startup_message()
    plan_csv = _input("plan", plan_csv, "plan.csv")
    span = _span(year)
    pto = _setting("pto", pto, 0.0)

    # A person's own pto_days lives in allocations.csv. `hours` honours it, so
    # this view has to as well or the two disagree about the same plan. Project
    # file only: the bundled sample allocations are a different team.
    alloc_csv = _workspace_input("allocations")
    pto_by_name = pto_overrides(alloc_csv) if alloc_csv else {}

    allocation_plan = load_plan(plan_csv)
    _print_plan_table(allocation_plan, span, pto, pto_by_name)


def _print_plan_table(allocation_plan, span, pto, pto_by_name=None):
    from rich.table import Table

    from budgie.singletons import console

    table = Table(
        show_header=True,
        header_style="bold magenta",
        title=f"Allocation plan {span.label}",
    )
    table.add_column("Name")
    table.add_column("Changes")
    table.add_column("Hours", justify="right")
    total = 0.0
    for name in allocation_plan.names:
        days = (pto_by_name or {}).get(name, pto)
        hours = allocation_plan.allocated_hours(name, span, pto_days=days)
        total += hours
        changes = ", ".join(
            f"{e.effective_date:%b %-d}→{e.fte:g}"
            for e in allocation_plan.changes_for(name)
        )
        table.add_row(name, changes, f"{hours:,.0f}")
    table.add_section()
    table.add_row("[bold]Total[/bold]", "", f"[bold]{total:,.0f}[/bold]")
    console.print(table)


cli.add_command(init)
cli.add_command(delete_project_cmd)
cli.add_command(guide)
cli.add_command(status)
cli.add_command(forecast)
cli.add_command(assumptions)
cli.add_command(plan)
cli.add_command(tui)
cli.add_command(hours)
cli.add_command(emails)
cli.add_command(scenario)
cli.add_command(monthly)

if __name__ == "__main__":
    cli()
