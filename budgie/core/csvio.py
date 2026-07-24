"""
Tiny CSV reading layer shared by every loader in the engine.

Budgie's inputs are small, flat, human-edited CSVs -- a few dozen rows at most.
The stdlib ``csv`` module reads those perfectly well, and it costs nothing to
import, whereas pandas costs roughly half a second before ``budgie --help`` can
even print. Since every loader immediately iterates rows into frozen dataclasses
and never touches a DataFrame again, there was nothing to give up.

Everything here returns plain strings; the ``as_*`` helpers do the conversions
with error messages that name the column and the offending value, because these
files are edited by hand and a typo should say where it is.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from pathlib import Path

# Accepted date spellings, most-preferred first. ISO is what we document and
# write in templates; the other two are what spreadsheets export.
_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d")

Row = dict[str, str]


class Table(list):
    """Rows, plus the header they came from.

    A list of row dicts is all any caller iterates, but a loader that picks its
    input shape from the columns present (``loader.load_people``) still needs the
    header when the file has none -- so it hangs off the list rather than being
    inferred from ``rows[0]``.
    """

    def __init__(self, rows: Iterable[Row], columns: Iterable[str]) -> None:
        super().__init__(rows)
        self.columns = frozenset(columns)


def read_rows(csv_path: str | Path, required: Iterable[str] = ()) -> Table:
    """Read a CSV into a :class:`Table` of ``{column: value}`` dicts.

    Values are stripped strings; blank cells come back as ``""``. Column names
    are stripped and lower-cased so ``Name`` and ``name`` are the same column.

    Raises:
        ValueError: If any of ``required`` is missing from the header.
    """
    path = Path(csv_path)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = [(f or "").strip().lower() for f in (reader.fieldnames or [])]
        missing = set(required) - set(fieldnames)
        if missing:
            raise ValueError(f"{path.name} missing columns: {sorted(missing)}")

        rows = []
        for raw in reader:
            row = {}
            for key, value in zip(fieldnames, raw.values()):
                # A short row yields None for the trailing columns.
                row[key] = (value or "").strip()
            rows.append(row)
    return Table(rows, fieldnames)


def as_float(row: Row, key: str, default: float | None = None) -> float | None:
    """Float value of ``row[key]``, or ``default`` when absent or blank."""
    value = row.get(key, "")
    if value == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{key}: expected a number, got {value!r}") from exc


def as_required_float(row: Row, key: str) -> float:
    """Float value of ``row[key]``, which must be present and non-blank."""
    value = as_float(row, key)
    if value is None:
        raise ValueError(f"{key} is required but blank")
    return value


def as_int(row: Row, key: str) -> int:
    """Integer value of ``row[key]`` (accepts ``12`` and ``12.0``)."""
    value = as_required_float(row, key)
    if value != int(value):
        raise ValueError(f"{key}: expected a whole number, got {value:g}")
    return int(value)


def as_str(row: Row, key: str, default: str = "") -> str:
    """Stripped string value of ``row[key]``, falling back to ``default``."""
    return row.get(key, "") or default


def parse_date(value: str | date) -> date:
    """Parse a date cell, accepting ISO or the usual spreadsheet exports."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    # Spreadsheets sometimes append a midnight time to a date column.
    text = text.split(" ")[0].split("T")[0]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()  # noqa: DTZ007
        except ValueError:
            continue
    raise ValueError(
        f"could not read {value!r} as a date; use YYYY-MM-DD (e.g. 2026-03-15)"
    )


def last_day_of_month(year: int, month: int) -> date:
    """Final calendar day of ``month`` -- the natural month-end as-of date."""
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)
