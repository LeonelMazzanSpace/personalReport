"""Extract per-commit stats from a git repo via `git log --numstat`.

This module and branches.py are the only ones that shell out to git; everything
downstream works on plain `Commit` objects so it can be tested without a
repository. Every audited repo is read-only here — no fetch, no checkout.
"""
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from src.calendar_labels import month_key

FIELD_SEP = "\x1f"
MARKER = f"COMMIT_START{FIELD_SEP}"

# Paths whose churn is machine-generated, vendored or binary: counted in raw_*
# totals only, never in lines_added/lines_removed. The lockfiles alone would
# dominate every line count. A project adds its own vendored trees via the config
# key `exclude_paths` (regexes, appended to this list) — see AUDIT.md step 3.
DEFAULT_EXCLUDED_PATH_PATTERNS = [
    re.compile(r"(^|/)yarn\.lock$"),
    re.compile(r"(^|/)package-lock\.json$"),
    re.compile(r"(^|/)pnpm-lock\.yaml$"),
    re.compile(r"(^|/)node_modules/"),
    re.compile(r"(^|/)dist/"),
    re.compile(r"(^|/)build/"),
    re.compile(r"(^|/)coverage/"),
    re.compile(r"(^|/)\.yarn/"),
    re.compile(r"(^|/)assets/"),
    re.compile(r"(^|/)public/"),
    re.compile(r"\.min\.js$"),
    re.compile(r"\.map$"),
]


@dataclass
class Commit:
    hash: str
    repo: str       # one of the REPOS labels in run_audit.py
    email: str
    name: str
    date: str       # YYYY-MM-DD
    time: str       # HH:MM
    iso_week: str   # YYYY-Www
    month: str      # YYYY-MM, from the commit's own date — never from its ISO week
    dow: int        # 0 = Monday .. 6 = Sunday
    hour: int
    subject: str
    files: list = field(default_factory=list)   # (added, removed, path), excluded dropped
    # The same tuples for paths the exclusion list drops: lockfiles, vendored
    # trees, build output. They stay out of lines_added/lines_removed but are kept
    # here so the report can show what the headline number leaves out instead of
    # silently omitting it (src/file_kinds.classify_lines reads both lists).
    excluded_files: list = field(default_factory=list)
    body: str = ""                              # commit message body, for trailers
    raw_added: int = 0                          # includes excluded paths
    raw_removed: int = 0

    @property
    def lines_added(self):
        return sum(a for a, _r, _p in self.files)

    @property
    def lines_removed(self):
        return sum(r for _a, r, _p in self.files)

    @property
    def files_changed(self):
        return len(self.files)

    @property
    def raw_lines_added(self):
        return self.raw_added

    @property
    def raw_lines_removed(self):
        return self.raw_removed


def is_excluded_path(path, patterns=DEFAULT_EXCLUDED_PATH_PATTERNS):
    return any(p.search(path) for p in patterns)


def normalize_numstat_path(path):
    """git --numstat renders renames as 'old => new' or 'dir/{old => new}/file'.

    The brace form is located by finding the '{' that opens git's marker — the one
    preceding ' => ' — rather than the first '{' in the string, so a directory whose
    own name contains a brace survives.
    """
    if " => " not in path:
        return path
    arrow = path.index(" => ")
    open_brace = path.rfind("{", 0, arrow)
    if open_brace != -1:
        close_brace = path.find("}", arrow)
        if close_brace != -1:
            pre = path[:open_brace]
            mid = path[open_brace + 1:close_brace]
            post = path[close_brace + 1:]
            return pre + mid.split(" => ")[-1].strip() + post
    return path.split(" => ")[-1].strip()


def iso_week_key(dt):
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def parse_log(output, repo, excluded=DEFAULT_EXCLUDED_PATH_PATTERNS,
              timezone_name=None, timezone_changes=()):
    """Parse `git log --pretty=format:COMMIT_START<sep>... --numstat` output."""
    commits = []
    current = None
    for line in output.splitlines():
        if line.startswith(MARKER):
            # maxsplit=5 keeps any separator inside the subject attached to the subject.
            _, h, email, name, stamp, subject = line.split(FIELD_SEP, 5)
            dt = datetime.fromisoformat(stamp)
            if dt.tzinfo is not None and timezone_name:
                zone = ZoneInfo(timezone_name)
                for change in timezone_changes:
                    next_zone = ZoneInfo(change["timezone"])
                    boundary = datetime.fromisoformat(change["from"]).replace(tzinfo=next_zone)
                    if dt >= boundary:
                        zone = next_zone
                dt = dt.astimezone(zone)
            date = dt.strftime("%Y-%m-%d")
            current = Commit(
                hash=h,
                repo=repo,
                email=email,
                name=name,
                date=date,
                time=dt.strftime("%H:%M"),
                iso_week=iso_week_key(dt),
                month=month_key(date),
                dow=dt.weekday(),
                hour=dt.hour,
                subject=subject,
            )
            commits.append(current)
            continue
        if not line.strip() or current is None:
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added_s, removed_s, path = parts
        if added_s == "-" or removed_s == "-":
            continue                      # binary file: git reports no line counts
        added, removed = int(added_s), int(removed_s)
        current.raw_added += added
        current.raw_removed += removed
        path = normalize_numstat_path(path)
        if is_excluded_path(path, excluded):
            current.excluded_files.append((added, removed, path))
            continue
        current.files.append((added, removed, path))
    return commits


BODY_SEP = "\x1e"


def parse_bodies(output):
    """Parse `git log --format=%H<sep>%B<record-sep>` output into {sha: body}.

    Record-separated rather than line-based, because a commit body is multi-line by
    definition — which is also why it cannot ride along in the numstat stream that
    parse_log reads.
    """
    bodies = {}
    for record in output.split(BODY_SEP):
        record = record.strip("\n")
        if not record.strip():
            continue
        sha, _, body = record.partition(FIELD_SEP)
        bodies[sha.strip()] = body
    return bodies


def extract_bodies(repo_path):
    """Second, cheap pass over the same scope to collect full commit messages.

    Only needed for trailer evidence (Co-authored-by and friends), so it skips
    --numstat entirely and costs a fraction of the main pass.
    """
    cmd = [
        "git", "-C", str(repo_path), "log", "--all", "--no-merges",
        f"--pretty=format:%H{FIELD_SEP}%B{BODY_SEP}",
    ]
    output = subprocess.run(cmd, capture_output=True, text=True,
                            errors="replace", check=True).stdout
    return parse_bodies(output)


def extract_commits(repo_path, repo, excluded=DEFAULT_EXCLUDED_PATH_PATTERNS,
                    timezone_name=None, timezone_changes=()):
    """Run `git log` over ALL refs, excluding merge commits, and parse the result.

    `--all` deliberately includes refs/remotes: typically only the default branch is
    checked out locally, so the remote refs from the last fetch carry every other
    branch. This is why the audit fetches before it reads — see AUDIT.md step 4.
    """
    cmd = [
        "git", "-C", str(repo_path), "log", "--all", "--no-merges",
        # Preserve the source offset before converting to the report's travel timezone.
        "--date=format:%Y-%m-%d %H:%M:%S %z",
        f"--pretty=format:{MARKER}%H{FIELD_SEP}%ae{FIELD_SEP}%an{FIELD_SEP}%ad{FIELD_SEP}%s",
        "--numstat",
    ]
    output = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return parse_log(output, repo, excluded, timezone_name, timezone_changes)
