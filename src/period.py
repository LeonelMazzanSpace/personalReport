"""Resolve the reporting period and test dates against it.

The personal audit reports the full history by default. `--month YYYY-MM` narrows
every figure in the report — commits, lines, Codex activity, active days — to one
calendar month, which is the shape the monthly client report needs.

A month that has not finished yet is clipped at the collection cutoff and flagged
`month_to_date`, so the report can label itself instead of implying it covers 30
days when it covers 9. Everything here works on `YYYY-MM-DD` strings in the
configured reporting timezone: the caller renders dates in that timezone before
handing them over, so no tz maths happens below.
"""
from calendar import monthrange
from datetime import date

from src.calendar_labels import MONTH_NAMES


class PeriodError(Exception):
    """The requested period is not a `YYYY-MM` calendar month."""


def parse_month(value):
    """'2026-09' -> (2026, 9). Raises PeriodError on anything else."""
    parts = str(value).split("-")
    if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2:
        raise PeriodError(f"--month must be YYYY-MM, got {value!r}")
    try:
        year, month = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise PeriodError(f"--month must be YYYY-MM, got {value!r}") from exc
    if not 1 <= month <= 12:
        raise PeriodError(f"--month must be YYYY-MM with a real month, got {value!r}")
    return year, month


def month_period(value, today=None):
    """Build the period dict for a `YYYY-MM` month.

    `end` is the last day of the month, or today when the month is still running.
    A month in the future is an error rather than an empty report: it is always a
    typo, and an empty report reads like "no work happened".
    """
    year, month = parse_month(value)
    today = today or date.today()
    start = date(year, month, 1)
    if start > today:
        raise PeriodError(f"--month {value} starts in the future")
    last = date(year, month, monthrange(year, month)[1])
    to_date = last > today
    end = today if to_date else last
    return {
        "key": f"{year}-{month:02d}",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "full_end": last.isoformat(),
        "label": f"{MONTH_NAMES[month - 1]} {year}",
        "month_to_date": to_date,
    }


def in_period(date_str, period):
    """True when a `YYYY-MM-DD` falls inside the period. No period means no filter."""
    if not period:
        return True
    return period["start"] <= date_str <= period["end"]


def period_days(period):
    """Every calendar day of the period, so idle days still get a table row."""
    if not period:
        return []
    start = date.fromisoformat(period["start"]).toordinal()
    end = date.fromisoformat(period["end"]).toordinal()
    return [date.fromordinal(o).isoformat() for o in range(start, end + 1)]
