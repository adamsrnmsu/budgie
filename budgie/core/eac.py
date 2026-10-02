"""
Estimate at completion: what's been spent, plus a forecast of what's left.

A full-year forecast made in September still simulates January. Once there are
readings of real spend, the past is known and only the remainder is uncertain.

The whole feature rests on one fact: a triangular estimate that is scaled and
shifted is still triangular. So there is no second simulator here -- just
adjusted :class:`Person` objects that the ordinary ``forecast()``,
``simulate()`` and ``signals.evaluate()`` consume unchanged::

    hours at completion = spent + planned hours x share of the plan left

The share left is the person's own plan.csv shape when there is one (someone
who joins in July has all of it left on Jun 30), else working days.

Stated assumptions: spent hours are costed at the person's *current* rate (no
rate history exists), and non-labor costs are not adjusted (no actuals exist
for them).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import TYPE_CHECKING

from budgie.core.actuals import Observation
from budgie.core.calendar import workdays_between, workdays_in_year, year_span
from budgie.core.person import HoursEstimate, Person

if TYPE_CHECKING:
    from budgie.core.plan import AllocationPlan

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Completion:
    """The adjusted team, and the reading each adjustment was made from."""

    people: list[Person]
    # name -> the (date, cumulative hours) reading used. People with no usable
    # reading are absent, and their Person is the full-year plan, untouched.
    readings: dict[str, Observation]


def elapsed_fraction(year: int, as_of: date) -> float:
    """Share of ``year``'s working days gone by the end of ``as_of``, in [0, 1].

    Working days are Mon-Fri minus federal holidays, and ``as_of`` itself counts
    as elapsed -- a reading dated the 30th includes the 30th's hours. Dates
    outside the year clamp to its ends.
    """
    start, end = date(year, 1, 1), date(year, 12, 31)
    if as_of < start:
        return 0.0
    return workdays_between(start, min(as_of, end)) / workdays_in_year(
        year_span(year)
    )  # bridge: budgie-bvd


def at_completion(
    people: Sequence[Person],
    observations: Mapping[str, Sequence[Observation]],
    year: int,
    as_of: date | None = None,
    plan: AllocationPlan | None = None,
) -> Completion:
    """Replace each person's elapsed plan with their latest reading of real spend.

    ``as_of`` only filters which readings count. The elapsed share is always
    measured at the *reading's own date*: hours booked after it are unknown, so
    that stretch has to stay forecast rather than be silently treated as zero.
    ``plan`` makes that share the plan's hours accrued by then, for everyone it
    has hours for; anyone else keeps the working-day share.
    """
    unknown = sorted(set(observations) - {p.name for p in people})
    if unknown:
        logger.warning(
            "Actuals for %s match nobody in the team; ignored", ", ".join(unknown)
        )

    adjusted: list[Person] = []
    readings: dict[str, Observation] = {}
    for person in people:
        usable = [
            o
            for o in observations.get(person.name, ())
            if as_of is None or o[0] <= as_of
        ]
        if not usable:
            adjusted.append(person)
            continue
        when, spent = max(usable, key=lambda o: o[0])
        done = plan.fraction_through(person.name, year, when) if plan else None
        left = 1.0 - (elapsed_fraction(year, when) if done is None else done)
        est = person.hours
        readings[person.name] = (when, spent)
        adjusted.append(
            replace(
                person,
                hours=HoursEstimate(
                    spent + est.low * left,
                    spent + est.mode * left,
                    spent + est.high * left,
                ),
            )
        )
    return Completion(people=adjusted, readings=readings)
