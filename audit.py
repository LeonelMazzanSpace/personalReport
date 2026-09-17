"""Run a PERSONAL git + Codex contribution audit, driven by a JSON config.

This is the reusable engine. It holds nothing about any particular project: the
repos to read, the project name, whose commits to count and the two
directory-bucketing knobs all come from an `audit.config.json` that lives next to
the project being audited. See AUDIT.md for the end-to-end process, PROMPT.md for
the prompt that drives it, and README.md for the config reference.

Usage
    python3 /path/to/auditProcessPersonal/audit.py                 # ./audit.config.json
    python3 /path/to/auditProcessPersonal/audit.py --month 2026-09 # one calendar month
    python3 /path/to/auditProcessPersonal/audit.py --no-fetch      # skip the git fetch
    python3 /path/to/auditProcessPersonal/audit.py --output-dir /tmp/x

The audited repos are only ever read (`git log`, `git for-each-ref`, `git rev-list`,
`git config --get`) with one exception: unless `--no-fetch` is passed, each repo
gets a `git fetch --all --prune` first. That updates refs/remotes only — it never
touches the working tree, the index, or any local branch. It is on by default
because the audit reads `--all`, and stale remote refs mean a stale report.

The Codex session history is read-only too, and never leaves the machine: only
counts, durations and coverage figures reach the report. No prompt text, no task
identifiers, no file system paths from the sessions.
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.branches import collect_branches, mine as mine_branches
from src.classify import classify
from src.codex_activity import collect_codex_activity, get_zone
from src.codex_evidence import annotate, summarize
from src.codex_sessions import DEFAULT_SESSIONS_DIR, merge_intervals
from src.daily import build_daily, build_day_items, by_month, daily_totals
from src.duplicates import collect_duplicates
from src.extract_commits import (DEFAULT_EXCLUDED_PATH_PATTERNS, extract_bodies,
                                 extract_commits)
from src.file_kinds import classify_lines
from src.hotspots import build_hotspots
from src.me import IdentityError, ambiguous_identities, filter_mine, resolve_identity
from src.metrics import build_metrics
from src.period import PeriodError, in_period, month_period, period_days
from src.rhythm import build_rhythm
from src.totals import build_totals

GIT_SCOPE = "--all --no-merges"
DEFAULT_CONFIG_NAME = "audit.config.json"
DEFAULT_TIMEZONE = "America/Montevideo"

# The contract between enrich() and every downstream module. test_audit pins this,
# so renaming a key here fails the suite instead of the pipeline.
ENRICHED_KEYS = frozenset({
    "repo", "email", "name", "hash", "date", "time", "month", "dow", "hour",
    "subject", "lines_added", "lines_removed", "raw_added", "raw_removed",
    "files_changed", "files", "excluded_files", "type", "scope", "is_conventional",
    "category", "is_refactor",
})


class ConfigError(Exception):
    """The config is missing, malformed, or points at something that is not a repo."""


def load_config(path):
    """Read and validate an audit config. Repo paths resolve against the config file.

    Relative `repos[].path` values are resolved against the config's OWN directory,
    not the shell's cwd, so `python3 .../audit.py --config x/audit.config.json` works
    from anywhere.
    """
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ConfigError(f"config not found: {path}")
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: invalid JSON — {exc}") from exc

    base = path.parent
    project = raw.get("project")
    if not project:
        raise ConfigError(f"{path}: 'project' is required (the name shown on the report)")

    repos_raw = raw.get("repos") or []
    if not repos_raw:
        raise ConfigError(f"{path}: 'repos' must list at least one repo")
    repos = []
    for entry in repos_raw:
        if not entry.get("path"):
            raise ConfigError(f"{path}: every repo needs a 'path'")
        repo_path = (base / entry["path"]).resolve()
        label = entry.get("label") or repo_path.name
        if not (repo_path / ".git").exists():
            raise ConfigError(f"{label}: not a git repo — {repo_path}")
        repos.append({"path": repo_path, "label": label})

    labels = [r["label"] for r in repos]
    duplicated = sorted({l for l in labels if labels.count(l) > 1})
    if duplicated:
        raise ConfigError(f"{path}: duplicate repo labels {duplicated}")

    me = raw.get("me") or {}
    if me and not isinstance(me, dict):
        raise ConfigError(f"{path}: 'me' must be an object with name/emails")

    hotspots = raw.get("hotspots") or {}
    excluded = list(DEFAULT_EXCLUDED_PATH_PATTERNS)
    for pattern in raw.get("exclude_paths") or []:
        try:
            excluded.append(re.compile(pattern))
        except re.error as exc:
            raise ConfigError(
                f"{path}: exclude_paths entry {pattern!r} is not a valid regex — {exc}"
            ) from exc

    codex = raw.get("codex") or {}
    for pattern in codex.get("commit_evidence") or []:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ConfigError(
                f"{path}: codex.commit_evidence entry {pattern!r} is not a valid "
                f"regex — {exc}") from exc
    # Session paths default to the audited repos themselves: a Codex session is
    # this project's when it ran inside one of the clones being audited.
    session_paths = [str((base / p).resolve()) for p in codex.get("project_paths")
                     or []] or [str(r["path"]) for r in repos]

    timezone_changes = raw.get("timezone_changes") or []
    try:
        from zoneinfo import ZoneInfo
        previous = None
        if not isinstance(timezone_changes, list):
            raise ValueError("must be a list")
        for change in timezone_changes:
            day = datetime.strptime(change["from"], "%Y-%m-%d").date()
            if day.isoformat() != change["from"] or (previous and day <= previous):
                raise ValueError("dates must be unique and increasing YYYY-MM-DD values")
            ZoneInfo(change["timezone"])
            previous = day
    except (ValueError, TypeError, KeyError) as exc:
        raise ConfigError(f"invalid timezone_changes: {exc}") from exc

    return {
        "project": project,
        "report_name": raw.get("report_name") or f"report{_slug(project)}.html",
        "repos": repos,
        "me": me,
        "timezone": raw.get("timezone") or DEFAULT_TIMEZONE,
        "timezone_changes": timezone_changes,
        "deep_roots": frozenset(hotspots.get("deep_roots") or ()),
        "nested_segments": frozenset(hotspots.get("nested_segments") or ()),
        "excluded_paths": excluded,
        "codex_sessions_dir": codex.get("sessions_dir", DEFAULT_SESSIONS_DIR),
        "codex_project_paths": session_paths,
        "codex_evidence_patterns": codex.get("commit_evidence") or None,
        "duplicate_scan": bool(raw.get("duplicate_scan", True)),
        "output_dir": (base / (raw.get("output_dir") or "output")).resolve(),
        "config_path": path,
    }


def _slug(project):
    """`My Project` -> `MyProject`, for the default report filename."""
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[\s_-]+", project)
                   if part)


def fetch_repos(repos):
    """`git fetch --all --prune` each repo. Returns a list of (label, error) failures.

    A failure is reported and the audit continues against whatever refs the clone
    already has, rather than aborting — an offline run of a stale clone is still a
    useful report, as long as the staleness is visible. The caller prints it.
    """
    failures = []
    for repo in repos:
        result = subprocess.run(
            ["git", "-C", str(repo["path"]), "fetch", "--all", "--prune"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            failures.append((repo["label"], (result.stderr or "").strip().splitlines()))
    return failures


def enrich(commits):
    """Turn already-filtered Commit objects into the plain dicts everything reads."""
    return [{
        "repo": c.repo,
        "email": c.email,
        "name": c.name,
        "hash": c.hash,
        "date": c.date,
        "time": c.time,
        "month": c.month,
        "dow": c.dow,
        "hour": c.hour,
        "subject": c.subject,
        "lines_added": c.lines_added,
        "lines_removed": c.lines_removed,
        "raw_added": c.raw_lines_added,
        "raw_removed": c.raw_lines_removed,
        "files_changed": c.files_changed,
        "files": c.files,
        "excluded_files": c.excluded_files,
        **classify(c),
    } for c in commits]


def build_duplicates_section(duplicates):
    """Fold per-repo collect_duplicates() results into a report-ready section.

    Absent or empty input yields {}, not a zeroed structure — the disclosure note
    keys off this being falsy to stay silent when there is nothing to disclose.
    """
    if not duplicates:
        return {}
    by_repo = {d["repo"]: {k: v for k, v in d.items() if k != "repo"}
               for d in duplicates}
    total = {key: sum(d[key] for d in duplicates)
             for key in ("commits", "redundant", "groups", "unique", "no_patch")}
    return {"by_repo": by_repo, "total": total}


def build_data(enriched, identity, repos, codex, evidence, branches,
               period=None, timezone_name=None, project=None, generated_at=None,
               cutoff=None, duplicates=None, ambiguous=(), deep_roots=frozenset(),
               nested_segments=frozenset()):
    """Assemble the full dataset the report and the metrics file are rendered from."""
    totals = build_totals(enriched)
    days = period_days(period)
    daily = build_daily(enriched, (codex or {}).get("by_day"), days)

    # Repos actually present in the data, in first-appearance order — not the
    # configured list — so the report names what it actually shows. Falls back to
    # the configured labels only when there is no data at all, so an empty report
    # still names every repo that was read.
    present = list(dict.fromkeys(c["repo"] for c in enriched))

    return {
        "totals": totals,
        "daily": daily,
        "daily_totals": daily_totals(daily),
        "day_items": build_day_items(enriched),
        "monthly": by_month(daily),
        "codex": codex or {},
        "codex_evidence": evidence or {},
        "line_kinds": classify_lines(enriched),
        "rhythm": build_rhythm(enriched),
        "hotspots": build_hotspots(enriched, deep_roots=deep_roots,
                                   nested_segments=nested_segments),
        "branches": branches,
        "duplicates": build_duplicates_section(duplicates),
        "attribution": {
            "source": identity["source"],
            "emails": identity["emails"],
            "detected_emails": identity["detected_emails"],
            "ambiguous": list(ambiguous),
        },
        "meta": {
            "project": project,
            "person": identity["name"],
            "emails": identity["emails"],
            "repos": present or list(repos),
            "scope": GIT_SCOPE,
            "timezone": timezone_name,
            "period": period,
            "generated_at": generated_at or datetime.now().strftime("%Y-%m-%d %H:%M"),
            "cutoff": cutoff or datetime.now().strftime("%Y-%m-%d %H:%M %Z").strip(),
            "range": {"first": totals["first_date"], "last": totals["last_date"]},
        },
    }


def run(config, output_dir=None, fetch=True, month=None, today=None):
    """Execute the pipeline for a loaded config. Returns (data, fetch_failures)."""
    from src.generate_report import generate_report

    repos = config["repos"]
    fetch_failures = fetch_repos(repos) if fetch else []
    report_now = datetime.now(get_zone(config["timezone"]))
    period = month_period(month, today or report_now.date()) if month else None

    identity = resolve_identity(config["me"], repos)
    excluded = config["excluded_paths"]

    all_commits, branches, bodies, duplicates = [], [], {}, []
    for repo in repos:
        all_commits.extend(extract_commits(
            repo["path"], repo["label"], excluded, config["timezone"],
            config.get("timezone_changes", ())))
        branches.extend(mine_branches(
            collect_branches(repo["path"], repo["label"]), identity["emails"]))
        bodies.update(extract_bodies(repo["path"]))
        if config["duplicate_scan"]:
            duplicates.append(collect_duplicates(repo["path"], repo["label"]))
    branches.sort(key=lambda b: (-b["commits"], b["repo"], b["name"]))

    ambiguous = ambiguous_identities(all_commits, identity)
    mine = [c for c in filter_mine(all_commits, identity) if in_period(c.date, period)]
    enriched = enrich(mine)

    codex = collect_codex_activity(config["codex_sessions_dir"],
                                   config["codex_project_paths"], period,
                                   config["timezone"], config.get("timezone_changes", ()))
    # Popped, not read: the raw intervals are an input to commit annotation and
    # must not reach data.json.
    intervals = merge_intervals(codex.pop("_intervals", []))
    annotate(enriched, bodies, intervals,
             patterns=config["codex_evidence_patterns"],
             zone=get_zone(config["timezone"]),
             timezone_changes=config.get("timezone_changes", ()))
    evidence = summarize(enriched)

    timezone_label = config["timezone"] + "".join(
        f"; {change['timezone']} from {change['from']}"
        for change in config.get("timezone_changes", ()))
    data = build_data(
        enriched, identity, [r["label"] for r in repos], codex, evidence, branches,
        period=period, timezone_name=timezone_label, project=config["project"],
        generated_at=report_now.strftime("%Y-%m-%d %H:%M %Z"),
        cutoff=report_now.isoformat(),
        duplicates=duplicates, ambiguous=ambiguous,
        deep_roots=config["deep_roots"], nested_segments=config["nested_segments"],
    )
    output_dir = Path(output_dir or config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "data.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str))
    (output_dir / "metrics.json").write_text(
        json.dumps(build_metrics(data), indent=2, ensure_ascii=False, default=str))
    (output_dir / config["report_name"]).write_text(generate_report(data))
    return data, fetch_failures


def print_summary(data, config, output_dir, fetch_failures):
    t = data["totals"]
    m = data["meta"]
    codex = data.get("codex") or {}
    for label, stderr in fetch_failures:
        detail = stderr[-1] if stderr else "no detail"
        print(f"WARNING fetch failed in {label}: {detail}")
    if fetch_failures:
        print("  -> the report uses the refs the clone already had; it may be stale")
    print(f"project: {config['project']}  person: {m['person']} "
          f"({', '.join(m['emails'])}, from {data['attribution']['source']})")
    period = m.get("period")
    if period:
        mtd = " (month to date)" if period["month_to_date"] else ""
        print(f"period: {period['label']}{mtd}  {period['start']} → {period['end']}")
    else:
        print("period: full available history")
    print(f"commits found in range: {t['first_date'] or '—'} → {t['last_date'] or '—'}")
    print(f"commits: {t['commits']}  +{t['lines_added']} -{t['lines_removed']} "
          f"(net {t['net_lines']:+})  active days: {t['active_days']}")
    for repo, stats in sorted(t["repos"].items()):
        print(f"  {repo}: {stats['commits']} commits")
    if codex.get("available"):
        print(f"codex: {codex['tasks']} tasks  {codex['turns']} turns  "
              f"{codex['runtime_seconds'] // 60} min recorded runtime  "
              f"{codex['active_days']} active days")
    else:
        print(f"codex: unavailable — no readable session history under "
              f"{config['codex_sessions_dir']}")
    print(f"codex-attributed commits: {data['codex_evidence'].get('attributed', 0)}")
    if data["attribution"]["ambiguous"]:
        print("ATTENTION unconfirmed identities (excluded from every total): "
              + ", ".join(f"{r['email']} ({r['commits']})"
                          for r in data["attribution"]["ambiguous"]))
    print(f"report:  {Path(output_dir) / config['report_name']}")
    print(f"metrics: {Path(output_dir) / 'metrics.json'}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run a personal git + Codex audit from an audit.config.json.")
    parser.add_argument("--config", default=DEFAULT_CONFIG_NAME,
                        help=f"path to the config (default: ./{DEFAULT_CONFIG_NAME})")
    parser.add_argument("--month", default=None,
                        help="limit the report to one calendar month, YYYY-MM "
                             "(default: the full available history)")
    parser.add_argument("--output-dir", default=None,
                        help="where to write the HTML + JSON (default: from config)")
    parser.add_argument("--no-fetch", action="store_true",
                        help="skip `git fetch --all --prune`; read the clones as they are")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    output_dir = args.output_dir or config["output_dir"]
    try:
        data, fetch_failures = run(config, output_dir, fetch=not args.no_fetch,
                                   month=args.month)
    except (PeriodError, IdentityError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print_summary(data, config, output_dir, fetch_failures)
    return 0


if __name__ == "__main__":
    sys.exit(main())
