"""Headline totals for one developer's committed work.

The team audit aggregated per person and then ranked them. A personal audit has
one subject, so this collapses to a single stats block plus the breakdowns the
report actually shows: per repo, per commit category, and the largest single
commit of the period.

Every line figure here is a COMMITTED line change, not a count of unique lines
written: a line edited in three commits is counted three times, and a file moved
and edited counts as both a deletion and an addition. The report says so, because
"lines of code written" is the reading a client will otherwise assume.
"""
from collections import Counter, defaultdict
from datetime import date

from src.classify import IMPLEMENTATION_CATEGORIES


def _span_days(first, last):
    """Inclusive calendar span, so a single-day total reports 1, not 0."""
    if not first or not last:
        return 0
    return (date.fromisoformat(last) - date.fromisoformat(first)).days + 1


def _new_repo_bucket():
    return {"commits": 0, "lines_added": 0, "lines_removed": 0, "files_touched": 0}


def build_totals(enriched):
    """Fold the person's commits into one totals block. Safe on an empty list."""
    repos = defaultdict(_new_repo_bucket)
    categories = Counter()
    types = Counter()
    dates = set()
    emails = set()
    largest = None
    added = removed = raw_added = raw_removed = files = 0
    conventional = refactor = attributed = concurrent = 0

    for c in enriched:
        added += c["lines_added"]
        removed += c["lines_removed"]
        raw_added += c["raw_added"]
        raw_removed += c["raw_removed"]
        files += c["files_changed"]
        dates.add(c["date"])
        emails.add(c["email"])
        categories[c["category"]] += 1
        if c["type"]:
            types[c["type"]] += 1
        if c["is_conventional"]:
            conventional += 1
        if c["is_refactor"]:
            refactor += 1
        if c.get("codex_attributed"):
            attributed += 1
        elif c.get("codex_concurrent"):
            concurrent += 1

        bucket = repos[c["repo"]]
        bucket["commits"] += 1
        bucket["lines_added"] += c["lines_added"]
        bucket["lines_removed"] += c["lines_removed"]
        bucket["files_touched"] += c["files_changed"]

        lines = c["lines_added"] + c["lines_removed"]
        if largest is None or lines > largest["lines"]:
            largest = {"hash": c["hash"][:7], "date": c["date"], "repo": c["repo"],
                       "subject": c["subject"], "lines": lines}

    first = min(dates) if dates else None
    last = max(dates) if dates else None
    commits = len(enriched)
    implementation = sum(n for cat, n in categories.items()
                         if cat in IMPLEMENTATION_CATEGORIES)

    return {
        "commits": commits,
        "lines_added": added,
        "lines_removed": removed,
        "net_lines": added - removed,
        "total_lines_changed": added + removed,
        "raw_added": raw_added,
        "raw_removed": raw_removed,
        "files_touched": files,
        "emails": sorted(emails),
        "repos": {r: dict(v) for r, v in sorted(repos.items())},
        "categories": dict(categories),
        "types": dict(types),
        "conventional_commits": conventional,
        "refactor_commits": refactor,
        "implementation_commits": implementation,
        "supporting_commits": commits - implementation,
        "codex_attributed_commits": attributed,
        "codex_concurrent_commits": concurrent,
        "active_days": len(dates),
        "first_date": first,
        "last_date": last,
        "span_days": _span_days(first, last),
        "avg_lines_per_commit": round((added + removed) / commits, 1) if commits else 0.0,
        "avg_commits_per_active_day": round(commits / len(dates), 1) if dates else 0.0,
        "largest_commit": largest,
    }
