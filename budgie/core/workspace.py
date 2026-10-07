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
      weekly.csv         (or monthly actuals.csv; weekly wins when both exist)

``budgie init`` writes that directory. Every command afterwards finds it by
walking up from the working directory, so you can run ``budgie forecast`` from
anywhere inside the project and get *your* numbers. Explicit ``--people`` style
options still win, and with no workspace at all the bundled samples are used --
so nothing that worked before stops working.

Projects are kept together under a ``budget/`` container, because a budget is
rarely singular -- there's next year's, and the one for the other team::

    my-work/
      budget/
        fy26/
          budgie.yaml
        fy27/
          budgie.yaml

With one project there, commands find it and nothing changes. With several
there is no right answer to guess at, so :func:`find_workspace` returns None and
the front-end lists them -- see :func:`available_projects`. Naming one with
``--project`` resolves it. The flat layout that earlier versions wrote (a
project directly below the current directory) is still discovered, so projects
made before the container existed keep working.

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

# Projects live together under this folder. It is a *container*, not a project:
# `budget/budgie.yaml` is a project called "budget" (the shape earlier versions
# wrote), while `budget/fy26/budgie.yaml` is one called "fy26". Both are found.
PROJECTS_DIR = "budget"

# Every input Budgie knows how to read: config key -> (default filename,
# what it is, which commands consume it).
INPUTS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "people": (
        "people.csv",
        "What an hour of each person costs, and how far their hours may run under or over the plan",
        ("forecast", "monthly", "tui", "scenario"),
    ),
    "allocations": (
        "allocations.csv",
        "FTE allocations and hours spent to date, plus each person's email",
        ("hours", "emails", "plan", "tui"),
    ),
    "plan": (
        "plan.csv",
        "Dated allocation changes -- joins, departures and re-plans, one row each",
        ("plan", "hours", "emails", "tui"),
    ),
    "costs": (
        "costs.csv",
        "Non-labor lines: materials, licences, travel",
        ("forecast", "monthly", "tui"),
    ),
    "budget": (
        "budget.csv",
        "Budget revisions over time (or a single number in budgie.yaml)",
        ("forecast", "monthly", "scenario", "tui"),
    ),
    "actuals": (
        "actuals.csv",
        "Observed spend: monthly hours per person",
        ("forecast", "emails", "tui"),
    ),
    "weekly": (
        "weekly.csv",
        "Observed spend: cumulative hours through an ISO week",
        ("forecast", "emails", "tui"),
    ),
    "scenarios": (
        "scenarios.yaml",
        "Named what-if scenarios to compare",
        ("scenario",),
    ),
}

# Settings a workspace can pin so you stop retyping them on every command.
SETTINGS = ("year", "year_start", "pto", "iterations", "seed")


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
        """A pinned default from ``budgie.yaml`` (year, year_start, pto, iterations, seed)."""
        value = self.settings.get(key)
        return default if value is None else value


@dataclass(frozen=True)
class Project:
    """A project found below the current directory, named for its folder."""

    name: str
    config_path: Path

    @property
    def root(self) -> Path:
        return self.config_path.parent

    def load(self) -> Workspace:
        return load_workspace(self.config_path)


@lru_cache(maxsize=8)
def find_workspace(
    start: str | Path | None = None, project: str | None = None
) -> Workspace | None:
    """Find the workspace to use, from ``start`` (default: cwd).

    Naming a ``project`` picks it out of the ones below; otherwise the nearest
    ``budgie.yaml`` at or above ``start`` wins, and failing that the single
    project below. Returns None when there is nothing to use -- the caller then
    falls back to the bundled sample data, or reports the choice it can't make.

    Cached, because a single command resolves several inputs and each would
    otherwise re-walk the tree and re-parse the YAML. Call
    :func:`forget_workspaces` after writing or moving a config.
    """
    here = Path(start or Path.cwd()).resolve()

    if project:
        # An explicit name beats proximity: `--project fy27` run from inside
        # fy26 has to mean fy27, or the flag would do nothing where it is most
        # likely to be typed. Searching only below `here` would find nothing
        # there -- fy27 is a *sibling* -- so walk up until some directory
        # contains a project by that name.
        for directory in (here, *here.parents):
            for candidate in _projects_below(directory):
                if candidate.name == project:
                    logger.info("Using project %s", candidate.root)
                    return candidate.load()
        return None

    for directory in (here, *here.parents):
        config = directory / CONFIG_NAME
        if _is_config(config):
            logger.debug("Using workspace %s", config)
            return load_workspace(config)

    below = _projects_below(here)
    if len(below) == 1:
        # `budgie init` puts the project in a subfolder, so the very next thing
        # a user does is run a command one level above it. Walking up alone
        # would send them back to the bundled samples, which look like real
        # output and hide the mistake.
        only = below[0]
        logger.info("Using the project in %s/", only.root.name)
        return only.load()
    return None


def available_projects(start: str | Path | None = None) -> list[Project]:
    """The projects a front-end can offer, for listing or browsing.

    This is what makes the ambiguous case actionable: :func:`find_workspace`
    declines to guess between two budgets, and the caller shows these instead of
    a bare "no project found".

    Looks below ``start``, and -- when ``start`` is *itself* a project -- among
    its siblings, since standing in ``budget/fy26`` the thing worth listing is
    the other budgets, not the nothing underneath it.

    Deliberately not a walk to the filesystem root. Somewhere far above you
    there may well be an unrelated ``budgie.yaml``, and offering a stranger's
    budget as a choice here is worse than offering none.
    """
    here = Path(start or Path.cwd()).resolve()
    found = _projects_below(here)
    if found:
        return found
    if _is_config(here / CONFIG_NAME):
        return _projects_below(_container_of(here))
    return []


def _container_of(project_root: Path) -> Path:
    """The directory whose children are ``project_root``'s siblings."""
    parent = project_root.parent
    # Inside the container, siblings are one level further up: `budget/fy26`'s
    # peers are found by listing the directory that holds `budget/`.
    return parent.parent if parent.name == PROJECTS_DIR else parent


def _projects_below(directory: Path) -> list[Project]:
    """Projects directly below ``directory``, and inside its ``budget/``.

    Sorted by name so a listing is stable, and de-duplicated by root so a
    project reachable both ways is only offered once.
    """
    found: dict[Path, Project] = {}
    for parent in (directory, directory / PROJECTS_DIR):
        for child in _child_dirs(parent):
            config = child / CONFIG_NAME
            if _is_config(config):
                found[child] = Project(name=child.name, config_path=config)
    return sorted(found.values(), key=lambda p: p.name)


def _child_dirs(directory: Path) -> list[Path]:
    """Visible subdirectories of ``directory``; empty if it isn't one."""
    try:
        return sorted(
            d for d in directory.iterdir() if d.is_dir() and not d.name.startswith(".")
        )
    except OSError:
        return []


def _is_config(path: Path) -> bool:
    """Whether ``path`` is a readable config file.

    ``Path.is_file()`` propagates PermissionError rather than answering False,
    and discovery walks all the way to the filesystem root -- one unreadable
    directory anywhere above you (a restricted /tmp, a network mount) would
    otherwise crash every command instead of simply not finding a project.
    """
    try:
        return path.is_file()
    except OSError:
        return False


def yaml_problem(exc) -> str:
    """A YAML parse error as one line: what, and where (PyYAML spans five)."""
    mark = getattr(exc, "problem_mark", None)
    what = getattr(exc, "problem", None) or str(exc).splitlines()[0]
    return f"{what} at line {mark.line + 1}" if mark else what


def forget_workspaces() -> None:
    """Drop the :func:`find_workspace` cache (after init, or in tests)."""
    find_workspace.cache_clear()


def load_workspace(config_path: str | Path) -> Workspace:
    """Read a ``budgie.yaml`` into a :class:`Workspace`."""
    import yaml

    path = Path(config_path).resolve()
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{path.name}: not valid YAML ({yaml_problem(exc)})") from exc
    if not isinstance(data, dict):
        raise ValueError(  # noqa: TRY004
            f"{path.name} must be key: value pairs, got a {type(data).__name__}"
        )

    settings = {k: data[k] for k in SETTINGS if k in data}
    if "year_start" in settings:
        from budgie.core.calendar import year_start_month

        try:
            year_start_month(settings["year_start"])
        except ValueError as exc:
            raise ValueError(f"{path.name}: {exc}") from None
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
