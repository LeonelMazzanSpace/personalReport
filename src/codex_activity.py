"""Aggregate parsed Codex sessions into the report's activity and runtime metrics.

Everything here is expressed in the configured reporting timezone: a turn that
starts at 23:40 and ends at 00:20 contributes to two calendar days, and the split
happens at local midnight, not UTC midnight. Runtime is summed from MERGED
intervals so two sessions running side by side are one stretch of recorded
runtime, not two.

Two counting rules the report states out loud, because they make the daily table
and the headline disagree on purpose:

* A task is counted once in the period total, however many days it spans. The
  daily row counts it on each day it was active, so the daily column can sum to
  more than the headline.
* Idle time between turns is never counted. The gap between "assistant finished"
  and "developer typed the next thing" is not runtime.
"""
from collections import defaultdict
from src.codex_tokens import summarize_tokens
from datetime import datetime, timedelta, timezone

from src.codex_sessions import (belongs_to_project, clip, find_session_files,
                                merge_intervals, parse_session_lines)

try:                                            # Python 3.9+, stdlib
    from zoneinfo import ZoneInfo
except ImportError:                             # pragma: no cover - very old runtimes
    ZoneInfo = None

DEFINITIONS = {
    "task": ("One Codex session: a single conversation started in one working "
             "directory, recorded as one rollout file in the local Codex history."),
    "turn": ("One instruction from the developer plus the assistant work that "
             "follows it, until completion or interruption; older histories fall back "
             "to the last event before the next instruction or session end."),
    "recorded_runtime": ("Wall-clock time inside turn intervals, merged so "
                         "overlapping work counts once. It includes tool execution "
                         "and waiting, and it is not developer working hours."),
    "active_day": ("A calendar day, in the reporting timezone, with at least one "
                   "recorded turn."),
}


def get_zone(name):
    """Resolve a tz name, falling back to UTC rather than failing the run."""
    if not name or ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except Exception:                           # unknown zone, or no tzdata installed
        return timezone.utc


def split_by_day(interval, zone):
    """Split one interval at local midnight -> [(date_str, seconds), ...]."""
    start, end = interval[0].astimezone(zone), interval[1].astimezone(zone)
    out = []
    cursor = start
    while cursor < end:
        midnight = datetime.combine(cursor.date() + timedelta(days=1),
                                    datetime.min.time(), tzinfo=zone)
        chunk_end = min(midnight, end)
        out.append((cursor.date().isoformat(),
                    int((chunk_end - cursor).total_seconds())))
        cursor = chunk_end
    return out


def _period_bounds(period, zone):
    """The period as aware datetimes, or None when the report is full-history."""
    if not period:
        return None
    start = datetime.combine(datetime.fromisoformat(period["start"]).date(),
                             datetime.min.time(), tzinfo=zone)
    end = datetime.combine(datetime.fromisoformat(period["end"]).date(),
                           datetime.min.time(), tzinfo=zone) + timedelta(days=1)
    return start, end


def _zoned_parts(interval, zone, changes):
    """Split at each change, effective at midnight in the destination zone."""
    start, end = interval
    for change in changes:
        next_zone = get_zone(change["timezone"])
        boundary = datetime.fromisoformat(change["from"]).replace(tzinfo=next_zone)
        if boundary <= start:
            zone = next_zone
            continue
        if boundary >= end:
            break
        yield start, boundary, zone
        start, zone = boundary, next_zone
    yield start, end, zone


def build_activity(sessions, period=None, timezone_name=None, coverage=None,
                   timezone_changes=()):
    """Fold parsed sessions into the activity metrics. Pure: takes sessions, not paths.

    `available` is False when no session could be read at all. The report prints
    "Unavailable" for every Codex metric in that case instead of zeros, because a
    zero would assert that no assistant work happened — a claim this data cannot
    support when the history simply was not found.
    """
    zone = get_zone(timezone_name)
    timezone_changes = timezone_changes or ()
    coverage = dict(coverage or {})

    by_day = defaultdict(lambda: {"tasks": set(), "turns": 0, "runtime_seconds": 0})
    task_ids = set()
    turns_total = 0
    all_intervals = []
    turns_without_duration = 0
    token_records = []

    for index, session in enumerate(sessions):
        key = session.get("id") or session.get("path") or index
        for record in session.get("token_records", []):
            stamp = record["timestamp"]
            for _, _, part_zone in _zoned_parts((stamp, stamp), zone, timezone_changes):
                bounds = _period_bounds(period, part_zone)
                if not bounds or bounds[0] <= stamp < bounds[1]:
                    token_records.append((key, record))
        counted = False
        for turn in session["turns"]:
            interval = (turn["start"], turn["end"])
            turn_days = set()
            positive = False
            for start, end, part_zone in _zoned_parts(interval, zone, timezone_changes):
                bounds = _period_bounds(period, part_zone)
                if bounds:
                    if end > start:
                        clipped = clip((start, end), *bounds)
                        if clipped is None:
                            continue
                        start, end = clipped
                    elif not bounds[0] <= start < bounds[1]:
                        continue
                if end > start:
                    positive = True
                    all_intervals.append((start, end))
                    turn_days.update(day for day, _ in split_by_day((start, end), part_zone))
                else:
                    turn_days.add(start.astimezone(part_zone).date().isoformat())
            if not turn_days:
                continue
            counted = True
            turns_total += 1
            if not positive:
                turns_without_duration += 1
            for day in turn_days:
                by_day[day]["tasks"].add(key)
                by_day[day]["turns"] += 1
        if counted:
            task_ids.add(key)

    merged = merge_intervals(all_intervals)
    for interval in merged:
        for start, end, part_zone in _zoned_parts(interval, zone, timezone_changes):
            for day, seconds in split_by_day((start, end), part_zone):
                by_day[day]["runtime_seconds"] += seconds
    runtime = sum(v["runtime_seconds"] for v in by_day.values())

    days = {day: {"tasks": len(v["tasks"]), "turns": v["turns"],
                  "runtime_seconds": v["runtime_seconds"]}
            for day, v in sorted(by_day.items())}

    coverage["turns_without_duration"] = (
        coverage.get("turns_without_duration", 0) + turns_without_duration)

    return {
        "available": bool(coverage.get("files_parsed")),
        # Merged turn intervals as datetimes, for flagging commits authored while a
        # session was running. Underscore-prefixed because it is an intermediate
        # the caller consumes and drops: it never belongs in the written dataset.
        "_intervals": merged,
        "tokens": summarize_tokens(token_records),
        "tasks": len(task_ids),
        "turns": turns_total,
        "runtime_seconds": runtime,
        "active_days": len(days),
        "by_day": days,
        "first_date": min(days) if days else None,
        "last_date": max(days) if days else None,
        "coverage": coverage,
        "definitions": DEFINITIONS,
        "timezone": timezone_name or "UTC",
        "timezone_changes": list(timezone_changes),
    }


def collect_codex_activity(sessions_dir, project_paths=(), period=None,
                           timezone_name=None, timezone_changes=()):
    """Read the sessions directory end to end and return the activity metrics.

    A missing directory is not an error: Codex may not be installed on the machine
    running the audit, or may keep its history elsewhere. The run continues and the
    report declares the metrics unavailable, naming the directory it looked in.
    """
    files = find_session_files(sessions_dir) if sessions_dir else []
    coverage = {
        "sessions_dir": str(sessions_dir) if sessions_dir else None,
        "files_found": len(files),
        "files_parsed": 0,
        "files_failed": 0,
        "sessions_matched": 0,
        "sessions_without_cwd": 0,
        "unreadable_lines": 0,
    }

    sessions = []
    for path in files:
        try:
            parsed = parse_session_lines(path.read_text(errors="replace").splitlines(),
                                         path)
        except OSError:
            coverage["files_failed"] += 1
            continue
        coverage["files_parsed"] += 1
        coverage["unreadable_lines"] += parsed["unreadable_lines"]
        if not parsed["cwd"]:
            coverage["sessions_without_cwd"] += 1
        if not belongs_to_project(parsed, project_paths):
            continue
        coverage["sessions_matched"] += 1
        sessions.append(parsed)

    return build_activity(sessions, period=period, timezone_name=timezone_name,
                          coverage=coverage, timezone_changes=timezone_changes)
