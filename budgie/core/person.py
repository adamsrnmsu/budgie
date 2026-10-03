"""
People and their (uncertain) expected hours.

A person costs ``hourly_cost`` per hour and is expected to work some number of
hours in the forecast period. That number is rarely known exactly, so it's
modelled as a three-point estimate (min / most-likely / max) -- the deterministic
forecast uses the most-likely value, while Monte Carlo samples the full range.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HoursEstimate:
    """A three-point (triangular) estimate of expected hours.

    ``low <= mode <= high`` is required. Use :meth:`constant` when hours are
    known exactly.
    """

    low: float
    mode: float
    high: float

    def __post_init__(self) -> None:
        if not (self.low <= self.mode <= self.high):
            raise ValueError(
                f"HoursEstimate requires low <= mode <= high, got "
                f"({self.low}, {self.mode}, {self.high})"
            )
        if self.low < 0:
            raise ValueError(f"hours cannot be negative, got low={self.low}")

    @classmethod
    def constant(cls, hours: float) -> HoursEstimate:
        """A degenerate estimate with no uncertainty."""
        return cls(hours, hours, hours)

    @classmethod
    def from_utilization(
        cls,
        productive_hours: float,
        util_low: float,
        util_mode: float,
        util_high: float,
    ) -> HoursEstimate:
        """Build an hours estimate from utilization fractions of a ceiling.

        ``productive_hours`` is the realistic maximum (see
        :func:`budgie.core.calendar.productive_hours`); each ``util_*`` is a
        fraction in [0, 1] of that ceiling.
        """
        return cls(
            productive_hours * util_low,
            productive_hours * util_mode,
            productive_hours * util_high,
        )

    @property
    def point(self) -> float:
        """The single most-likely value, used by the deterministic forecast."""
        return self.mode

    def sample(self, rng: np.random.Generator, size: int) -> np.ndarray:
        """Draw ``size`` triangular samples of expected hours."""
        # np.random.Generator.triangular requires left < right; a degenerate
        # (constant) estimate is returned directly.
        if self.low == self.high:
            return np.full(size, self.mode, dtype=float)
        return rng.triangular(self.low, self.mode, self.high, size=size)


@dataclass(frozen=True)
class Person:
    """Someone with an hourly cost and an uncertain number of expected hours."""

    name: str
    hourly_cost: float
    hours: HoursEstimate
    #: ``(low / likely, high / likely)``: how far real hours may stray from a
    #: plan. None when likely was 0, so no ratio exists.
    spread: tuple[float, float] | None = (1.0, 1.0)
    #: This person's own PTO days from people.csv, if it gave one.
    pto_days: float | None = None

    def expected_cost(self) -> float:
        """Deterministic cost using the most-likely hours."""
        return self.hourly_cost * self.hours.point

    def sample_cost(self, rng: np.random.Generator, size: int) -> np.ndarray:
        """Draw ``size`` cost samples from the person's hours uncertainty."""
        return self.hourly_cost * self.hours.sample(rng, size)
