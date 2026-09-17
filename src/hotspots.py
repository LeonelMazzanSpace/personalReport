"""Identify code hotspots: most-churned files, directory ownership, language mix.

Directory keys are repo-scoped and depth-aware, because one segment is the wrong
depth for most repos: in a monorepo it collapses everything to a handful of
workspace names, and in a single-package repo it collapses everything to `src`.
Neither says anything about who works where.

So two config knobs, both per-project and both calibrated by measuring the repos
(`AUDIT.md` step 3 has the exact commands):

- `deep_roots` — top-level directories that are too coarse alone and keep a
  SECOND segment: the workspace names in a monorepo, or just `src` in a
  single-package repo.
- `nested_segments` — segments inside a deep root that are STILL too coarse and
  keep a THIRD: typically `src` under a workspace, or `modules` under `src`.

Both default to empty, which means one segment per directory — correct for a flat
repo and harmless anywhere else, just coarse. See design decision D6.
"""
from collections import defaultdict

DEEP_ROOTS = frozenset()
NESTED_SEGMENTS = frozenset()
NO_EXTENSION_LABEL = "(no extension)"
ROOT_LABEL = "(root)"


def dir_key(repo, path, deep_roots=DEEP_ROOTS, nested_segments=NESTED_SEGMENTS):
    """Repo-scoped directory bucket for a path. See the module docstring."""
    parts = path.split("/")
    if len(parts) == 1:
        return f"{repo}/{ROOT_LABEL}"
    if parts[0] not in deep_roots:
        return f"{repo}/{parts[0]}"
    if len(parts) == 2:
        return f"{repo}/{parts[0]}"
    if parts[1] in nested_segments and len(parts) > 3:
        return f"{repo}/{parts[0]}/{parts[1]}/{parts[2]}"
    return f"{repo}/{parts[0]}/{parts[1]}"


def _extension(path):
    name = path.rsplit("/", 1)[-1]
    if "." not in name:
        return NO_EXTENSION_LABEL
    return "." + name.rsplit(".", 1)[-1]


def build_hotspots(enriched, top_files=25, top_dirs=20, deep_roots=DEEP_ROOTS,
                   nested_segments=NESTED_SEGMENTS):
    files = defaultdict(lambda: {"commits": 0, "added": 0, "removed": 0})
    dirs = defaultdict(lambda: {"files": 0, "commits": 0, "added": 0, "removed": 0})
    exts = defaultdict(lambda: {"files": 0, "commits": 0, "added": 0, "removed": 0})

    for c in enriched:
        dirs_seen = set()
        exts_seen = set()
        for added, removed, path in c["files"]:
            key = dir_key(c["repo"], path, deep_roots, nested_segments)
            ext_key = _extension(path)

            f = files[(c["repo"], path)]
            f["commits"] += 1          # numstat lists a path at most once per commit
            f["added"] += added
            f["removed"] += removed

            d = dirs[key]
            d["files"] += 1
            d["added"] += added
            d["removed"] += removed
            dirs_seen.add(key)

            e = exts[ext_key]
            e["files"] += 1
            e["added"] += added
            e["removed"] += removed
            exts_seen.add(ext_key)

        # Per-commit counters are incremented once per DISTINCT dir/extension, so a
        # commit sweeping 20 files under frontend/src/common counts as one commit
        # here, not twenty.
        for key in dirs_seen:
            dirs[key]["commits"] += 1
        for ext_key in exts_seen:
            exts[ext_key]["commits"] += 1

    file_rows = sorted(
        ({"repo": repo, "path": path, "commits": v["commits"], "added": v["added"],
          "removed": v["removed"]}
         for (repo, path), v in files.items()),
        key=lambda r: (-r["commits"], r["repo"], r["path"]),
    )[:top_files]

    dir_rows = sorted(
        ({"dir": d, "files": v["files"], "commits": v["commits"], "added": v["added"],
          "removed": v["removed"]}
         for d, v in dirs.items()),
        key=lambda r: (-r["files"], r["dir"]),
    )[:top_dirs]

    ext_rows = sorted(
        ({"ext": e, "files": v["files"], "commits": v["commits"], "added": v["added"],
          "removed": v["removed"], "lines": v["added"] + v["removed"]}
         for e, v in exts.items()),
        key=lambda r: (-r["lines"], r["ext"]),
    )

    return {
        "files": file_rows,
        "dirs": dir_rows,
        "extensions": ext_rows,
        "total_files_touched": len(files),
    }
