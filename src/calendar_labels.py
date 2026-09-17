"""Calendar labels and calendar-month helpers.

Shared by weekly.py, monthly.py, daily rendering and rhythm.py so the day and
month label lists exist in exactly one place. Week helpers stay in weekly.py —
they are ISO-week logic, not calendar logic, and the two must not be conflated
(see D3).

Labels are English: the personal report is written for a client to read.


ISO week helpers live here too: the calendar heatmap lays days out in week
columns, and the week maths is calendar maths.
"""
from datetime import date, timedelta

DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]


def month_key(date_str):
    """'2026-08-04' -> '2026-08'. The commit's OWN calendar month, never its week's."""
    return date_str[:7]


def _parse(key):
    year_s, month_s = key.split("-")
    return int(year_s), int(month_s)


def month_range(first_key, last_key):
    """Every month key from first to last inclusive, including idle months."""
    if not first_key or not last_key:
        return []
    year, month = _parse(first_key)
    end_year, end_month = _parse(last_key)
    keys = []
    while (year, month) <= (end_year, end_month):
        keys.append(f"{year}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return keys


def month_label(key):
    """'2026-08' -> 'Aug 26'."""
    year, month = _parse(key)
    return f"{MONTH_ABBR[month - 1]} {year % 100:02d}"


def month_name(key):
    """'2026-08' -> 'August 2026', for headings rather than axis ticks."""
    year, month = _parse(key)
    return f"{MONTH_NAMES[month - 1]} {year}"


def iso_week_key(day):
    """A date (or YYYY-MM-DD string) -> 'YYYY-Www'."""
    if isinstance(day, str):
        day = date.fromisoformat(day)
    iso = day.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _parse_week(iso_week):
    year_s, week_s = iso_week.split("-W")
    return int(year_s), int(week_s)


def week_bounds(iso_week):
    """Return (monday, sunday) as YYYY-MM-DD strings for an ISO week key."""
    year, week = _parse_week(iso_week)
    monday = date.fromisocalendar(year, week, 1)
    return monday.isoformat(), (monday + timedelta(days=6)).isoformat()


def week_range(first_week, last_week):
    """Every ISO week key from first to last inclusive, including idle weeks."""
    if not first_week or not last_week:
        return []
    cursor = date.fromisocalendar(*_parse_week(first_week), 1)
    end = date.fromisocalendar(*_parse_week(last_week), 1)
    keys = []
    while cursor <= end:
        keys.append(iso_week_key(cursor))
        cursor += timedelta(days=7)
    return keys
