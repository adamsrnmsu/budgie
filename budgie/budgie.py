"""
Budgie CLI.

Thin front-end over the presentation-independent engine in ``budgie.core``. Each
command loads inputs, calls the engine, and renders results with rich (and
optionally matplotlib figures). No budgeting math lives here.
"""

from pathlib import Path

import click

from budgie.core.allocation import load_allocations
from budgie.core.calendar import productive_hours
from budgie.core.costs import load_costs
from budgie.core.forecast import forecast as run_forecast
from budgie.core.loader import load_people
from budgie.core.montecarlo import simulate
from budgie.core.scenario import run_scenarios
from budgie.core.signals import Signal
from budgie.singletons import console, logger, set_verbose
from budgie.utils.utils import display_startup_message

# Stoplight glyph + rich color per signal.
_SIGNAL_STYLE = {
    Signal.GREEN: ("●", "green", "GOOD"),
    Signal.YELLOW: ("●", "yellow", "CAUTION"),
    Signal.RED: ("●", "red", "BAD"),
    Signal.BLUE: ("●", "blue", "NO CHANGE"),
}

THIS_FILE = Path(__file__).resolve()
THIS_DIR = THIS_FILE.parent


@click.group()
@click.option(
    "-v", "--verbose", is_flag=True, help="Show DEBUG logging from budgie's internals."
)
def cli(verbose):
    """Budgie -- the ultimate budget companion."""
    set_verbose(verbose)


@click.command()
@click.option(
    "--people",
    "people_csv",
    default=str(THIS_DIR / "tests" / "team.csv"),
    show_default=True,
    help="CSV of team members (name, hourly_cost, and util_*/hours_* columns).",
)
@click.option(
    "--year",
    default=2026,
    show_default=True,
    help="Calendar year for productive hours.",
)
@click.option(
    "--pto",
    default=0.0,
    show_default=True,
    help="PTO/sick days to subtract per person.",
)
@click.option(
    "--iterations", default=10_000, show_default=True, help="Monte Carlo iterations."
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
    display_startup_message()

    ph = productive_hours(year, pto_days=pto)
    logger.info(
        f"Productive hours {year}: {ph.productive_hours:.0f}"
        + (
            f" (available after {pto:g} PTO days: {ph.available_hours:.0f})"
            if pto
            else ""
        )
    )

    people = load_people(people_csv, productive_hours=ph.available_hours)
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

    # Signal against the budget as it stands now, not the original baseline.
    result = evaluate(sim, budget.latest)
    _, color, word = _SIGNAL_STYLE[result.signal]
    if budget.has_revisions:
        console.print(
            f"[dim]Budget: original ${budget.original:,.0f} → current "
            f"${budget.latest:,.0f} ({budget.net_change:+,.0f} over "
            f"{len(budget.revisions)} revisions)[/dim]"
        )
    console.print(f"[{color}]●[/{color}] [bold]{word}[/bold] — {result.rationale}")


def _print_montecarlo_summary(sim, pct):
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
def hours(alloc_csv, year, pto):
    """Show each person's allocated / spent / remaining hours from their FTE."""
    display_startup_message()
    ph = productive_hours(year, pto_days=pto)
    allocs = load_allocations(alloc_csv, available_hours=ph.available_hours)
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
    from budgie.emails import render_email, write_drafts

    display_startup_message()
    ph = productive_hours(year, pto_days=pto)
    allocs = load_allocations(alloc_csv, available_hours=ph.available_hours)

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
    default=str(THIS_DIR / "tests" / "scenarios.yaml"),
    show_default=True,
    help="YAML config describing a budget and named scenarios to compare.",
)
def scenario(config_path):
    """Compare what-if scenarios side by side, with a stoplight vs the budget."""
    display_startup_message()
    results, budget = run_scenarios(config_path)
    logger.info(f"Budget target: ${budget:,.0f}   (baseline: {results[0].name})")
    _print_scenario_table(results, budget)
    console.print("\n[bold]Signals[/bold]")
    for r in results:
        _, color, word = _SIGNAL_STYLE[r.signal.signal]
        console.print(
            f"  [{color}]●[/{color}] [bold]{r.name}[/bold] — {word}: {r.signal.rationale}"
        )


def _print_scenario_table(results, budget):
    from rich.table import Table

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
        _, color, _word = _SIGNAL_STYLE[r.signal.signal]
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
    default=str(THIS_DIR / "tests" / "team.csv"),
    show_default=True,
    help="CSV of team members.",
)
@click.option("--year", default=2026, show_default=True, help="Calendar year.")
@click.option("--pto", default=0.0, show_default=True, help="PTO/sick days per person.")
@click.option(
    "--iterations", default=10_000, show_default=True, help="Monte Carlo iterations."
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
    from budgie.core.monthly import monthly_forecast, monthly_simulation

    display_startup_message()
    people = load_people(
        people_csv,
        productive_hours=productive_hours(year, pto_days=pto).available_hours,
    )
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
@click.option(
    "--plan",
    "plan_csv",
    default=str(THIS_DIR / "tests" / "plan.csv"),
    show_default=True,
    help="CSV of allocation changes (name, effective_date, fte).",
)
@click.option("--year", default=2026, show_default=True, help="Calendar year.")
@click.option("--pto", default=0.0, show_default=True, help="PTO/sick days per person.")
def plan(plan_csv, year, pto):
    """Show allocated hours from a date-resolution allocation plan.

    Each row applies from its effective date until the next row for that person,
    so joining mid-year, leaving, and re-planning are all just appended rows.
    """
    from budgie.core.plan import load_plan

    display_startup_message()
    allocation_plan = load_plan(plan_csv)
    _print_plan_table(allocation_plan, year, pto)


def _print_plan_table(allocation_plan, year, pto):
    from rich.table import Table

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


cli.add_command(forecast)
cli.add_command(plan)
cli.add_command(tui)
cli.add_command(hours)
cli.add_command(emails)
cli.add_command(scenario)
cli.add_command(monthly)

if __name__ == "__main__":
    cli()
