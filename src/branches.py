"""Inventory a repo's branches and how far each one has diverged.

One `rev-list --count` per ref would be one subprocess per ref, and most remote
refs share a tip with their local counterpart, so counts are computed once per
distinct tip SHA and fanned back out. See design decision D5.
"""
import subprocess

FIELD_SEP = "\x1f"
LOCAL_PREFIX = "refs/heads/"
REMOTE_PREFIX = "refs/remotes/"


def parse_branch_lines(lines, repo):
    rows = []
    for line in lines:
        if not line.strip():
            continue
        parts = line.split(FIELD_SEP, 4)
        if len(parts) != 5:
            continue
        ref, tip_sha, tip_date, tip_email, tip_subject = parts
        if ref.startswith(LOCAL_PREFIX):
            name, is_remote = ref[len(LOCAL_PREFIX):], False
        elif ref.startswith(REMOTE_PREFIX):
            name, is_remote = ref[len(REMOTE_PREFIX):], True
        else:
            continue
        if name.endswith("/HEAD"):
            continue          # symbolic ref, not a real branch
        rows.append({
            "repo": repo, "name": name, "is_remote": is_remote, "commits": 0,
            "tip_sha": tip_sha, "tip_date": tip_date, "tip_subject": tip_subject,
            # The tip's author email, so a personal report can show the branches
            # this developer last pushed to rather than every branch in the repo.
            # It attributes the TIP only: a branch whose last commit is someone
            # else's drops off the list even if most of it is this developer's.
            "tip_email": tip_email.strip("<>").strip().lower(),
        })
    return rows


def mine(rows, emails):
    """Branches whose tip commit was authored by one of these emails."""
    wanted = {e.strip().lower() for e in emails}
    return [r for r in rows if r.get("tip_email") in wanted]


def count_by_tip(rows, count_fn):
    """Call count_fn once per distinct tip SHA; write the result onto every ref."""
    cache = {}
    for row in rows:
        sha = row["tip_sha"]
        if sha not in cache:
            cache[sha] = count_fn(sha)
        row["commits"] = cache[sha]
    return rows


def collect_branches(repo_path, repo):
    fmt = (f"%(refname){FIELD_SEP}%(objectname){FIELD_SEP}"
           f"%(committerdate:short){FIELD_SEP}%(authoremail){FIELD_SEP}"
           f"%(contents:subject)")
    output = subprocess.run(
        ["git", "-C", str(repo_path), "for-each-ref", f"--format={fmt}",
         "refs/heads", "refs/remotes"],
        capture_output=True, text=True, check=True,
    ).stdout
    rows = parse_branch_lines(output.splitlines(), repo)

    def count(sha):
        # The SHA comes from this repo's own for-each-ref output, never from user
        # input, so no `--` separator is needed.
        out = subprocess.run(
            ["git", "-C", str(repo_path), "rev-list", "--count", "--no-merges", sha],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return int(out or 0)

    count_by_tip(rows, count)
    return sorted(rows, key=lambda r: (-r["commits"], r["name"]))
