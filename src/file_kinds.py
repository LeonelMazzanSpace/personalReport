"""Split committed line changes by what kind of file they landed in.

"I wrote 40,000 lines this month" means one thing when it is application code and
another when it is a regenerated lockfile. The prompt asks for source and tests to
be separated from documentation, configuration, lockfiles and generated files
"where classification is reliable" — so this classifier is deliberately
conservative: a path only leaves `code` when a rule matches it outright, and
`unclassified` exists for the cases where nothing does but the extension is not a
known source one either.

Order matters. `generated` is checked first because `dist/app.config.js` is
generated output, not configuration; `tests` before `code` because a test file is
source too but is not what "source code" means in a report.
"""
import re

KIND_ORDER = ["code", "tests", "docs", "config", "generated", "unclassified"]

KIND_LABELS = {
    "code": "Source code",
    "tests": "Tests",
    "docs": "Documentation",
    "config": "Configuration",
    "generated": "Lockfiles / generated",
    "unclassified": "Unclassified",
}

GENERATED_PATTERNS = [
    re.compile(r"(^|/)(yarn\.lock|package-lock\.json|pnpm-lock\.yaml|poetry\.lock|"
               r"Gemfile\.lock|Cargo\.lock|composer\.lock|Podfile\.lock)$"),
    re.compile(r"(^|/)(node_modules|dist|build|out|coverage|\.next|\.expo|vendor|"
               r"__snapshots__|migrations)/"),
    re.compile(r"\.(min\.js|min\.css|map|snap|lock)$"),
    re.compile(r"\.(pb|generated)\.[A-Za-z0-9]+$"),
]

TEST_PATTERNS = [
    re.compile(r"(^|/)(tests?|__tests__|__mocks__|spec|specs|e2e|cypress)/"),
    re.compile(r"(^|/)test_[^/]+\.py$"),
    re.compile(r"[._-](test|spec)\.[A-Za-z0-9]+$"),
    re.compile(r"_test\.[A-Za-z0-9]+$"),
]

DOC_PATTERNS = [
    re.compile(r"(^|/)(docs?|documentation)/"),
    re.compile(r"\.(md|mdx|rst|adoc|txt)$"),
    re.compile(r"(^|/)(README|CHANGELOG|LICENSE|CONTRIBUTING|AUTHORS)[^/]*$"),
]

CONFIG_PATTERNS = [
    re.compile(r"(^|/)\.[^/]*(rc|ignore|env)[^/]*$"),
    re.compile(r"(^|/)(Dockerfile|Makefile|Procfile|Jenkinsfile)[^/]*$"),
    re.compile(r"(^|/)\.github/"),
    re.compile(r"\.(json|ya?ml|toml|ini|cfg|conf|properties|plist|gradle|xml|env)$"),
    re.compile(r"[.-]config\.[A-Za-z0-9]+$"),
]

# Extensions that are unambiguously hand-written program source. Anything outside
# this list that no other rule claims lands in `unclassified` rather than
# inflating the source-code figure.
CODE_EXTENSIONS = frozenset({
    "ts", "tsx", "js", "jsx", "mjs", "cjs", "vue", "svelte", "py", "rb", "go",
    "rs", "java", "kt", "kts", "swift", "m", "mm", "c", "h", "cc", "cpp", "hpp",
    "cs", "php", "scala", "clj", "ex", "exs", "dart", "sol", "sql", "sh", "bash",
    "zsh", "fish", "ps1", "css", "scss", "sass", "less", "html", "htm", "graphql",
    "gql", "prisma", "proto",
})


def _matches(path, patterns):
    return any(p.search(path) for p in patterns)


def file_kind(path):
    """Classify one repo-relative path into one of KIND_ORDER."""
    if _matches(path, GENERATED_PATTERNS):
        return "generated"
    if _matches(path, TEST_PATTERNS):
        return "tests"
    if _matches(path, DOC_PATTERNS):
        return "docs"
    if _matches(path, CONFIG_PATTERNS):
        return "config"
    name = path.rsplit("/", 1)[-1]
    if "." in name and name.rsplit(".", 1)[-1].lower() in CODE_EXTENSIONS:
        return "code"
    return "unclassified"


def _new_bucket():
    return {"added": 0, "removed": 0, "files": 0, "commits": 0}


def classify_lines(commits):
    """Aggregate every touched path of every commit into the six buckets.

    Reads both `files` (what the line totals count) and `excluded_files` (lockfiles
    and vendored trees, which the totals deliberately leave out), so the breakdown
    can show what the headline number excludes instead of just omitting it. The
    `included` flag on each bucket says which side of that line it falls on.
    """
    buckets = {kind: _new_bucket() for kind in KIND_ORDER}
    excluded_lines = {kind: {"added": 0, "removed": 0} for kind in KIND_ORDER}

    for c in commits:
        seen = set()
        for added, removed, path in c["files"]:
            kind = file_kind(path)
            bucket = buckets[kind]
            bucket["added"] += added
            bucket["removed"] += removed
            bucket["files"] += 1
            seen.add(kind)
        for added, removed, path in c.get("excluded_files") or []:
            kind = file_kind(path)
            excluded_lines[kind]["added"] += added
            excluded_lines[kind]["removed"] += removed
        for kind in seen:
            buckets[kind]["commits"] += 1

    return {
        "counted": {k: v for k, v in buckets.items()
                    if v["added"] or v["removed"] or v["files"]},
        "excluded": {k: v for k, v in excluded_lines.items()
                     if v["added"] or v["removed"]},
    }
