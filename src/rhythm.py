"""Day-of-week and hour-of-day activity distributions.

Both axes use the reporting timezone and travel changes applied during extraction.
These distributions measure commit events, not hours worked.
"""
from src.calendar_labels import DOW_LABELS

WORK_START_HOUR = 8
WORK_END_HOUR = 20


def build_rhythm(enriched):
    dow = [{"dow": i, "label": DOW_LABELS[i], "commits": 0, "added": 0, "removed": 0}
           for i in range(7)]
    hours = [{"hour": h, "commits": 0} for h in range(24)]
    weekend = 0
    off_hours = 0

    for c in enriched:
        bucket = dow[c["dow"]]
        bucket["commits"] += 1
        bucket["added"] += c["lines_added"]
        bucket["removed"] += c["lines_removed"]
        hours[c["hour"]]["commits"] += 1
        if c["dow"] >= 5:
            weekend += 1
        if c["hour"] < WORK_START_HOUR or c["hour"] >= WORK_END_HOUR:
            off_hours += 1

    peak_dow = max(dow, key=lambda d: d["commits"]) if enriched else None
    peak_hour = max(hours, key=lambda h: h["commits"]) if enriched else None

    return {
        "dow": dow,
        "hours": hours,
        "peak_dow": peak_dow["label"] if peak_dow else None,
        "peak_hour": peak_hour["hour"] if peak_hour else None,
        "weekend_commits": weekend,
        "off_hours_commits": off_hours,
    }
