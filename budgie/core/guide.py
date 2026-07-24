"""
The walkthrough: how to build a budget, and how to change one part of it.

Budgie has a dozen commands and eight input files, and knowing which
command to run second is not something anyone should have to infer. This
module holds that knowledge as data -- ordered phases for building a budget
from nothing, and a per-file topic explaining what to put in it and what
the engine will do with it.

It is deliberately UI-free, like everything else under ``core/``: the CLI
renders these structures with rich, and the strings here carry no markup.
Descriptions and consumers come from :data:`budgie.core.workspace.INPUTS`
so there is one registry of what an input is, not two.
"""

from __future__ import annotations

from dataclasses import dataclass

from budgie.core.workspace import INPUTS


@dataclass(frozen=True)
class Step:
    """One thing to do, and why it's worth doing."""

    action: str  # a command to run, or a file to edit
    why: str
    is_command: bool = True


@dataclass(frozen=True)
class Phase:
    """A stage of building a budget."""

    number: int
    title: str
    goal: str
    steps: tuple[Step, ...]


@dataclass(frozen=True)
class Topic:
    """How to fill in or update one input file."""

    key: str  # matches a key in workspace.INPUTS
    title: str
    purpose: str
    columns: tuple[tuple[str, str], ...]  # (column, meaning)
    example: str
    rules: tuple[str, ...] = ()
    optional: bool = False

    @property
    def filename(self) -> str:
        return INPUTS[self.key][0]

    @property
    def used_by(self) -> tuple[str, ...]:
        return INPUTS[self.key][2]


def _rules(*items: str) -> tuple[str, ...]:
    """Collect rule strings.

    A call rather than a tuple literal on purpose: a rule is a sentence or two
    and has to wrap, and ruff flags implicit string concatenation inside a
    collection literal (ISC004) but not inside a call.
    """
    return items


def _cols(*items: tuple[str, str]) -> tuple[tuple[str, str], ...]:
    """Collect (column, meaning) pairs. A call, for the same reason as _rules."""
    return items


# The help listing, grouped and ordered by when you'd reach for each command
# rather than alphabetically. Summaries live here rather than being sliced out
# of the docstrings, which truncate mid-sentence at any sensible width.
COMMAND_GROUPS: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    (
        "Start here",
        "Create a project and look it over",
        (
            ("init", "Create a project folder with starter files"),
            ("status", "Which inputs exist, and what reads each one"),
            ("assumptions", "What Budgie assumes about time and money"),
            ("guide", "Walk through building a budget, step by step"),
            ("delete", "Remove a project and everything in it"),
        ),
    ),
    (
        "Forecast",
        "What will this cost, and how sure are we",
        (
            ("forecast", "Team cost with P10/P50/P90 confidence bounds"),
            ("monthly", "The same total spread across the year"),
            ("scenario", "Compare what-ifs, with a stoplight per option"),
        ),
    ),
    (
        "Plan",
        "Who is on the project, and when",
        (
            ("plan", "Allocated hours from dated FTE changes"),
            ("hours", "Who has time left, and who is over"),
        ),
    ),
    (
        "Report",
        "Tell people where they stand",
        (("emails", "Per-person drafts (writes files, never sends)"),),
    ),
    (
        "Explore",
        "Everything at once, interactively",
        (("tui", "Live forecast, re-planning and your input files"),),
    ),
)


PHASES: tuple[Phase, ...] = (
    Phase(
        number=1,
        title="Create the project",
        goal="Get a folder with a config and a starter file for every input.",
        steps=(
            Step(
                "budgie init my-budget",
                "Makes budget/my-budget/. Projects live together under budget/, "
                "so next year's can sit beside this one. Leave the name off and "
                "it asks. The starter files hold working example data, so every "
                "command runs before you change a thing.",
            ),
            Step(
                "cd budget/my-budget",
                "Commands find the project by looking up from where you are, "
                "so work from inside it. With more than one project, "
                "--project my-budget picks it from anywhere.",
            ),
            Step(
                "budgie status",
                "Confirms which files exist and which command reads each one.",
            ),
        ),
    ),
    Phase(
        number=2,
        title="Describe the team",
        goal="Two files carry almost all the signal: who costs what, and who is "
        "assigned how much.",
        steps=(
            Step(
                "people.csv",
                "One row per person: their hourly cost, and a low/likely/high "
                "guess at their hours. The guess is what becomes a confidence "
                "range -- widen it when you genuinely don't know.",
                is_command=False,
            ),
            Step(
                "allocations.csv",
                "Each person's FTE share and the hours they've already spent. "
                "This is what `hours` and `emails` report on.",
                is_command=False,
            ),
            Step(
                "budgie guide people",
                "Shows the columns, an example, and the rules for any input "
                "file. Swap in allocations, costs, budget, plan, actuals.",
            ),
        ),
    ),
    Phase(
        number=3,
        title="Check the assumptions",
        goal="Make sure Budgie counts time and money the way your organisation "
        "does, before you trust a number it produces.",
        steps=(
            Step(
                "budgie assumptions",
                "Every modelling choice with its current value: the working "
                "week, this year's holidays, how PTO interacts with part-time "
                "work, the sampling distributions, the signal thresholds.",
            ),
            Step(
                "budgie.yaml",
                "Pin the year, PTO days, iterations, seed and budget here so "
                "you stop passing them on every command.",
                is_command=False,
            ),
        ),
    ),
    Phase(
        number=4,
        title="Read the forecast",
        goal="A cost with honest bounds around it, then the same thing spread "
        "across the year.",
        steps=(
            Step(
                "budgie forecast",
                "The per-person table plus P10/P50/P90. P50 is your expected "
                "cost; P90 is what to reserve.",
            ),
            Step(
                "budgie monthly",
                "The same total, month by month, weighted by real working days. "
                "Shows when the money actually goes out.",
            ),
            Step(
                "budgie scenario",
                "Compare what-ifs side by side. The first scenario in "
                "scenarios.yaml is the baseline everything else is measured "
                "against.",
            ),
        ),
    ),
    Phase(
        number=5,
        title="Keep it current",
        goal="A budget is only useful if it tracks what actually happened.",
        steps=(
            Step(
                "actuals.csv or weekly.csv",
                "Real hours booked. Add readings as they come in -- one is "
                "enough to fix the endpoint, several give a real burn-down.",
                is_command=False,
            ),
            Step(
                "plan.csv",
                "Someone joining, leaving or changing FTE is a NEW dated row. "
                "Never edit an old one: the history is the record.",
                is_command=False,
            ),
            Step(
                "budgie hours",
                "Who has how much time left, and who is over.",
            ),
            Step(
                "budgie emails",
                "A draft per person telling them where they stand and what it "
                "means per week. Writes files only -- it never sends.",
            ),
        ),
    ),
)


TOPICS: tuple[Topic, ...] = (
    Topic(
        key="people",
        title="Team members and their hours",
        purpose="Drives the cost forecast. One row per person.",
        columns=_cols(
            ("name", "Whatever you want to see in the tables"),
            ("hourly_cost", "Fully loaded hourly rate"),
            ("util_low / util_mode / util_high", "Fraction of available hours, 0-1"),
            ("pto_days", "Optional. Overrides the project's PTO for this person"),
        ),
        example=(
            "name,hourly_cost,util_low,util_mode,util_high\n"
            "Alice,95,0.80,0.90,0.98\n"
            "Bob,110,0.70,0.85,0.95"
        ),
        rules=_rules(
            "The three values are a low / most-likely / high estimate. The "
            "forecast table uses the middle one; the Monte Carlo samples the "
            "whole range, so the spread is where your confidence bounds come "
            "from.",
            "Prefer stating hours directly? Use hours_low/hours_mode/hours_high "
            "instead of the util_* columns.",
        ),
    ),
    Topic(
        key="allocations",
        title="FTE allocations and hours spent",
        purpose="Drives `hours` and `emails`. Tracks consumption against a "
        "fixed allocation, which is a different question from forecasting cost.",
        columns=_cols(
            ("name", "Should match the name in people.csv"),
            ("fte", "Share of full time on this project, e.g. 0.25"),
            ("hours_spent", "Hours booked so far"),
            ("email", "Optional. Where the draft is addressed"),
            ("pto_days", "Optional. This person's own PTO"),
        ),
        example=(
            "name,fte,hours_spent,email,pto_days\n"
            "Alice,0.25,180,alice@example.com,\n"
            "Bob,0.50,760,bob@example.com,20"
        ),
        rules=_rules(
            "allocated = fte x (2080 - holidays - PTO). PTO is taken off the "
            "full-time figure first, so a 0.25 FTE person gives this project a "
            "quarter of their PTO, not all of it.",
            "Leave pto_days blank to use the project default from budgie.yaml.",
        ),
    ),
    Topic(
        key="plan",
        title="Allocation changes over time",
        purpose="For when people join, leave, or get re-planned mid-year. Each "
        "row applies from its date until the next row for that person.",
        columns=_cols(
            ("name", "The person"),
            ("effective_date", "YYYY-MM-DD, when this FTE starts applying"),
            ("fte", "Their share from that date on; 0 means off the project"),
        ),
        example=(
            "name,effective_date,fte\n"
            "Alice,2026-01-01,0.25\n"
            "Bob,2026-01-01,0.50\n"
            "Bob,2026-09-01,0.00\n"
            "Carol,2026-07-15,0.50"
        ),
        rules=_rules(
            "APPEND, never edit. Adding someone, zeroing someone out and "
            "re-planning are all the same operation: a new row. That is what "
            "preserves the record of what changed and when.",
            "Before a person's first row they count as 0 FTE.",
            "Hours are counted day by day over real working days, so a "
            "mid-month start is charged from the actual day -- Carol above gets "
            "466 hours, not a rounded 502 or a flat 996.",
        ),
        optional=True,
    ),
    Topic(
        key="costs",
        title="Non-labor costs",
        purpose="Materials, licences, hardware, travel. They sit in the same "
        "totals and the same simulation as labor.",
        columns=_cols(
            ("name", "What it is"),
            ("category", "Free text, used to group the subtotals"),
            ("date", "When it is incurred"),
            ("amount", "The most-likely figure"),
            ("low / high", "Optional. Supply both and it samples like hours do"),
            ("recurring", "yes = charged every month from its own through Dec"),
        ),
        example=(
            "name,category,date,amount,low,high,recurring\n"
            "Laptops,materials,2026-03-15,12000,11000,14000,no\n"
            "Cloud hosting,services,2026-01-01,2000,,,yes"
        ),
        rules=_rules(
            "A recurring line's total is NOT its amount: the cloud row above "
            "books 2000 twelve times, so it totals 24000.",
            "Leave low/high blank for a cost you know exactly.",
            "Costs land in the month they fall, so they show up as a step in "
            "the monthly and fan charts rather than smeared across the year.",
        ),
        optional=True,
    ),
    Topic(
        key="budget",
        title="Budget revisions",
        purpose="The number the stoplight signals compare against. A budget is "
        "rarely one figure for a whole year.",
        columns=_cols(
            ("effective_date", "When this amount takes over"),
            ("amount", "The budget from that date"),
            ("note", "Optional. Why it changed"),
        ),
        example=(
            "effective_date,amount,note\n"
            "2026-01-01,720000,Original\n"
            "2026-05-01,780000,Q2 increase"
        ),
        rules=_rules(
            "Append revisions rather than overwriting the amount, and Budgie "
            "can show the drift from the original.",
            "Signals compare against the LATEST revision, not the original.",
            "A single number in budgie.yaml works too -- use this file when you "
            "want the history.",
        ),
        optional=True,
    ),
    Topic(
        key="actuals",
        title="Observed spend, by month",
        purpose="Turns the burn-down chart from a straight interpolation into a "
        "real curve.",
        columns=_cols(
            ("name", "The person"),
            ("month", "1-12"),
            ("hours", "Hours booked IN that month"),
        ),
        example="name,month,hours\nAlice,1,32\nAlice,2,28\nBob,1,80",
        rules=_rules(
            "These are per-month hours, not running totals. Missing months "
            "count as zero.",
            "If your timesheet exports cumulative readings instead, use "
            "weekly.csv -- see `budgie guide weekly`.",
        ),
        optional=True,
    ),
    Topic(
        key="weekly",
        title="Observed spend, cumulative by week",
        purpose="The shape most timesheet exports actually give you: hours "
        "booked to date as of some week.",
        columns=_cols(
            ("name", "The person"),
            ("week", "ISO week number"),
            ("hours_to_date", "Total hours booked THROUGH that week"),
        ),
        example=("name,week,hours_to_date\nAlice,12,150\nAlice,20,180\nBob,20,760"),
        rules=_rules(
            "CUMULATIVE, not per-week. Budgie rejects a series that goes down, "
            "because a decrease means per-period values were pasted in.",
            "One row per person is enough -- it fixes the endpoint exactly. "
            "More rows give a real curve.",
            "The as-of date comes from the latest reading, so the burn rate is "
            "measured over the right window rather than against today.",
        ),
        optional=True,
    ),
    Topic(
        key="scenarios",
        title="What-if scenarios",
        purpose="Run the same engine over several variations and compare them "
        "side by side.",
        columns=_cols(
            ("budget / iterations / seed", "Shared across every scenario"),
            ("scenarios[].name", "What to call it in the table"),
            ("scenarios[].people", "Which team file to use"),
            ("scenarios[].year / pto", "The assumptions for that variation"),
        ),
        example=(
            "budget: 720000\n"
            "iterations: 10000\n"
            "seed: 42\n"
            "scenarios:\n"
            "  - name: Baseline\n"
            "    people: people.csv\n"
            "    year: 2026\n"
            "    pto: 0\n"
            "  - name: With 15 PTO days\n"
            "    people: people.csv\n"
            "    year: 2026\n"
            "    pto: 15"
        ),
        rules=_rules(
            "The FIRST scenario is the baseline. Cost deltas and the blue "
            "no-change signal are both measured against it.",
            "People paths are relative to this config file.",
        ),
        optional=True,
    ),
)

TOPICS_BY_KEY: dict[str, Topic] = {t.key: t for t in TOPICS}


def topic_names() -> list[str]:
    """Every topic `budgie guide <name>` accepts."""
    return [t.key for t in TOPICS]
