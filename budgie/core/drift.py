"""What moved since the previous recorded reading, at team level."""

from __future__ import annotations

from dataclasses import dataclass

from budgie.core.eac import at_completion
from budgie.core.montecarlo import simulate
from budgie.core.signals import probability_over


@dataclass(frozen=True)
class Drift:
    p50_delta: float
    hours_booked: float
    over_before: float | None = None  # P(over budget); None without a budget
    over_after: float | None = None


def _k(x: float) -> str:
    sign = "+" if x >= 0 else "-"
    x = abs(x)
    return f"{sign}${x / 1000:,.1f}k" if x >= 1000 else f"{sign}${x:,.0f}"


def since_last_reading(snap, iterations: int, seed: int | None) -> Drift | None:
    """Forecast now vs as of the reading before the latest, same seed and runs.

    The previous reading is the second-latest distinct reading date in
    weekly/actuals (never "now minus 7 days"). None under two such dates.
    """
    dates = sorted({d for obs in snap.readings.values() for d, _ in obs})
    if len(dates) < 2:
        return None
    prev = dates[-2]

    def run(as_of):
        comp = at_completion(
            snap.people, snap.readings, snap.span, as_of=as_of, plan=snap.plan
        )
        sim = simulate(comp.people, iterations, seed, costs=snap.costs)
        return comp, sim

    (c0, s0), (c1, s1) = run(prev), run(None)
    booked = sum(
        c1.readings[n][1] - c0.readings.get(n, (None, 0.0))[1] for n in c1.readings
    )
    budget = snap.budget.latest if snap.budget else None
    return Drift(
        s1.percentile(50) - s0.percentile(50),
        booked,
        None if budget is None else probability_over(s0, budget),
        None if budget is None else probability_over(s1, budget),
    )


def drift_line(d: Drift) -> str:
    parts = [f"P50 {_k(d.p50_delta)}"]
    if d.over_before is not None:
        parts.append(f"over budget {d.over_before:.0%} → {d.over_after:.0%}")
    parts.append(f"{d.hours_booked:,.0f} h booked")
    return "since last week: " + " · ".join(parts)
