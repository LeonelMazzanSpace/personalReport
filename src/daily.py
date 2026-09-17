"""The daily activity table: one row per calendar day, git and Codex side by side.

This is the table a client reads first, so it is also the one that must not
overstate. Two rules come straight from the metric definitions:

* Git columns and Codex columns are measured from different sources and can
  disagree — a day with commits and no recorded turns is normal (work done
  without the assistant, or history Codex did not record), and so is the reverse
  (a day spent on review and investigation that produced no commit).
* With a reporting period set, EVERY day of the period gets a row, including the
  empty ones. A table that lists only busy days reads as if the month were busier
  than it was.
"""
from collections import defaultdict


def _new_row(day):
    return {
        "date": day, "commits": 0, "added": 0, "removed": 0, "files": 0,
        "repos": set(), "codex_attributed": 0,
        "tasks": 0, "turns": 0, "runtime_seconds": 0,
    }


def build_daily(enriched, codex_by_day=None, days=()):
    """Merge per-commit rows and per-day Codex rows into one ordered table.

    `days` is the period's full day list; any day carrying activity is added even
    if it falls outside, so a mismatch between the period and the data can never
    hide a row.
    """
    codex_by_day = codex_by_day or {}
    rows = {day: _new_row(day) for day in days}

    for c in enriched:
        row = rows.setdefault(c["date"], _new_row(c["date"]))
        row["commits"] += 1
        row["added"] += c["lines_added"]
        row["removed"] += c["lines_removed"]
        row["files"] += c["files_changed"]
        row["repos"].add(c["repo"])
        if c.get("codex_attributed"):
            row["codex_attributed"] += 1

    for day, stats in codex_by_day.items():
        row = rows.setdefault(day, _new_row(day))
        row["tasks"] = stats["tasks"]
        row["turns"] = stats["turns"]
        row["runtime_seconds"] = stats["runtime_seconds"]

    ordered = []
    for day in sorted(rows):
        row = dict(rows[day])
        row["repos"] = sorted(row["repos"])
        row["net"] = row["added"] - row["removed"]
        row["active"] = bool(row["commits"] or row["turns"])
        ordered.append(row)
    return ordered


def daily_totals(rows):
    """Column totals, plus the three active-day counts the report reports separately."""
    commit_days = sum(1 for r in rows if r["commits"])
    codex_days = sum(1 for r in rows if r["turns"])
    return {
        "days_listed": len(rows),
        "active_days": sum(1 for r in rows if r["active"]),
        "commit_days": commit_days,
        "codex_days": codex_days,
        "commits": sum(r["commits"] for r in rows),
        "added": sum(r["added"] for r in rows),
        "removed": sum(r["removed"] for r in rows),
        "net": sum(r["net"] for r in rows),
        "files": sum(r["files"] for r in rows),
        "codex_attributed": sum(r["codex_attributed"] for r in rows),
        "turns": sum(r["turns"] for r in rows),
        "runtime_seconds": sum(r["runtime_seconds"] for r in rows),
    }


def by_month(rows):
    """Roll the daily table up to calendar months, for the monthly breakdown."""
    months = defaultdict(lambda: {
        "commits": 0, "added": 0, "removed": 0, "files": 0,
        "tasks": 0, "turns": 0, "runtime_seconds": 0,
        "commit_days": 0, "codex_days": 0,
    })
    for row in rows:
        m = months[row["date"][:7]]
        for key in ("commits", "added", "removed", "files", "turns",
                    "runtime_seconds"):
            m[key] += row[key]
        m["tasks"] += row["tasks"]
        if row["commits"]:
            m["commit_days"] += 1
        if row["turns"]:
            m["codex_days"] += 1
    return {key: {**value, "net": value["added"] - value["removed"]}
            for key, value in sorted(months.items())}


def build_day_items(enriched):
    """date -> the day's commits, oldest first, in the shape the modal renders.

    Kept out of build_daily because the daily TABLE needs none of it and the
    calendar modal needs nothing else; shipping the items inside every table row
    would put the whole commit list in the report twice.
    """
    items = defaultdict(list)
    for c in sorted(enriched, key=lambda x: (x["date"], x["time"], x["hash"])):
        items[c["date"]].append({
            "hash": c["hash"][:7],
            "time": c["time"],
            "repo": c["repo"],
            "category": c["category"],
            "subject": c["subject"],
            "added": c["lines_added"],
            "removed": c["lines_removed"],
            "codex": bool(c.get("codex_attributed")),
        })
    return dict(items)
