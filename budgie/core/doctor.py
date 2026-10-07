"""``budgie doctor``: one status line per thing that can be wrong, read only.

Each check is a :class:`Check` value; the front-end prints them and exits 1 only
when one is ``fail``. Every rule is asked of the core (the loaders
``load_snapshot`` uses, ``budget_source``, ``readings_files``) -- nothing here
re-derives which input wins. Nothing is written.
"""

from __future__ import annotations

import os
import site
import stat
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

OK, WARN, FAIL = "ok", "warn", "fail"
STALE_DAYS = 14
VENV = Path("~/Documents/tools/budgie").expanduser()


@dataclass(frozen=True)
class Check:
    status: str  # ok | warn | fail
    what: str
    fix: str = ""  # shown only when not ok


def _hidden(path: Path) -> bool:
    flag = getattr(stat, "UF_HIDDEN", 0)
    try:
        return bool(flag and getattr(path.stat(), "st_flags", 0) & flag)
    except OSError:
        return False


def environment_checks(env=None, prefix: str | None = None) -> list[Check]:
    env = os.environ if env is None else env
    prefix = sys.prefix if prefix is None else prefix
    out = []
    if Path(prefix).resolve() == VENV.resolve():
        out.append(Check(OK, f"interpreter is the venv's ({prefix})"))
    else:
        out.append(
            Check(
                WARN,
                f"interpreter {prefix} is not {VENV}",
                f"run {VENV}/bin/budgie, or `make venv` and activate it",
            )
        )

    import budgie

    out.append(
        Check(OK, f"budgie imports from {Path(budgie.__file__).resolve().parent}")
    )

    hidden = [
        p
        for d in site.getsitepackages()
        for p in Path(d).glob("*.pth")
        if "budgie" in p.name.lower() and _hidden(p)
    ]
    for p in hidden:
        out.append(
            Check(
                WARN,
                f"{p.name} is marked hidden; Python skips it",
                f"chflags nohidden {p}",
            )
        )
    if not hidden:
        out.append(Check(OK, "no hidden editable-install .pth file"))

    if env.get("VISUAL") or env.get("EDITOR"):
        out.append(Check(OK, "editor set for the TUI's `e` key"))
    else:
        out.append(
            Check(
                WARN,
                "$VISUAL and $EDITOR unset; the TUI's `e` falls back to vim",
                "export EDITOR=nano",
            )
        )
    return out


def sample_checks() -> list[Check]:
    return [
        Check(
            WARN,
            "no project found; commands run on the bundled sample data",
            "budgie init NAME",
        )
    ]


def several_checks(names: list[str]) -> list[Check]:
    return [
        Check(
            WARN,
            f"several projects ({', '.join(names)}); the engine never picks one",
            "budgie doctor --project NAME",
        )
    ]


def project_checks(workspace, today: date) -> list[Check]:
    """Every input loads, and the precedence rules say what you think they do."""
    from budgie.core.allocation import load_allocations
    from budgie.core.budget import coerce_budget
    from budgie.core.calendar import productive_hours, year_span
    from budgie.core.costs import load_costs
    from budgie.core.loader import load_people
    from budgie.core.plan import load_plan
    from budgie.core.project import budget_source, load_observations, readings_files

    cfg = str(workspace.config_path)
    year = workspace.setting("year")
    if year is None:
        return [
            Check(FAIL, f"{cfg}: `year` is not set", f"add `year: {today.year}` to it")
        ]
    try:
        span = year_span(year, workspace.setting("year_start", "01-01"))
    except (TypeError, ValueError) as exc:
        return [Check(FAIL, f"{cfg}: {exc}", f"fix year/year_start in {cfg}")]
    ceiling = productive_hours(span, pto_days=workspace.setting("pto", 0.0))

    out: list[Check] = []
    loaded: dict[str, object] = {}

    def attempt(key: str, load) -> None:
        path = workspace.path_for(key)
        if not path.is_file():
            return
        try:
            loaded[key] = load(str(path))
        except Exception as exc:  # noqa: BLE001 -- any loader error is the finding
            out.append(Check(FAIL, f"{path.name}: {exc}", f"edit {path}"))
        else:
            out.append(Check(OK, f"{path.name} loads"))

    attempt("people", lambda p: load_people(p, productive_hours=ceiling))
    attempt("plan", load_plan)
    attempt(
        "allocations", lambda p: load_allocations(p, ceiling, plan=loaded.get("plan"))
    )
    attempt("costs", lambda p: load_costs(p, span=span))
    attempt("budget", coerce_budget)
    attempt("actuals", lambda p: load_observations(span, actuals=p))
    attempt("weekly", lambda p: load_observations(span, weekly=p))
    attempt("scenarios", lambda p: __import__("yaml").safe_load(Path(p).read_text()))

    # Which budget wins is Budgie's rule; here we only say what the loser held.
    source = budget_source(workspace)
    csv = workspace.path_for("budget")
    if isinstance(source, (int, float)) and csv.is_file():
        other = loaded.get("budget")
        shown = f"{other.latest:,.0f}" if other is not None else "unreadable"
        out.append(
            Check(
                WARN,
                f"budget {source:,.0f} pinned in budgie.yaml wins; "
                f"{csv.name} ({shown}) is ignored",
                f"delete `budget:` from {cfg} to use {csv.name}, or drop {csv.name}",
            )
        )

    actuals, weekly = readings_files(workspace)
    if actuals and weekly:
        out.append(
            Check(
                WARN,
                "weekly.csv and actuals.csv both present; weekly wins, actuals is ignored",
                "delete actuals.csv if it is stale",
            )
        )
    days = [d for obs in (loaded.get("weekly") or {}).values() for d, _ in obs]
    if days:
        age = (today - max(days)).days
        if age > STALE_DAYS:
            out.append(
                Check(
                    WARN,
                    f"latest weekly reading is {age} days old ({max(days)})",
                    "add this week's reading to weekly.csv",
                )
            )
        else:
            out.append(Check(OK, f"latest weekly reading is {age} days old"))

    plan = loaded.get("plan")
    if plan is not None:
        if "people" in loaded:
            known = {p.name for p in loaded["people"]}
            missing = [n for n in plan.names if n not in known]
            # fail, not warn: a name with no people.csv row has no hourly cost
            if missing:
                out.append(
                    Check(
                        FAIL,
                        f"plan.csv names not in people.csv: {', '.join(missing)}",
                        "add them to people.csv or fix the spelling in plan.csv",
                    )
                )
        uncovered = []
        for y, m in span.months:
            last = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
            if sum(plan.fte_on(n, last) for n in plan.names) <= 0:
                uncovered.append(f"{y}-{m:02d}")
        if uncovered:
            out.append(
                Check(
                    WARN,
                    f"plan allocates nobody at the end of {', '.join(uncovered)}",
                    "append plan.csv rows (budgie plan) covering those months",
                )
            )
        else:
            out.append(Check(OK, f"plan covers all of {span.label}"))
    return out
