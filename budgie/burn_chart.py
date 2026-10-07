"""Text burn chart for the Forecast tab: a pure `render(series, width, height)`.

x = the span's month-ends, y = labor dollars. `█` spent (up to the latest
reading), `░` the P10-P90 fan, `·` plan, `─` budget. Later marks overwrite
earlier ones. Pure: no Textual, no I/O, so tests read cells directly.
"""

from __future__ import annotations

from budgie.core.burn import BurnSeries

SPENT, FAN, PLAN, BUDGET = "█", "░", "·", "─"
LABEL = 7  # "$1.2M " plus the axis bar
MIN_WIDTH = 40


def _k(v: float) -> str:
    return f"${v / 1e6:.1f}M" if abs(v) >= 1e6 else f"${v / 1e3:.0f}k"


def _at(vals: tuple, x: int, w: int) -> float | None:
    """The series at column x, linear between month points; None over a gap."""
    n = len(vals)
    pos = x * (n - 1) / max(w - 1, 1)
    i = int(pos)
    a = vals[i]
    if a is None or i == n - 1 or pos == i:
        return a
    b = vals[i + 1]
    return None if b is None else a + (b - a) * (pos - i)


def render(series: BurnSeries, width: int, height: int) -> list[str]:
    """`height` lines: plot rows, a month axis row, a legend row."""
    width = max(width, MIN_WIDTH)
    rows = max(height - 2, 3)
    w = width - LABEL
    n = len(series.months)
    fan = bool(series.p90) and len(series.p90) == n
    vals = [
        v
        for s in (series.spent, series.plan, series.budget, series.p90)
        for v in s
        if v is not None
    ]
    top = max(vals, default=0)
    if not n or top <= 0:
        return ["no burn to draw yet"] + [""] * (height - 1)

    grid = [[" "] * w for _ in range(rows)]  # [row from top][column]

    def row(v: float) -> int:
        return max(0, min(rows - 1, round(v / top * (rows - 1))))

    def put(x: int, v: float, mark: str, fill_from: float | None = None) -> None:
        lo = row(v) if fill_from is None else row(fill_from)
        for r in range(lo, row(v) + 1):
            grid[rows - 1 - r][x] = mark

    for x in range(w):
        if fan and (lo := _at(series.p10, x, w)) is not None:
            put(x, _at(series.p90, x, w), FAN, lo)
        if (v := _at(series.spent, x, w)) is not None:
            put(x, v, SPENT, 0)
        if (v := _at(series.plan, x, w)) is not None:
            put(x, v, PLAN)
        if (v := _at(series.budget, x, w)) is not None:
            put(x, v, BUDGET)

    out = []
    for i, cells in enumerate(grid):
        r = rows - 1 - i
        tick = _k(top * r / (rows - 1)) if r in (0, rows - 1, (rows - 1) // 2) else ""
        out.append(f"{tick:>{LABEL - 1}}│" + "".join(cells))
    axis = [" "] * w
    for i, m in enumerate(series.months):
        axis[round(i * (w - 1) / max(n - 1, 1))] = m.strftime("%b")[0]
    out.append(" " * (LABEL - 1) + "└" + "".join(axis))
    legend = [f"{SPENT} spent", f"{PLAN} plan", f"{BUDGET} budget"]
    if fan:
        legend.append(f"{FAN} P10-P90")
    line = "  ".join(legend)
    if series.note:
        line += f"  ({series.note})"
    out.append(line[:width])
    return out
