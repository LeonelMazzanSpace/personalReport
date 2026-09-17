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
             "follows it, up to the next instruction or the end of the session."),
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


def build_activity(sessions, period=None, timezone_name=None, coverage=None):
    """Fold parsed sessions into the activity metrics. Pure: takes sessions, not paths.

    `available` is False when no session could be read at all. The report prints
    "Unavailable" for every Codex metric in that case instead of zeros, because a
    zero would assert that no assistant work happened — a claim this data cannot
    support when the history simply was not found.
    """
    zone = get_zone(timezone_name)
    bounds = _period_bounds(period, zone)
    coverage = dict(coverage or {})

    by_day = defaultdict(lambda: {"tasks": set(), "turns": 0, "runtime_seconds": 0})
    task_ids = set()
    turns_total = 0
    all_intervals = []
    turns_without_duration = 0

    for index, session in enumerate(sessions):
        key = session.get("id") or session.get("path") or index
        counted = False
        for turn in session["turns"]:
            interval = (turn["start"], turn["end"])
            if bounds:
                clipped = clip(interval, *bounds) if interval[1] > interval[0] else None
                if clipped is None:
                    # A zero-length turn has nothing to clip; keep it if its instant
                    # falls inside the window, so it still counts as a turn.
                    if not (bounds[0] <= interval[0] < bounds[1]):
                        continue
                    clipped = interval
                interval = clipped
            turns_total += 1
            counted = True
            if interval[1] > interval[0]:
                all_intervals.append(interval)
                for day, seconds in split_by_day(interval, zone):
                    by_day[day]["runtime_seconds"] += seconds
                    by_day[day]["tasks"].add(key)
                    by_day[day]["turns"] += 1
            else:
                turns_without_duration += 1
                day = interval[0].astimezone(zone).date().isoformat()
                by_day[day]["tasks"].add(key)
                by_day[day]["turns"] += 1
        if counted:
            task_ids.add(key)

    merged = merge_intervals(all_intervals)
    runtime = int(sum((e - s).total_seconds() for s, e in merged))

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
    }


def collect_codex_activity(sessions_dir, project_paths=(), period=None,
                           timezone_name=None):
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
                          coverage=coverage)
