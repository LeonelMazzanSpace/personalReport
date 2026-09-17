"""Resolve WHO the report is about, and keep only that person's commits.

The team audit resolved every email in the history to a person. A personal audit
only has to answer one question — "is this commit mine?" — but it has to answer it
without silently dropping work: the same developer commits from a work address on
the laptop, a `users.noreply` address from a web UI, and occasionally a personal
one. Missing one of those understates the month.

So identity resolution has two halves:

* `resolve_identity` establishes the emails to count. Config wins; otherwise the
  audited repos' own `git config user.email` does, which is what "take it from my
  logged-in account in that project" means in git terms.
* `ambiguous_identities` looks for what the config missed: emails in the history
  whose git author NAME matches the person, but whose address is not on the list.
  Those are reported, never auto-included — guessing an identity is how a report
  claims someone else's commits. See the prompt requirement "Ask if attribution is
  ambiguous".
"""
import subprocess


class IdentityError(Exception):
    """No email could be established for the person the report is about."""


def normalize(email):
    return (email or "").strip().lower()


def git_config_value(repo_path, key):
    """Read one git config key for a repo, or None. Never raises on a missing key."""
    result = subprocess.run(
        ["git", "-C", str(repo_path), "config", "--get", key],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def detect_from_repos(repos, read=git_config_value):
    """Collect `user.email` / `user.name` as each audited repo sees them.

    Per-repo `git config --get` already falls back to the global file, so one repo
    configured with a client address and another with the company one both show up
    — which is exactly the multi-identity case worth surfacing.
    """
    emails, names = [], []
    for repo in repos:
        email = read(repo["path"], "user.email")
        if email and normalize(email) not in {normalize(e) for e in emails}:
            emails.append(email.strip())
        name = read(repo["path"], "user.name")
        if name and name.strip() not in names:
            names.append(name.strip())
    return emails, names


def resolve_identity(me_config, repos, read=git_config_value):
    """Return {name, emails, source, detected_emails} for the person being audited.

    `emails` from the config are authoritative and stop the detection from adding
    anything: a config that lists one address is a deliberate choice to count one
    address. With no config, every address the repos' git config reports is used,
    and `source` says so — the report prints it, because "which identities did you
    count" is the first question anyone reading the numbers should be able to check.
    """
    me_config = me_config or {}
    configured = [e for e in (me_config.get("emails") or []) if normalize(e)]
    detected_emails, detected_names = detect_from_repos(repos, read)

    if configured:
        emails, source = configured, "config"
    elif detected_emails:
        emails, source = detected_emails, "git config"
    else:
        raise IdentityError(
            "cannot tell whose commits to count: no `me.emails` in the config and "
            "no `user.email` set in any audited repo. Add me.emails to the config."
        )

    name = me_config.get("name") or (detected_names[0] if detected_names else emails[0])
    return {
        "name": name,
        "emails": sorted({normalize(e) for e in emails}),
        "display_emails": emails,
        "source": source,
        "detected_emails": detected_emails,
    }


def is_mine(email, identity):
    return normalize(email) in set(identity["emails"])


def filter_mine(commits, identity):
    """Keep only this person's commits, deduplicated by (repo, full SHA).

    `git log --all` already yields each commit once per repo, so the dedup is a
    guard rather than a fix — but the prompt asks for SHA-level deduplication
    explicitly, and a config that ever lists the same repo under two labels would
    otherwise double every number in the report.
    """
    seen = set()
    mine = []
    for c in commits:
        if not is_mine(c.email, identity):
            continue
        key = (c.repo, c.hash)
        if key in seen:
            continue
        seen.add(key)
        mine.append(c)
    return mine


def ambiguous_identities(commits, identity):
    """Emails that look like this person but are not on the list.

    Matched on the git author NAME, case-insensitively, because that is the only
    signal available locally that links two addresses to one human. Returns rows of
    {email, name, commits} for the report's attribution note — a prompt to confirm,
    not a set to merge.
    """
    mine = set(identity["emails"])
    target = (identity["name"] or "").strip().lower()
    if not target:
        return []
    rows = {}
    for c in commits:
        key = normalize(c.email)
        if key in mine or (c.name or "").strip().lower() != target:
            continue
        row = rows.setdefault(key, {"email": key, "name": c.name, "commits": 0})
        row["commits"] += 1
    return sorted(rows.values(), key=lambda r: (-r["commits"], r["email"]))
