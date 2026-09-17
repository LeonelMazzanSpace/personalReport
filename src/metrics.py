"""Build the supporting metrics file: aggregates, definitions, collection cutoff.

`data.json` is the full dataset the HTML renders from — every commit item, every
hotspot row. This is the other half: a small, stable document that states the
period's headline numbers, what each of them means, and when they were collected,
so the report can be reproduced or checked without reading the HTML or the full
dataset.

It contains no commit subjects, no file paths, no emails and no session
identifiers. It is aggregates and definitions only, which is what makes it safe to
hand to whoever asks how a figure was reached.
"""
from src.codex_activity import DEFINITIONS as CODEX_DEFINITIONS

COMMIT_DEFINITIONS = {
    "commit": ("A non-merge commit whose git author email is one of the audited "
               "identities, counted once per full SHA."),
    "committed_line_change": ("An added or removed line as reported by git "
                              "--numstat for a counted commit. Repeated edits to "
                              "the same line count once per commit; this is not a "
                              "count of unique lines written."),
    "commit_day": ("A calendar day, in the reporting timezone, carrying at least "
                   "one counted commit."),
    "implementation_commit": ("A commit whose conventional-commit type marks it as "
                              "a feature or a fix. Derived from the commit subject, "
                              "which is the only local signal for it."),
    "codex_attributed_commit": ("A counted commit whose message carries an explicit "
                                "assistant attribution trailer or footer."),
    "codex_concurrent_commit": ("A counted commit authored inside a recorded Codex "
                                "turn interval. Circumstantial evidence only."),
}


def build_metrics(data):
    """Reduce the full dataset to the reproducible metrics document."""
    meta = data["meta"]
    totals = data["totals"]
    codex = data.get("codex") or {}
    daily = data.get("daily_totals") or {}
    evidence = data.get("codex_evidence") or {}
    available = bool(codex.get("available"))

    def codex_value(key):
        """None, not 0, when no history was read: the JSON must not assert a zero."""
        return codex.get(key) if available else None

    return {
        "report": {
            "project": meta.get("project"),
            "person": meta.get("person"),
            "identities": meta.get("emails"),
            "identity_source": (data.get("attribution") or {}).get("source"),
            "repositories": meta.get("repos"),
            "timezone": meta.get("timezone"),
            "git_scope": meta.get("scope"),
            "generated_at": meta.get("generated_at"),
            "collection_cutoff": meta.get("cutoff"),
            "period": meta.get("period") or {"label": "Full available history",
                                             "start": totals.get("first_date"),
                                             "end": totals.get("last_date"),
                                             "month_to_date": False},
        },
        "activity": {
            "codex_tasks": codex_value("tasks"),
            "codex_turns": codex_value("turns"),
            "codex_recorded_runtime_seconds": codex_value("runtime_seconds"),
            "codex_active_days": codex_value("active_days"),
            "human_working_hours": None,
            "by_day": codex.get("by_day") if available else None,
        },
        "commits": {
            "total": totals["commits"],
            "implementation": totals["implementation_commits"],
            "supporting": totals["supporting_commits"],
            "conventional": totals["conventional_commits"],
            "codex_attributed": evidence.get("attributed", 0),
            "codex_concurrent_only": (evidence.get("concurrent_only")
                                      if available else None),
            "no_assistant_evidence": evidence.get("no_evidence"),
            "by_repository": {repo: stats["commits"]
                              for repo, stats in totals["repos"].items()},
            "by_category": totals["categories"],
        },
        "lines": {
            "added": totals["lines_added"],
            "removed": totals["lines_removed"],
            "net": totals["net_lines"],
            "raw_added_including_excluded": totals["raw_added"],
            "raw_removed_including_excluded": totals["raw_removed"],
            "file_changes": totals["files_touched"],
            "by_file_type": (data.get("line_kinds") or {}).get("counted", {}),
            "excluded_from_totals_by_file_type": (data.get("line_kinds")
                                                  or {}).get("excluded", {}),
        },
        "days": {
            "with_commits": daily.get("commit_days", totals["active_days"]),
            "with_codex_activity": codex_value("active_days"),
            "with_either": daily.get("active_days", totals["active_days"]),
            "listed_in_period": daily.get("days_listed"),
            "first": totals.get("first_date"),
            "last": totals.get("last_date"),
        },
        "definitions": {**COMMIT_DEFINITIONS, **CODEX_DEFINITIONS},
        "coverage": {
            "codex_history": codex.get("coverage") or {},
            "codex_metrics_available": available,
            "unresolved_identities": (data.get("attribution") or {}).get("ambiguous",
                                                                        []),
            "duplicate_content": (data.get("duplicates") or {}).get("total") or {},
            "notes": [
                "Uncommitted working-tree changes are excluded from every total.",
                "Binary files carry no line counts and are excluded.",
                "Commits are deduplicated by full SHA; cherry-pick, rebase and "
                "squash copies are distinct SHAs with identical diffs and are "
                "counted separately.",
                "Recorded Codex runtime includes tool execution and waiting, and "
                "is not developer working hours.",
            ],
        },
    }
