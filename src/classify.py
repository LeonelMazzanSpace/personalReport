"""Classify a commit subject into a conventional-commit type and a work category.

The type table holds the conventional-commit prefixes and nothing else.
`is_conventional` is gated on membership here, so adding or removing an entry
changes the "% conventional" figure as well as the category — non-type prefixes
that occur in the history (`update:`) must stay out, and land in `other`.
"""
import re

CONVENTIONAL_RE = re.compile(
    r"^(?P<type>[A-Za-z]+)(?:\((?P<scope>[^)]+)\))?!?:\s*(?P<desc>.+)$"
)

# Only these words count as a commit type; anything else with a colon is prose.
# Counts measured 2026-09-04 over both repos, --all --no-merges.
TYPE_TO_CATEGORY = {
    "feat": "feature",       # 1564
    "fix": "fix",            # 1315
    "hotfix": "fix",         # 1 — a prod fix is a fix
    "refactor": "refactor",  # 354
    "chore": "refactor",     # 230
    "perf": "refactor",      # 11
    "style": "refactor",     # 8
    "ci": "refactor",        # 6
    "build": "refactor",     # 1
    "test": "test",          # 75
    "docs": "docs",          # 53
    "revert": "revert",      # 11 — its own category, NOT `other`; see D10
    "wip": "wip",            # 21
    "debug": "wip",          # 4
    "spike": "wip",          # 1
}

CATEGORY_ORDER = ["feature", "fix", "refactor", "test", "docs", "revert", "wip", "other"]

CATEGORY_LABELS = {
    "feature": "Features",
    "fix": "Fixes",
    "refactor": "Refactor / chores",
    "test": "Tests",
    "docs": "Docs",
    "revert": "Reverts",
    "wip": "WIP / debug",
    "other": "No convention",
}

# Which categories the report presents as shipped product work, and which are
# supporting work. The prompt requires implemented work to be distinguishable from
# reviews and investigations, and a commit subject is the only local signal for it.
IMPLEMENTATION_CATEGORIES = frozenset({"feature", "fix"})
SUPPORTING_CATEGORIES = frozenset({"refactor", "test", "docs", "revert", "wip",
                                   "other"})


def parse_subject(subject):
    """Return {'type', 'scope', 'is_conventional'} for a commit subject."""
    match = CONVENTIONAL_RE.match(subject.strip())
    if not match:
        return {"type": None, "scope": None, "is_conventional": False}
    ctype = match.group("type").lower()
    if ctype not in TYPE_TO_CATEGORY:
        return {"type": None, "scope": None, "is_conventional": False}
    scope = match.group("scope")
    return {
        "type": ctype,
        "scope": scope.lower() if scope else None,
        "is_conventional": True,
    }


def classify(commit):
    parsed = parse_subject(commit.subject)
    ctype = parsed["type"]
    return {
        "type": ctype,
        "scope": parsed["scope"],
        "is_conventional": parsed["is_conventional"],
        "category": TYPE_TO_CATEGORY.get(ctype, "other"),
        "is_refactor": ctype == "refactor",
    }
