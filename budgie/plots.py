"""
Matplotlib figure generation for forecasts.

Kept separate from the CLI so the same figures can be reused by a future TUI/GUI.
Uses the non-interactive Agg backend and writes image files -- nothing here opens
a window.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # file output only; no display required
import matplotlib.pyplot as plt

from budgie.core.burndown import BurndownStatus
from budgie.core.forecast import Forecast
from budgie.core.montecarlo import SimulationResult
from budgie.core.monthly import MONTH_NAMES, MonthlyForecast, MonthlySimulation

# Budgie house palette (matches the demo/report styling).
GREEN = "#4c9f70"
INK = "#3d405b"
AMBER = "#d08700"
RED = "#c0362c"
MUTED = "#8a978f"


def montecarlo_histogram(
    result: SimulationResult,
    out_path: str | Path,
    percentiles=(10, 50, 90),
) -> Path:
    """Histogram of simulated total costs with percentile marker lines."""
    out_path = Path(out_path)
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.hist(result.total_costs, bins=60, color="#4c9f70", alpha=0.85, edgecolor="white")

    pct = result.percentiles(percentiles)
    colors = {10: "#e07a5f", 50: "#3d405b", 90: "#e07a5f"}
    for p, value in pct.items():
        ax.axvline(value, color=colors.get(p, "#3d405b"), linestyle="--", linewidth=1.5)
        ax.text(
            value,
            ax.get_ylim()[1] * 0.95,
            f"P{p}\n${value:,.0f}",
            ha="center",
            va="top",
            fontsize=9,
            color=colors.get(p, "#3d405b"),
        )

    ax.set_title(f"Monte Carlo total cost ({result.iterations:,} simulations)")
    ax.set_xlabel("Total cost ($)")
    ax.set_ylabel("Frequency")
    ax.xaxis.set_major_formatter(lambda x, _: f"${x:,.0f}")
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def forecast_bars(forecast: Forecast, out_path: str | Path) -> Path:
    """Per-person cost contribution as a horizontal bar chart."""
    out_path = Path(out_path)
    items = sorted(forecast.line_items, key=lambda i: i.cost)
    names = [i.name for i in items]
    costs = [i.cost for i in items]

    fig, ax = plt.subplots(figsize=(9, max(3, 0.6 * len(items) + 1)))
    ax.barh(names, costs, color="#4c9f70")
    ax.set_title("Expected cost per person (most-likely hours)")
    ax.set_xlabel("Cost ($)")
    ax.xaxis.set_major_formatter(lambda x, _: f"${x:,.0f}")
    for y, cost in enumerate(costs):
        ax.text(cost, y, f" ${cost:,.0f}", va="center", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def burndown_chart(status: BurndownStatus, out_path: str | Path) -> Path:
    """Per-person hours burn-down: even pace vs actual spend, with a projection.

    Sized and styled for embedding in an email (compact, high contrast).
    """
    import matplotlib.dates as mdates

    out_path = Path(out_path)
    alloc = status.allocation
    start = date(status.year, 1, 1)
    end = date(status.year, 12, 31)
    allocated = alloc.allocated_hours

    fig, ax = plt.subplots(figsize=(7.2, 3.4))

    # Even-pace reference line: 0 on Jan 1 -> full allocation on Dec 31.
    ax.plot(
        [start, end],
        [0, allocated],
        color=MUTED,
        linestyle="--",
        linewidth=1.4,
        label="Even pace",
        zorder=2,
    )

    # Actual spend to date. Use real monthly data when supplied, else interpolate
    # from the origin to the one point we actually know (spent-to-date).
    if status.monthly_spent:
        xs = [start] + [
            min(date(status.year, m + 1, 1) - timedelta(days=1), end)
            for m in range(len(status.monthly_spent))
        ]
        ys = [0.0, *status.monthly_spent]
    else:
        xs = [start, status.as_of]
        ys = [0.0, alloc.hours_spent]
    actual_color = RED if status.projected_over else GREEN
    ax.plot(xs, ys, color=actual_color, linewidth=2.4, label="Actual", zorder=4)

    # Anchor the marker and the projection to wherever the actual series really
    # ends (month end with actuals, as-of date without) so there's no gap.
    last_x, last_y = xs[-1], ys[-1]
    ax.scatter([last_x], [last_y], color=actual_color, s=42, zorder=5)

    # Projection from there to year end at the observed burn rate.
    projected_end = status.projected_total
    ax.plot(
        [last_x, end],
        [last_y, projected_end],
        color=actual_color,
        linestyle=":",
        linewidth=1.8,
        label="Projected",
        zorder=3,
    )

    # Allocation ceiling.
    ax.axhline(allocated, color=INK, linewidth=1.2, alpha=0.8)
    ax.text(
        start,
        allocated,
        f" allocation {allocated:,.0f} h",
        va="bottom",
        ha="left",
        fontsize=8,
        color=INK,
    )

    # Mark the date the allocation runs dry, if it does so this year.
    exhausted = status.exhaustion_date
    if exhausted is not None:
        ax.axvline(exhausted, color=RED, linestyle="-.", linewidth=1.2, alpha=0.9)
        ax.text(
            exhausted,
            allocated * 0.06,
            f" runs out {exhausted:%b %d} ",
            rotation=90,
            fontsize=8,
            color=RED,
            va="bottom",
            ha="right",
        )

    ax.set_xlim(start, end)
    ax.set_ylim(0, max(allocated, projected_end, alloc.hours_spent) * 1.18)
    ax.set_ylabel("Cumulative hours", fontsize=9)
    ax.set_title(f"{alloc.name} — {status.year} hours burn-down", fontsize=11)
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax.tick_params(labelsize=8)
    ax.grid(axis="y", alpha=0.18)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(fontsize=8, frameon=False, loc="upper left")

    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return out_path


def fan_chart(
    sim: MonthlySimulation,
    out_path: str | Path,
    budget: float | None = None,
) -> Path:
    """Cumulative cost through the year with a widening P10-P90 uncertainty band."""
    out_path = Path(out_path)
    months = range(12)
    p10, p50, p90 = sim.band(10), sim.band(50), sim.band(90)

    fig, ax = plt.subplots(figsize=(9, 4.6))
    ax.fill_between(months, p10, p90, color=GREEN, alpha=0.22, label="P10-P90")
    ax.plot(months, p50, color=GREEN, linewidth=2.4, label="P50 (expected)")

    if budget is not None:
        ax.axhline(budget, color=RED, linestyle="--", linewidth=1.4)
        # Right-aligned so it never collides with the upper-left legend.
        ax.text(
            11,
            budget,
            f"budget ${budget:,.0f} ",
            va="bottom",
            ha="right",
            fontsize=9,
            color=RED,
        )

    ax.set_xticks(list(months))
    ax.set_xticklabels(MONTH_NAMES, fontsize=9)
    ax.set_ylabel("Cumulative cost ($)", fontsize=10)
    ax.set_title(f"Cumulative cost through {sim.year} ({sim.iterations:,} simulations)")
    ax.yaxis.set_major_formatter(lambda x, _: f"${x:,.0f}")
    ax.set_xlim(0, 11)
    ax.set_ylim(0, None)
    ax.grid(axis="y", alpha=0.2)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(fontsize=9, frameon=False, loc="upper left")

    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def monthly_cost_bars(forecast: MonthlyForecast, out_path: str | Path) -> Path:
    """Per-month cost, showing how working-day count shapes the year."""
    out_path = Path(out_path)
    fig, ax = plt.subplots(figsize=(9, 3.8))
    ax.bar(MONTH_NAMES, forecast.costs, color=GREEN)
    ax.set_ylabel("Cost ($)", fontsize=10)
    ax.set_title(f"Cost per month, {forecast.year} (weighted by working days)")
    ax.yaxis.set_major_formatter(lambda x, _: f"${x:,.0f}")
    ax.tick_params(labelsize=9)
    ax.grid(axis="y", alpha=0.2)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path
