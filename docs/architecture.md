# Architecture

Budgie is an engine with two front-ends. The engine, `budgie.core`, holds every
piece of budgeting and forecast math. The CLI (`budgie/budgie.py`) and the
Textual TUI (`budgie/tui.py`) load inputs, call the engine, and render what
comes back. Plots (`budgie/plots.py`) and email drafts (`budgie/emails.py`) are
renderers the front-ends share.

## Two rules

**The engine imports no UI.** Nothing under `budgie/core/` imports click, rich,
matplotlib or textual. That keeps the choice of interface reversible and lets the
engine be tested on its own. Modules under `core/` log through plain
`logging.getLogger(__name__)`; `budgie/singletons.py` is the only place rich is
wired into logging.

**Nothing heavy is imported at module scope in `budgie/budgie.py`.** Click
imports that file just to build the command tree, so engine and rendering
imports live inside the command that needs them. `budgie --help` returns in
about a tenth of a second, and `budgie/tests/test_startup.py` fails if numpy,
holidays, matplotlib, textual, yaml or pyfiglet creep back up to module scope.

## Where things live

| Concern | Module |
| --- | --- |
| Finding the project, the registry of inputs | {py:mod}`budgie.core.workspace` |
| Which input wins when several could apply | {py:mod}`budgie.core.project` |
| `budgie init` and `budgie delete` | {py:mod}`budgie.core.scaffold` |
| Reading CSVs (stdlib `csv`, no pandas) | {py:mod}`budgie.core.csvio`, {py:mod}`budgie.core.loader` |
| Productive hours, holidays, PTO | {py:mod}`budgie.core.calendar` |
| Deterministic forecast and Monte Carlo | {py:mod}`budgie.core.forecast`, {py:mod}`budgie.core.montecarlo` |
| Months weighted by working days | {py:mod}`budgie.core.monthly` |
| Non-labor costs and budget revisions | {py:mod}`budgie.core.costs`, {py:mod}`budgie.core.budget` |
| FTE allocations and dated plans | {py:mod}`budgie.core.allocation`, {py:mod}`budgie.core.plan` |
| Spend readings, estimate at completion, burn-down | {py:mod}`budgie.core.actuals`, {py:mod}`budgie.core.eac`, {py:mod}`budgie.core.burndown` |
| Stoplight signals and scenarios | {py:mod}`budgie.core.signals`, {py:mod}`budgie.core.scenario` |
| Walkthrough and landing-screen content | {py:mod}`budgie.core.guide` |

A new precedence rule ("a file named on the command line beats the project's
copy") belongs in {py:mod}`budgie.core.project`, never in a front-end, because
other tools read Budgie projects through {py:func}`budgie.core.project.load_snapshot`.

## Development

```bash
make test      # pytest
make lint      # ruff check
make format    # isort + ruff format
make docs      # build this site into docs/_build/html
make help      # list all targets
```

The environment comes from perch (`make install` in the perch checkout).

Run a single test:

```bash
pytest budgie/tests/test_core.py::test_productive_hours_matches_definition
```
