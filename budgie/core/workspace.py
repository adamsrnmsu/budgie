"""
The Budgie project workspace.

Every command used to default to a CSV *inside the installed package*, which
answered "how do I try this?" and completely failed to answer "where do I put my
own numbers?". A workspace fixes that: a directory with a ``budgie.yaml`` and the
input files next to it.

    my-project/
      budgie.yaml        <- which files, which year, which defaults
      people.csv
      allocations.csv
      plan.csv
      costs.csv
      budget.csv
      actuals.csv

``budgie init`` writes that directory. Every command afterwards finds it by
walking up from the working directory, so you can run ``budgie forecast`` from
anywhere inside the project and get *your* numbers. Explicit ``--people`` style
options still win, and with no workspace at all the bundled samples are used --
so nothing that worked before stops working.

This module is deliberately free of click and rich: it resolves paths and
reports what exists, and the front-ends decide how to show it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_NAME = "budgie.yaml"

# Every input Budgie knows how to read: config key -> (default filename,
# what it is, which commands consume it).
INPUTS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "people": (
        "people.csv",
        "Team members: hourly cost and a low/mode/high hours or utilization estimate",
        ("forecast", "monthly", "tui", "scenario"),
    ),
    "allocations": (
        "allocations.csv",
        "FTE allocations and hours spent to date, plus each person's email",
        ("hours", "emails"),
    ),
    "plan": (
        "plan.csv",
        "Dated allocation changes -- joins, departures and re-plans, one row each",
        ("plan",),
    ),
    "costs": (
        "costs.csv",
        "Non-labor lines: materials, licences, travel",
        ("forecast", "monthly"),
    ),
    "budget": (
        "budget.csv",
        "Budget revisions over time (or a single number in budgie.yaml)",
        ("forecast", "monthly", "scenario"),
    ),
    "actuals": (
        "actuals.csv",
        "Observed spend: monthly hours per person",
        ("emails",),
    ),
    "weekly": (
        "weekly.csv",
        "Observed spend: cumulative hours through an ISO week",
        ("emails",),
    ),
    "scenarios": (
        "scenarios.yaml",
        "Named what-if scenarios to compare",
        ("scenario",),
    ),
}

# Settings a workspace can pin so you stop retyping them on every command.
SETTINGS = ("year", "pto", "iterations", "seed")


@dataclass(frozen=True)
class InputFile:
    """One expected input, and whether it's actually there."""

    key: str
    path: Path
    description: str
    used_by: tuple[str, ...]

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    @property
    def rows(self) -> int | None:
        """Data rows in the file (excluding the header), or None if absent."""
        if not self.exists or self.path.suffix != ".csv":
            return None
        with self.path.open(encoding="utf-8-sig") as handle:
            return max(sum(1 for line in handle if line.strip()) - 1, 0)


@dataclass(frozen=True)
class Workspace:
    """A project directory: where the inputs live and what the defaults are."""

    root: Path
    settings: dict = field(default_factory=dict)
    paths: dict = field(default_factory=dict)

    @property
    def config_path(self) -> Path:
        return self.root / CONFIG_NAME

    def path_for(self, key: str) -> Path:
        """Where input ``key`` lives, whether or not it exists yet."""
        configured = self.paths.get(key)
        if configured:
            # A relative path in the config is relative to the config itself,
            # so a workspace can be moved or checked out anywhere.
            return (self.root / Path(configured)).resolve()
        return self.root / INPUTS[key][0]

    def inputs(self) -> list[InputFile]:
        """Every known input, in the order they're listed in :data:`INPUTS`."""
        return [
            InputFile(
                key=key,
                path=self.path_for(key),
                description=description,
                used_by=used_by,
            )
            for key, (_default, description, used_by) in INPUTS.items()
        ]

    def resolve(self, key: str, override: str | Path | None = None) -> str | None:
        """The path a command should use for ``key``.

        An explicit command-line value always wins. Otherwise the workspace file
        is used *if it exists* -- a workspace shouldn't make ``budgie forecast``
        fail just because you haven't written a costs file yet.
        """
        if override:
            return str(override)
        path = self.path_for(key)
        return str(path) if path.is_file() else None

    def setting(self, key: str, default=None):
        """A pinned default from ``budgie.yaml`` (year, pto, iterations, seed)."""
        value = self.settings.get(key)
        return default if value is None else value


@lru_cache(maxsize=8)
def find_workspace(start: str | Path | None = None) -> Workspace | None:
    """Find the nearest workspace by walking up from ``start`` (default: cwd).

    Returns None when there is no ``budgie.yaml`` anywhere above -- the caller
    then falls back to the bundled sample data.

    Cached, because a single command resolves several inputs and each would
    otherwise re-walk the tree and re-parse the YAML. Call
    :func:`forget_workspaces` after writing or moving a config.
    """
    here = Path(start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        config = directory / CONFIG_NAME
        if config.is_file():
            logger.debug("Using workspace %s", config)
            return load_workspace(config)

    child = _only_child_workspace(here)
    if child is not None:
        # `budgie init` puts the project in a subfolder, so the very next thing
        # a user does is run a command one level above it. Walking up alone
        # would send them back to the bundled samples, which look like real
        # output and hide the mistake.
        logger.info("Using the project in %s/", child.parent.name)
        return load_workspace(child)
    return None


def _only_child_workspace(directory: Path) -> Path | None:
    """The config of the single project directly below ``directory``.

    Exactly one, or nothing: with two candidates there is no right answer and
    guessing would silently pick a budget the user didn't mean.
    """
    try:
        children = sorted(directory.iterdir())
    except OSError:
        return None
    configs = [
        d / CONFIG_NAME
        for d in children
        if d.is_dir() and not d.name.startswith(".") and (d / CONFIG_NAME).is_file()
    ]
    return configs[0] if len(configs) == 1 else None


def forget_workspaces() -> None:
    """Drop the :func:`find_workspace` cache (after init, or in tests)."""
    find_workspace.cache_clear()


def load_workspace(config_path: str | Path) -> Workspace:
    """Read a ``budgie.yaml`` into a :class:`Workspace`."""
    import yaml

    path = Path(config_path).resolve()
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise TypeError(f"{path.name} must be a mapping, got {type(data).__name__}")

    settings = {k: data[k] for k in SETTINGS if k in data}
    # Anything under `inputs:` overrides a default filename; `budget:` doubles
    # as a plain number, so it is only a path when it looks like one.
    paths = dict(data.get("inputs") or {})
    unknown = set(paths) - set(INPUTS)
    if unknown:
        raise ValueError(
            f"{path.name}: unknown inputs {sorted(unknown)}; "
            f"expected any of {sorted(INPUTS)}"
        )
    if "budget" in data and isinstance(data["budget"], (int, float)):
        settings["budget"] = data["budget"]

    logger.info("Workspace %s", path)
    return Workspace(root=path.parent, settings=settings, paths=paths)
