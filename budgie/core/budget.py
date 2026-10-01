"""
Budget revisions over time.

A budget is rarely one number for the year -- it gets increased, cut, or
re-baselined, and you need to know both what it is *now* and what it started
as. A budget is therefore a list of dated revisions:

    effective_date,amount,note
    2026-01-01,425000,Original
    2026-05-01,450000,Q2 increase
    2026-10-01,440000,Q4 trim

Each revision holds until the next one, exactly like an allocation plan. History
is appended, never edited, so the trail of what changed and when is preserved
and the original baseline stays recoverable.

A plain number still works everywhere a budget is accepted -- ``Budget.flat()``
wraps it as a single revision -- so existing single-figure configs keep working.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from budgie.core.csvio import (
    as_required_float,
    as_str,
    last_day_of_month,
    parse_date,
    read_rows,
)

logger = logging.getLogger(__name__)

_REQUIRED_COLS = {"effective_date", "amount"}


@dataclass(frozen=True)
class BudgetRevision:
    effective_date: date
    amount: float
    note: str = ""


@dataclass(frozen=True)
class Budget:
    """A budget as a series of dated revisions (earliest first)."""

    revisions: tuple[BudgetRevision, ...]

    def __post_init__(self) -> None:
        if not self.revisions:
            raise ValueError("a budget needs at least one revision")

    @classmethod
    def flat(cls, amount: float, year: int = 1900) -> Budget:
        """A budget that never changes -- the single-number case."""
        return cls((BudgetRevision(date(year, 1, 1), float(amount), "flat"),))

    @property
    def original(self) -> float:
        """The first amount ever set -- the baseline to measure drift against."""
        return self.revisions[0].amount

    @property
    def latest(self) -> float:
        """The most recent amount, regardless of date."""
        return self.revisions[-1].amount

    @property
    def has_revisions(self) -> bool:
        return len(self.revisions) > 1

    @property
    def net_change(self) -> float:
        """Latest minus original (negative for a net cut)."""
        return self.latest - self.original

    def amount_on(self, day: date) -> float:
        """The budget in force on ``day``.

        Before the first revision the original amount applies -- a budget set in
        May was still the governing number for that year's January.
        """
        current = self.revisions[0].amount
        for revision in self.revisions:
            if revision.effective_date <= day:
                current = revision.amount
            else:
                break
        return current

    def monthly_amounts(self, year: int) -> list[float]:
        """The budget in force at each month end, for a stepped budget line."""
        return [self.amount_on(last_day_of_month(year, m)) for m in range(1, 13)]


def load_budget(csv_path: str | Path) -> Budget:
    """Load budget revisions from an ``effective_date,amount[,note]`` CSV."""
    revisions = [
        BudgetRevision(
            effective_date=parse_date(row["effective_date"]),
            amount=as_required_float(row, "amount"),
            note=as_str(row, "note"),
        )
        for row in read_rows(csv_path, required=_REQUIRED_COLS)
    ]
    revisions.sort(key=lambda r: r.effective_date)
    budget = Budget(tuple(revisions))
    logger.info(
        "Loaded budget: %d revision(s), original %s, current %s",
        len(revisions),
        f"${budget.original:,.0f}",
        f"${budget.latest:,.0f}",
    )
    return budget


def coerce_budget(value: float | dict | list | str | Path) -> Budget:
    """Accept any of the shapes a config might carry and return a Budget.

    Supports a bare number, a list of ``{date, amount, note}`` mappings, or a
    path to a revisions CSV -- so ``budget: 425000`` in an existing scenario
    config keeps working unchanged.
    """
    if isinstance(value, Budget):
        return value
    if isinstance(value, (int, float)):
        return Budget.flat(float(value))
    if isinstance(value, (str, Path)):
        return load_budget(value)
    if isinstance(value, list):
        revisions = [
            BudgetRevision(
                effective_date=parse_date(entry["date"]),
                amount=float(entry["amount"]),
                note=str(entry.get("note", "")),
            )
            for entry in value
        ]
        revisions.sort(key=lambda r: r.effective_date)
        return Budget(tuple(revisions))
    raise TypeError(f"cannot interpret {value!r} as a budget")
