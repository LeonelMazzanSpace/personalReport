"""Detect content-duplicate commits via `git patch-id`, not a numstat fingerprint.

Rebase and cherry-pick copies surviving on stale `refs/remotes`, plus Azure DevOps
"Merged PR N:" squashes that duplicate their own feature-branch commits, are
distinct SHAs with a single parent — `--no-merges` cannot catch them, and neither
can a fingerprint built from `(path, added, removed)` numstat tuples: that
overstates duplication because it cannot tell "changed one env var value" from a
true duplicate (measured 28.9% overall vs. patch-id's 23.5%, and 23.8% for
Infrastructure against patch-id's real 0.8%). `git patch-id --stable` hashes the
actual diff content, ignoring line numbers and context, so it is authoritative.
See finding C1.

This module and extract_commits.py/branches.py are the only ones that shell out
to git; everything downstream works on plain dicts so it can be tested without a
repository. Read-only: `git log` and `git patch-id` only, both reads.
"""
import subprocess
from collections import Counter


def parse_patch_ids(output):
    """Parse `git patch-id --stable` output into {commit_sha: patch_id}.

    Each line is `<patch-id> <commit-sha>`. A commit with an empty diff (no
    content change) emits no line at all, so it is simply absent from the
    result — see duplicate_stats' `no_patch` handling.
    """
    result = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        patch_id, sha = parts
        result[sha] = patch_id
    return result


def duplicate_stats(patch_ids_by_sha):
    """Summarise a {sha: patch_id} mapping.

    `redundant` counts every commit beyond the first in each group of commits
    that share a patch-id — i.e. the copies, not the originals. `groups` counts
    how many distinct patch-ids have more than one commit (the number of
    duplicate clusters, not the number of duplicate commits). `unique` is the
    number of distinct patch-ids seen, duplicated or not.

    This function cannot know about commits that never got a patch-id at all
    (empty diffs) — they are absent from `patch_ids_by_sha` by construction, not
    present with a null value. `collect_duplicates` fills in `no_patch` itself,
    from the total commit count it already has to shell out for anyway.
    """
    counts = Counter(patch_ids_by_sha.values())
    redundant = sum(c - 1 for c in counts.values() if c > 1)
    groups = sum(1 for c in counts.values() if c > 1)
    return {"redundant": redundant, "groups": groups, "unique": len(counts)}


def collect_duplicates(repo_path, repo):
    """Run the patch-id pass over one repo's full history and summarise it.

    Two git processes, piped: `git log -p` streams every non-merge commit's diff
    across ALL refs (deliberately including the stale `refs/remotes` the
    developer's local-only clone carries — same scope as extract_commits.py),
    and `git patch-id --stable` reads that stream and prints one line per commit
    that has an actual diff. `git patch-id` needs no `-C`: it never touches the
    repository, only its own stdin.

    The commit header format is `commit %H` — lowercase, matching git log's own
    default header exactly. `git patch-id` recognises a commit boundary and
    captures its SHA only from a line starting with the literal lowercase
    string "commit "; an uppercase or otherwise reworded header (the original
    dispatch note for this fix suggested "COMMIT %H") is not recognised, and
    every commit comes back with the SHA `000...0` instead of its real hash.
    Verified by diffing output against a plain unformatted `git log -p`, which
    is byte-identical.

    A separate, cheap `rev-list --count` gets the true total commit count, so
    `no_patch` (commits with no patch-id at all — empty diffs, not duplicates)
    can be computed without re-deriving it from parse_patch_ids' output, which
    by definition never contains those commits.
    """
    total = int(subprocess.run(
        ["git", "-C", str(repo_path), "rev-list", "--count", "--all", "--no-merges"],
        capture_output=True, text=True, check=True,
    ).stdout.strip() or 0)

    log_proc = subprocess.Popen(
        ["git", "-C", str(repo_path), "log", "--all", "--no-merges", "-p",
         "--format=commit %H"],
        stdout=subprocess.PIPE,
    )
    patch_id_output = subprocess.run(
        ["git", "patch-id", "--stable"],
        stdin=log_proc.stdout, capture_output=True, text=True, check=True,
    ).stdout
    log_proc.stdout.close()
    log_proc.wait()

    patch_ids_by_sha = parse_patch_ids(patch_id_output)
    stats = duplicate_stats(patch_ids_by_sha)
    stats["no_patch"] = max(total - len(patch_ids_by_sha), 0)
    return {"repo": repo, "commits": total, **stats}
