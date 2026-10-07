"""A forecast backtest: how often did the P10-P90 band hold?

For each past reading date d the forecast is rebuilt as it stood on d (the plan
rows effective by d, the readings up to d, the same estimate at completion and
triangular draws as `monthly`) and scored against the cumulative labor spend
actually read on each later reading date t. See
docs/superpowers/specs/2026-10-06-calibrate-design.md.

Team level, labor dollars. Nothing is tuned and nothing is written.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import median
from typing import TYPE_CHECKING

import numpy as np

from budgie.core.eac import at_completion, elapsed_fraction
from budgie.core.monthly import spent_at
from budgie.core.plan import AllocationPlan

if TYPE_CHECKING:
    from budgie.core.project import Snapshot

DEFAULT_ITERATIONS = 2000  # forecast's is 10,000; the band only needs 2 percentiles
DEFAULT_SEED = 1
MIN_PAIRS = 8
#: (label, lowest weeks ahead): a pair belongs to the last row it reaches.
HORIZONS = (("1-3 weeks", 1), ("4-7 weeks", 4), ("8+ weeks", 8))


@dataclass(frozen=True)
class Pair:
    forecast_date: date
    target_date: date
    weeks: int
    p10: float
    p50: float
    p90: float
    actual: float

    @property
    def error(self) -> float:
        """Actual minus P50: positive means spend ran hotter than the median."""
        return self.actual - self.p50


@dataclass(frozen=True)
class Score:
    """One row of results; ``enough`` is False below the minimum pair count."""

    label: str
    pairs: int
    enough: bool
    inside: float | None = None  # shares, 0..1
    below: float | None = None
    above: float | None = None
    median_error: float | None = None  # dollars
    median_error_pct: float | None = None  # of P50, None when no P50 is positive


@dataclass(frozen=True)
class Calibration:
    total: Score
    horizons: tuple[Score, ...]
    pairs: tuple[Pair, ...]
    iterations: int
    seed: int


def score(label: str, pairs: list[Pair], min_pairs: int = MIN_PAIRS) -> Score:
    n = len(pairs)
    if n < min_pairs:
        return Score(label, n, False)
    pcts = [p.error / p.p50 for p in pairs if p.p50 > 0]
    return Score(
        label,
        n,
        True,
        inside=sum(p.p10 <= p.actual <= p.p90 for p in pairs) / n,
        below=sum(p.actual < p.p10 for p in pairs) / n,
        above=sum(p.actual > p.p90 for p in pairs) / n,
        median_error=median(p.error for p in pairs),
        median_error_pct=median(pcts) if pcts else None,
    )


def _plan_by(plan: AllocationPlan | None, day: date) -> AllocationPlan | None:
    """The plan in force on ``day``: rows effective on or before it."""
    if plan is None:
        return None
    return AllocationPlan(tuple(e for e in plan.entries if e.effective_date <= day))


def calibrate(
    snap: Snapshot,
    iterations: int = DEFAULT_ITERATIONS,
    seed: int | None = None,
    min_pairs: int = MIN_PAIRS,
) -> Calibration:
    seed = seed if seed is not None else snap.seed
    seed = DEFAULT_SEED if seed is None else seed
    span = snap.span
    readings = {n: s for n, s in snap.readings.items() if s}
    scored = [p for p in snap.people if p.name in readings]
    rate = {p.name: p.hourly_cost for p in scored}
    days = sorted({d for s in readings.values() for d, _ in s if d <= span.last})
    last = {n: max(d for d, _ in s) for n, s in readings.items() if n in rate}

    def actual(t: date) -> float:
        return sum(spent_at(readings[n], t, span) * rate[n] for n in rate)

    pairs: list[Pair] = []
    done_memo: dict = {}
    for d in days:
        # Never extrapolate: a target needs a reading at or after it from everyone.
        targets = [t for t in days if t > d and all(last[n] >= t for n in last)]
        if not targets or not scored:
            continue
        plan = _plan_by(snap.plan, d)
        past = snap.with_plan(plan) if snap.plan is not None else snap
        team = [p for p in past.people if p.name in rate]
        eac = at_completion(team, readings, span, as_of=d, plan=plan)

        def done(name: str, day: date, plan=plan) -> float:
            # Plans repeat across forecast dates once past their last row, and
            # the day-by-day walk is the slow part, so memoise across them.
            key = (plan.entries if plan else (), name, day)
            if key not in done_memo:
                frac = plan.fraction_through(name, span, day) if plan else None
                done_memo[key] = elapsed_fraction(span, day) if frac is None else frac
            return done_memo[key]

        rng = np.random.default_rng(seed)
        draws = {p.name: p.hours.sample(rng, iterations) for p in eac.people}
        cum = {t: np.zeros(iterations) for t in targets}
        for p in eac.people:
            reading = eac.readings.get(p.name)
            for t in targets:
                if reading is None:
                    hours = draws[p.name] * done(p.name, t)
                else:
                    when, spent = reading
                    left = 1.0 - done(p.name, when)
                    share = (
                        1.0
                        if left <= 1e-9
                        else (done(p.name, t) - done(p.name, when)) / left
                    )
                    hours = spent + (draws[p.name] - spent) * min(1.0, share)
                cum[t] += p.hourly_cost * hours
        for t in targets:
            p10, p50, p90 = (float(np.percentile(cum[t], q)) for q in (10, 50, 90))
            weeks = max(1, round((t - d).days / 7))
            pairs.append(Pair(d, t, weeks, p10, p50, p90, actual(t)))

    rows = tuple(
        score(
            label,
            [
                p
                for p in pairs
                if p.weeks >= lo
                and all(p.weeks < nxt for _, nxt in HORIZONS if nxt > lo)
            ],
            min_pairs,
        )
        for label, lo in HORIZONS
    )
    return Calibration(
        score("All pairs", pairs, min_pairs), rows, tuple(pairs), iterations, seed
    )
