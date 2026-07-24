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


def _input(key: str, override, sample: str):
    """Resolve an input path: explicit option > workspace file > bundled sample.

    Click options all default to None now, so "the user said nothing" is
    distinguishable from "the user asked for the default" -- that's what lets a
    workspace supply the default without the option always overriding it.
    """
    from budgie.core.workspace import find_workspace

    if override:
        return str(override)
    workspace = find_workspace()
    if workspace:
        resolved = workspace.resolve(key)
        if resolved:
            return resolved
    return _sample(sample)


def _workspace_input(key: str):
    """The project's file for ``key`` if it exists, else None.

    Used for genuinely optional inputs (actuals, costs) where falling back to a
    bundled sample would silently invent data.
    """
    from budgie.core.workspace import find_workspace

    workspace = find_workspace()
    return workspace.resolve(key) if workspace else None


def _budget_arg(override):
    """Resolve --budget: explicit value > a number in budgie.yaml > budget.csv."""
    if override is not None:
        return override
    pinned = _setting("budget", None, None)
    if pinned is not None:
        return pinned
    return _workspace_input("budget")


def _setting(key: str, override, default):
    """Resolve a scalar setting: explicit option > workspace > built-in default."""
    from budgie.core.workspace import find_workspace

    if override is not None:
        return override
    workspace = find_workspace()
    if workspace:
        return workspace.setting(key, default)
    return default


@click.group()
@click.option(
    "-v", "--verbose", is_flag=True, help="Show DEBUG logging from budgie's internals."
)
def cli(verbose):
    """Budgie -- the ultimate budget companion."""
    from budgie.singletons import set_verbose

    set_verbose(verbose)


@click.command()
@click.option(
    "--people",
    "people_csv",
    default=None,
    help="CSV of team members (name, hourly_cost, and util_*/hours_* columns) "
    "[default: the project's, else bundled sample].",
)
@click.option("--year", default=None, type=int, help="Calendar year [default: 2026].")
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
def forecast(
    people_csv, year, pto, iterations, seed, plots, out_dir, costs_csv, budget_arg
):
    """Forecast team cost with productive-hours + Monte Carlo simulation."""
    from budgie.core.calendar import productive_hours
    from budgie.core.costs import load_costs
    from budgie.core.forecast import forecast as run_forecast
    from budgie.core.loader import load_people
    from budgie.core.montecarlo import simulate
    from budgie.singletons import console, logger
    from budgie.utils.utils import display_startup_message

    display_startup_message()

    people_csv = _input("people", people_csv, "team.csv")
    costs_csv = costs_csv or _workspace_input("costs")
    year = _setting("year", year, 2026)
    pto = _setting("pto", pto, 0.0)
    iterations = _setting("iterations", iterations, 10_000)
    seed = _setting("seed", seed, None)
    budget_arg = _budget_arg(budget_arg)

    ph = productive_hours(year, pto_days=pto)
    logger.info(
        f"Productive hours {year}: {ph.productive_hours:.0f}"
        + (
            f" (available after {pto:g} PTO days: {ph.available_hours:.0f})"
            if pto
            else ""
        )
    )

    people = load_people(people_csv, productive_hours=ph)
    costs = load_costs(costs_csv) if costs_csv else []
    # Loaded up front so its log line lands with the other loading messages
    # rather than interleaving after the tables.
    budget = _budget_from(budget_arg) if budget_arg else None

    det = run_forecast(people, costs=costs)
    sim = simulate(people, iterations=iterations, seed=seed, costs=costs)
    pct = sim.percentiles()

    _print_forecast_table(det)
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


def _print_forecast_table(det):
    from rich.table import Table

    from budgie.singletons import console

    table = Table(
        show_header=True, header_style="bold magenta", title="Deterministic forecast"
    )
    table.add_column("Name")
    table.add_column("$/hr", justify="right")
    table.add_column("Hours", justify="right")
    table.add_column("Cost", justify="right")
    for item in det.line_items:
        table.add_row(
            item.name,
            f"${item.hourly_cost:,.0f}",
            f"{item.hours:,.0f}",
            f"${item.cost:,.0f}",
        )
    table.add_section()
    # Labor only -- this table's rows are people, so its total must be the sum
    # of those rows. Non-labor is totalled in its own table.
    table.add_row(
        "[bold]Total[/bold]",
        "",
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
    default=str(THIS_DIR / "tests" / "team.csv"),
    show_default=True,
    help="CSV of team members (name, hourly_cost, and util_*/hours_* columns).",
)
def tui(people_csv):
    """Launch the interactive TUI to explore forecasts live."""
    from budgie.tui import run

    run(people_csv)


@click.command()
@click.option(
    "--allocations",
    "alloc_csv",
    default=None,
    help="CSV of allocations (name, fte, hours_spent, optional email/pto_days) "
    "[default: the project's, else bundled sample].",
)
@click.option("--year", default=None, type=int, help="Calendar year [default: 2026].")
@click.option(
    "--pto",
    default=None,
    type=float,
    help="PTO/sick days subtracted from the ceiling [default: 0].",
)
def hours(alloc_csv, year, pto):
    """Show each person's allocated / spent / remaining hours from their FTE."""
    from budgie.core.allocation import load_allocations
    from budgie.core.calendar import productive_hours
    from budgie.singletons import logger
    from budgie.utils.utils import display_startup_message

    display_startup_message()
    alloc_csv = _input("allocations", alloc_csv, "allocations.csv")
    year = _setting("year", year, 2026)
    pto = _setting("pto", pto, 0.0)

    ph = productive_hours(year, pto_days=pto)
    allocs = load_allocations(alloc_csv, available_hours=ph)
    logger.info(f"Available hours {year}: {ph.available_hours:,.0f} (1.0 FTE)")
    _print_hours_table(allocs)


@click.command()
@click.option(
    "--allocations",
    "alloc_csv",
    default=str(THIS_DIR / "tests" / "allocations.csv"),
    show_default=True,
    help="CSV of allocations (name, fte, hours_spent, and optional email).",
)
@click.option(
    "--year", default=2026, show_default=True, help="Calendar year for available hours."
)
@click.option(
    "--pto",
    default=0.0,
    show_default=True,
    help="PTO/sick days subtracted from the ceiling.",
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
    default=False,
    help="Write Outlook-ready .eml drafts with an embedded burn-down chart "
    "(default: plain .txt).",
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
def emails(
    alloc_csv, year, pto, out_dir, preview, as_html, as_of, actuals_csv, weekly_csv
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
    year = _setting("year", year, 2026)
    pto = _setting("pto", pto, 0.0)
    # Actuals are optional, so only reach for the project's copy when the user
    # didn't name one -- and only if it's actually there.
    actuals_csv = actuals_csv or _workspace_input("actuals")
    weekly_csv = weekly_csv or _workspace_input("weekly")

    ph = productive_hours(year, pto_days=pto)
    allocs = load_allocations(alloc_csv, available_hours=ph)

    if as_html:
        paths = _write_html_emails(
            allocs, year, out_dir, as_of, actuals_csv, weekly_csv
        )
    else:
        paths = write_drafts(allocs, year, out_dir)

    console.print(
        f"[bold]Wrote {len(paths)} draft(s)[/bold] to {out_dir}/ (review before sending)"
    )
    for path in paths:
        console.print(f"  • {path}")

    if preview and allocs and not as_html:
        console.rule("Preview")
        console.print(render_email(allocs[0], year).as_text())


def _write_html_emails(allocs, year, out_dir, as_of, actuals_csv=None, weekly_csv=None):
    """Render a burn-down chart per person and write Outlook-ready .eml drafts."""
    from budgie.core.actuals import load_weekly_actuals, monthly_to_observations
    from budgie.core.burndown import burndown
    from budgie.core.monthly import load_monthly_actuals
    from budgie.emails import slug, write_eml_drafts
    from budgie.plots import burndown_chart

    out = Path(out_dir)
    charts_dir = out / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    # Real spend readings turn the interpolated burn-down into a true curve.
    # Weekly cumulative readings and monthly per-period hours both reduce to
    # the same (date, cumulative-hours) observations.
    if weekly_csv:
        observations = load_weekly_actuals(weekly_csv, year)
    elif actuals_csv:
        observations = {
            name: monthly_to_observations(year, months)
            for name, months in load_monthly_actuals(actuals_csv).items()
        }
    else:
        observations = {}

    as_of_date = as_of.date() if as_of else None
    statuses, charts = [], {}
    for alloc in allocs:
        obs = observations.get(alloc.name)
        # Never chart a reading dated after the as-of date.
        if obs and as_of_date:
            obs = [o for o in obs if o[0] <= as_of_date]
        status = burndown(alloc, year, as_of=as_of_date, observations=obs)
        chart_path = burndown_chart(status, charts_dir / f"{slug(alloc.name)}.png")
        statuses.append(status)
        charts[alloc.name] = chart_path.read_bytes()

    return write_eml_drafts(statuses, year, out, charts=charts)


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
@click.option("--year", default=None, type=int, help="Calendar year [default: 2026].")
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
def monthly(
    people_csv, year, pto, iterations, seed, budget_arg, costs_csv, plots, out_dir
):
    """Break the year into months: cost per month and a cumulative fan chart."""
    from budgie.core.calendar import productive_hours
    from budgie.core.costs import load_costs
    from budgie.core.loader import load_people
    from budgie.core.monthly import monthly_forecast, monthly_simulation
    from budgie.singletons import console, logger
    from budgie.utils.utils import display_startup_message

    display_startup_message()
    people_csv = _input("people", people_csv, "team.csv")
    year = _setting("year", year, 2026)
    pto = _setting("pto", pto, 0.0)
    iterations = _setting("iterations", iterations, 10_000)
    seed = _setting("seed", seed, None)
    budget_arg = _budget_arg(budget_arg)

    ph = productive_hours(year, pto_days=pto)
    people = load_people(people_csv, productive_hours=ph)
    costs = load_costs(costs_csv) if costs_csv else []
    budget = _budget_from(budget_arg) if budget_arg else None

    mf = monthly_forecast(people, year, pto_days=pto, costs=costs)
    sim = monthly_simulation(
        people, year, pto_days=pto, iterations=iterations, seed=seed, costs=costs
    )
    logger.info(f"{len(people)} people, {year} split into months by working-day share")
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

    from budgie.core.monthly import MONTH_NAMES
    from budgie.singletons import console

    p10, p50, p90 = sim.band(10), sim.band(50), sim.band(90)
    table = Table(
        show_header=True,
        header_style="bold magenta",
        title=f"Monthly breakdown {mf.year}",
    )
    table.add_column("Month")
    table.add_column("Hours", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("Cumulative", justify="right")
    table.add_column("P10", justify="right")
    table.add_column("P90", justify="right")
    cum = mf.cumulative_costs
    for i, name in enumerate(MONTH_NAMES):
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


@click.command()
@click.argument("directory", default=".", type=click.Path(file_okay=False))
@click.option("--year", default=2026, show_default=True, help="Year to scaffold for.")
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite files that already exist (off by default -- init never "
    "silently replaces your numbers).",
)
def init(directory, year, force):
    """Create a Budgie project here: a budgie.yaml and starter input files.

    Every command afterwards finds this project by walking up from wherever you
    run it, so you can edit the CSVs in place and just re-run `budgie forecast`.
    """
    from budgie.core.scaffold import init_workspace
    from budgie.core.workspace import CONFIG_NAME, forget_workspaces
    from budgie.singletons import console
    from budgie.utils.utils import display_startup_message

    display_startup_message()
    written, skipped = init_workspace(directory, year=year, overwrite=force)
    forget_workspaces()

    root = Path(directory).resolve()
    console.print(f"[bold]Project at[/bold] {root}")
    for path in written:
        console.print(f"  [green]+[/green] {path.name}")
    for path in skipped:
        console.print(f"  [dim]· {path.name} (already there, left alone)[/dim]")
    if skipped and not force:
        console.print("[dim]Pass --force to overwrite the existing files.[/dim]")

    console.print(
        f"\nEdit the CSVs, then run [bold]budgie status[/bold] to check them.\n"
        f"Settings like year, PTO and budget live in [bold]{CONFIG_NAME}[/bold]."
    )


@click.command()
def status():
    """Show the current project: which inputs exist, and what feeds what."""
    from budgie.core.workspace import find_workspace
    from budgie.singletons import console
    from budgie.utils.utils import display_startup_message

    display_startup_message()
    workspace = find_workspace()
    if workspace is None:
        console.print(
            "[yellow]No budgie.yaml found[/yellow] above "
            f"{Path.cwd()}.\n"
            "Commands are running against the bundled sample data in "
            f"{THIS_DIR / 'tests'}.\n\n"
            "Run [bold]budgie init[/bold] to start a project with your own numbers."
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
@click.option("--year", default=None, type=int, help="Calendar year [default: 2026].")
@click.option(
    "--pto",
    default=None,
    type=float,
    help="PTO/sick days, to show its effect on the ceiling [default: 0].",
)
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
    from budgie.core.monthly import month_weights
    from budgie.utils.utils import display_startup_message

    display_startup_message()
    year = _setting("year", year, 2026)
    pto = _setting("pto", pto, 0.0)

    ph = productive_hours(year, pto_days=pto)
    weights = month_weights(year)

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
            f"{federal_holiday_workdays(year)} US federal holidays fall Mon-Fri"
            f" in {year} (-{ph.holiday_hours:,.0f} h)",
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
            f"{workdays_in_year(year)} in {year}; day-level math spreads"
            " available hours across exactly these",
            "core/calendar.py",
        ),
        _row(
            "Month weights",
            "by working-day share, not 1/12"
            f" (Jan {weights[0]:.1%} ... Feb {weights[1]:.1%})",
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
            "Burn-down pace",
            "expectation is a straight line from 0 on Jan 1"
            " to the full allocation on Dec 31",
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
    _print_assumptions_table(year, rows)


def _row(name: str, value: str, source: str) -> tuple[str, str, str]:
    """One row of the assumptions table."""
    return (name, value, source)


def _print_assumptions_table(year, rows):
    from rich.table import Table

    from budgie.singletons import console

    table = Table(
        show_header=True,
        header_style="bold magenta",
        title=f"Assumptions in force for {year}",
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
@click.option("--year", default=None, type=int, help="Calendar year [default: 2026].")
@click.option(
    "--pto", default=None, type=float, help="PTO/sick days per person [default: 0]."
)
def plan(plan_csv, year, pto):
    """Show allocated hours from a date-resolution allocation plan.

    Each row applies from its effective date until the next row for that person,
    so joining mid-year, leaving, and re-planning are all just appended rows.
    """
    from budgie.core.plan import load_plan
    from budgie.utils.utils import display_startup_message

    display_startup_message()
    plan_csv = _input("plan", plan_csv, "plan.csv")
    year = _setting("year", year, 2026)
    pto = _setting("pto", pto, 0.0)

    allocation_plan = load_plan(plan_csv)
    _print_plan_table(allocation_plan, year, pto)


def _print_plan_table(allocation_plan, year, pto):
    from rich.table import Table

    from budgie.singletons import console

    table = Table(
        show_header=True, header_style="bold magenta", title=f"Allocation plan {year}"
    )
    table.add_column("Name")
    table.add_column("Changes")
    table.add_column("Hours", justify="right")
    total = 0.0
    for name in allocation_plan.names:
        hours = allocation_plan.allocated_hours(name, year, pto_days=pto)
        total += hours
        changes = ", ".join(
            f"{e.effective_date:%b %-d}→{e.fte:g}" for e in allocation_plan._for(name)
        )
        table.add_row(name, changes, f"{hours:,.0f}")
    table.add_section()
    table.add_row("[bold]Total[/bold]", "", f"[bold]{total:,.0f}[/bold]")
    console.print(table)


cli.add_command(init)
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
