"""Decide which commits carry evidence of assistant involvement — and how strong it is.

The report must not claim that everything committed during a month of using Codex
was written by Codex. So evidence comes in two clearly separated strengths, and
they are never added together:

* **attributed** — the commit message itself says so: a `Co-authored-by` trailer
  naming the assistant, a "Generated with" footer, an explicit `Assisted-by`.
  This is direct evidence and is what the report's "Codex-assisted commits"
  figure counts.
* **concurrent** — the commit was authored inside a recorded Codex session
  interval. This is circumstantial only: it says the assistant was running, not
  that it wrote the commit. The report shows it as context, labelled as such.

The patterns are configurable (`codex.commit_evidence` in the audit config) so a
team whose trailer says something else does not have to patch the engine.
"""
import re

DEFAULT_EVIDENCE_PATTERNS = [
    r"(?im)^\s*co-authored-by:.*\bcodex\b",
    r"(?im)^\s*co-authored-by:.*\bclaude\b",
    r"(?im)^\s*(assisted|generated|written)[- ]by:.*\b(codex|claude|copilot)\b",
    r"(?im)generated with \[?(codex|claude code)\]?",
    r"(?im)^\s*codex-session:",
]


def compile_patterns(patterns=None):
    return [re.compile(p) for p in (patterns or DEFAULT_EVIDENCE_PATTERNS)]


def has_attribution(message, patterns):
    """True when the commit message carries an explicit assistant attribution."""
    if not message:
        return False
    return any(p.search(message) for p in patterns)


def commit_instant(commit, zone):
    """The commit's author time as an aware datetime in the reporting timezone.

    Extraction converts the author timestamp to the configured reporting timezone
    and dated travel changes before storing local date/time. This reconstruction
    uses the matching zone and retains the stored minute precision.
    """
    from datetime import datetime
    return datetime.strptime(f"{commit['date']} {commit['time']}",
                             "%Y-%m-%d %H:%M").replace(tzinfo=zone)


def annotate(enriched, bodies, session_intervals=(), patterns=None, zone=None,
             timezone_changes=()):
    """Mark every commit with `codex_attributed` and `codex_concurrent`.

    Mutates and returns the same list: the flags are per-commit facts that every
    downstream aggregation wants, and copying a month of commits to add two
    booleans is waste.
    """
    compiled = compile_patterns(patterns)
    merged = list(session_intervals)
    for c in enriched:
        message = "\n".join(filter(None, [c["subject"], bodies.get(c["hash"], "")]))
        c["codex_attributed"] = has_attribution(message, compiled)
        c["codex_concurrent"] = False
        if merged and zone is not None:
            commit_zone = zone
            for change in timezone_changes:
                if c["date"] >= change["from"]:
                    from zoneinfo import ZoneInfo
                    commit_zone = ZoneInfo(change["timezone"])
            instant = commit_instant(c, commit_zone)
            c["codex_concurrent"] = any(s <= instant <= e for s, e in merged)
    return enriched


def summarize(enriched):
    """Counts for the report: total, explicitly attributed, merely concurrent."""
    attributed = sum(1 for c in enriched if c.get("codex_attributed"))
    concurrent = sum(1 for c in enriched
                     if c.get("codex_concurrent") and not c.get("codex_attributed"))
    return {
        "commits": len(enriched),
        "attributed": attributed,
        "concurrent_only": concurrent,
        "no_evidence": len(enriched) - attributed - concurrent,
    }
