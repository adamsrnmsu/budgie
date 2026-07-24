"""
Templates written by ``budgie init``.

The files are generated from strings here rather than shipped as package data so
they can't drift out of sync with the loaders that read them, and so the
scaffold works from any install without extra packaging configuration.

Note the CSVs carry **no comment lines**. A ``#`` row is just a malformed record
to a CSV reader, so every explanation lives in ``budgie.yaml`` (which is YAML and
does take comments) and in the generated ``README.md``. The example rows are real,
loadable data -- ``budgie forecast`` works the moment ``init`` finishes.
"""

from __future__ import annotations

import logging
from pathlib import Path

from budgie.core.workspace import CONFIG_NAME, INPUTS, PROJECTS_DIR

logger = logging.getLogger(__name__)

# `budgie init` writes into a subfolder by default. Ten files loose in whatever
# directory you happened to be standing in is clutter, and a project is a thing
# you keep -- it deserves its own folder.
DEFAULT_PROJECT_DIR = PROJECTS_DIR

# What the project is called when you accept the prompt without typing a name.
# Something neutral, because the container it sits in is already called
# `budget/` -- `budget/budget/` would be a silly thing to have written.
DEFAULT_PROJECT_NAME = "main"


CONFIG_TEMPLATE = """\
# Budgie project configuration.
#
# Every command finds this file by walking up from wherever you run it, so
# `budgie forecast` anywhere inside this directory uses your numbers. A command
# line option still wins over anything set here.
#
# See `budgie assumptions` for what the engine assumes, and `budgie status` for
# which of the files below exist.

# Defaults, so you stop retyping them.
year: {year}
pto: 0            # PTO/sick days per person; pro-rated by FTE (see `budgie assumptions`)
iterations: 10000 # Monte Carlo runs
seed: 42          # fixed seed => reproducible numbers; remove for fresh draws

# The budget to signal against: a number here, or point `inputs.budget` at a
# CSV of dated revisions to keep the history of increases and cuts.
budget: 720000

# Where the inputs live. Paths are relative to this file. Delete a line to use
# the default filename; every input is optional until a command needs it.
inputs:
  people: people.csv
  allocations: allocations.csv
  plan: plan.csv
  costs: costs.csv
  actuals: actuals.csv
"""

PEOPLE_CSV = """\
name,hourly_cost,util_low,util_mode,util_high
Alice,95,0.80,0.90,0.98
Bob,110,0.70,0.85,0.95
"""

ALLOCATIONS_CSV = """\
name,fte,hours_spent,email,pto_days
Alice,0.25,180,alice@example.com,
Bob,0.50,760,bob@example.com,20
"""

PLAN_CSV = """\
name,effective_date,fte
Alice,{year}-01-01,0.25
Bob,{year}-01-01,0.50
Bob,{year}-09-01,0.00
"""

COSTS_CSV = """\
name,category,date,amount,low,high,recurring
Laptops,materials,{year}-03-15,12000,11000,14000,no
Cloud hosting,services,{year}-01-01,2000,,,yes
"""

BUDGET_CSV = """\
effective_date,amount,note
{year}-01-01,720000,Original
{year}-05-01,780000,Q2 increase
"""

ACTUALS_CSV = """\
name,month,hours
Alice,1,32
Alice,2,28
Bob,1,80
Bob,2,74
"""

WEEKLY_CSV = """\
name,week,hours_to_date
Alice,12,150
Alice,20,180
Bob,12,600
Bob,20,760
"""

SCENARIOS_YAML = """\
# Named what-if scenarios, compared side by side by `budgie scenario`.
# The FIRST scenario is the baseline: deltas and the BLUE "no change" signal
# are both measured against it.
budget: 720000
iterations: 10000
seed: 42

scenarios:
  - name: Baseline
    people: people.csv
    year: {year}
    pto: 0

  - name: With 15 PTO days
    people: people.csv
    year: {year}
    pto: 15
"""

README_TEMPLATE = """\
# Budgie project

Run any Budgie command from this directory (or below it) and it will use these
files. `budgie status` shows which exist; `budgie assumptions` shows what the
engine assumes about time and money.

## Files

{file_list}

## Editing

These are plain CSVs -- open them in a spreadsheet or an editor. A few rules the
engine cares about:

- **`plan.csv` is append-only.** Someone joining, leaving, or being re-planned
  is a new row with the date it takes effect. Never edit an old row: that's how
  you keep the record of what changed and when.
- **`weekly.csv` values are cumulative**, not per-week. "Hours booked *to date*
  as of week N." Budgie rejects a series that goes down, because that means
  per-period numbers were pasted in by mistake.
- **`budget.csv` is append-only too.** Add a revision rather than overwriting the
  amount, and Budgie can show you the drift from the original.
- **PTO is pro-rated by FTE.** A person at 0.25 FTE gives this project a quarter
  of their PTO, not all of it. Set `pto_days` on a person's row to override the
  project default.

Not sure what a column means? `budgie guide <file>` explains any one of them --
its columns, an example, and what the engine does with it.

## Next

    budgie guide         # the five phases, in order, from here to a forecast
    budgie status        # what's here and what's missing
    budgie forecast      # what will this cost, with confidence bounds
    budgie hours         # who has how many hours left
    budgie emails        # per-person drafts (writes files, never sends)
"""


def _file_list() -> str:
    return "\n".join(
        f"- `{filename}` -- {description}  \n  *used by:* "
        + ", ".join(f"`budgie {c}`" for c in used_by)
        for filename, description, used_by in INPUTS.values()
    )


def scaffold_files(year: int) -> dict[str, str]:
    """Filename -> contents for a fresh workspace."""
    return {
        CONFIG_NAME: CONFIG_TEMPLATE.format(year=year),
        "README.md": README_TEMPLATE.format(file_list=_file_list()),
        "people.csv": PEOPLE_CSV,
        "allocations.csv": ALLOCATIONS_CSV,
        "plan.csv": PLAN_CSV.format(year=year),
        "costs.csv": COSTS_CSV.format(year=year),
        "budget.csv": BUDGET_CSV.format(year=year),
        "actuals.csv": ACTUALS_CSV,
        "weekly.csv": WEEKLY_CSV,
        "scenarios.yaml": SCENARIOS_YAML.format(year=year),
    }


def init_workspace(
    directory: str | Path, year: int, overwrite: bool = False
) -> tuple[list[Path], list[Path]]:
    """Write a starter workspace into ``directory``.

    Existing files are left alone unless ``overwrite`` is set -- re-running
    ``budgie init`` in a live project must never quietly eat someone's numbers.

    Returns:
        ``(written, skipped)`` paths.
    """
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)

    written, skipped = [], []
    for filename, contents in scaffold_files(year).items():
        path = root / filename
        if path.exists() and not overwrite:
            skipped.append(path)
            continue
        path.write_text(contents)
        written.append(path)

    logger.info(
        "Scaffolded %d file(s) into %s (%d already existed)",
        len(written),
        root,
        len(skipped),
    )
    return written, skipped


def delete_project(directory: str | Path) -> list[Path]:
    """Delete a project directory outright, returning what was removed.

    This is the one irreversible thing Budgie does, so it refuses everything it
    isn't certain about rather than deleting its best guess:

    * the directory must hold a ``budgie.yaml`` -- so a mistyped path takes the
      error and not the contents of somebody's home directory;
    * it must not be a symlink, which would otherwise follow somewhere else;
    * it must not contain the working directory, because deleting the ground
      you are standing on leaves every later command resolving against a path
      that no longer exists.

    Callers are expected to have confirmed with the user first: by the time this
    runs, the files are going.
    """
    import shutil

    from budgie.core.workspace import CONFIG_NAME

    root = Path(directory).resolve()
    if root.is_symlink():
        raise ValueError(f"{root} is a symlink, not a project directory")
    if not (root / CONFIG_NAME).is_file():
        raise ValueError(f"{root} is not a Budgie project (no {CONFIG_NAME})")

    cwd = Path.cwd().resolve()
    if root == cwd or root in cwd.parents:
        raise ValueError(f"{root} is the directory you're in -- cd out of it first")

    removed = sorted(p for p in root.rglob("*") if p.is_file())
    shutil.rmtree(root)
    logger.info("Deleted project %s (%d file(s))", root, len(removed))
    return removed
