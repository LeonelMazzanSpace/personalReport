# Personal audit process — execution instructions

> This is the file to follow when the request is
> **"run my personal audit here, based on `auditProcessPersonal`"**.
>
> The engine (`audit.py` + `src/`) knows nothing about any particular project.
> Everything project-specific lives in an `audit.config.json` next to the audited
> project. This document is how that config gets written, and how the result gets
> validated.

## What it produces

In `<project>/audit/output/`:

- `report<Project>.html` — the report, self-contained, open it in a browser
- `data.json` — the full dataset (everything the HTML shows, and more)
- `metrics.json` — aggregates, definitions and collection cutoff, for reproducibility

Your work only. Commits by other people and by bots are outside every figure.

---

## Step 0 — Locate the repos

Repos are audited **as local clones**. List what is there:

```bash
cd <project-folder>
for d in */; do
  [ -d "$d/.git" ] && echo "$d -> $(git -C "$d" remote get-url origin 2>/dev/null)"
done
```

If a project repo is missing, **ask** before continuing: a report that omits a
repo reads as if that work never happened. Do not clone anything on your own
initiative.

---

## Step 1 — Create the audit directory

```bash
mkdir -p <project-folder>/audit
```

That directory holds **only** `audit.config.json` (plus `output/`, which is
generated). The code is not copied: `auditProcessPersonal` is referenced. If an
`audit/` from a previous run already exists, reuse it and update the config —
do not duplicate it.

---

## Step 2 — Measure before configuring

The three things the config defines (identity, directory buckets, exclusions) are
**measured against the repos, not guessed**.

Define the repo list once:

```bash
cd <project-folder>
REPOS="repo1 repo2 repo3"
```

### 2a. Identity — **the step that cannot be skipped**

First, which address each clone has configured. That is what the engine uses when
there is no `me.emails` in the config:

```bash
for d in $REPOS; do echo "$d: $(git -C "$d" config --get user.email)"; done
```

Then every author in the history, to find **your other addresses**:

```bash
for d in $REPOS; do git -C "$d" log --all --no-merges --format='%ae|%an'; done \
  | sort | uniq -c | sort -rn
```

Look in that output for any line carrying your name with a different address: the
laptop one, a second company domain, a `users.noreply`, a hostname-based one
(`you@192.168.1.10`). This is the norm, not the exception.

- If they are yours, **all of them** go in `me.emails`.
- If you are unsure about one, **ask** — do not add it just in case.

The engine makes its own pass and lists, on the report, every address whose git
author name matches yours but which is not in `me.emails`, under *"attribution
needs confirmation."* **It does not count them.** Close the loop: add the ones
that are yours and re-run, until that note is gone.

### 2b. Volume (sanity check)

```bash
for d in $REPOS; do
  echo "$d: $(git -C "$d" log --all --no-merges --author=<your-email> --format='%H' | sort -u | wc -l) commits of mine"
done
```

That number must match what the audit prints (step 5).

### 2c. Directory buckets (`hotspots`)

One path segment is the wrong depth for almost every repo. Measure where the
signal is.

```bash
# first segment
for d in $REPOS; do
  echo "=== $d"
  git -C "$d" log --all --no-merges --numstat --format='' \
    | awk 'NF==3{print $3}' \
    | awk -F/ '{if (NF==1) print "(root)"; else print $1}' \
    | sort | uniq -c | sort -rn | head -12
done
```

If one directory takes most of the file touches, it goes in `deep_roots` and the
measurement repeats one level down:

```bash
# second segment inside the dominant root (replace src/ with whatever came out)
for d in $REPOS; do
  echo "=== $d"
  git -C "$d" log --all --no-merges --numstat --format='' \
    | awk 'NF==3{print $3}' | grep '^src/' \
    | awk -F/ '{if (NF==2) print "src/(files)"; else print "src/"$2}' \
    | sort | uniq -c | sort -rn | head -14
done
```

If one dominates there too, it goes in `nested_segments` (a third level opens).

The two shapes that come up in practice:

| Repo shape | `deep_roots` | `nested_segments` | Resulting bucket |
|---|---|---|---|
| Single package (Nest / Vite / Expo) | `["src"]` | `["modules"]` | `api/src/modules/subscription` |
| yarn/pnpm monorepo | `["frontend","backend","shared"]` | `["src"]` | `mono/frontend/src/modules` |
| Flat repo | `[]` | `[]` | `repo/scripts` |

**The rule:** go one level deeper while a single bucket concentrates most of the
churn. Stop when the top buckets look like the product's own domains or modules.

### 2d. Exclusions (`exclude_paths`) — optional

Already excluded by default: lockfiles, `node_modules/`, `dist/`, `build/`,
`coverage/`, `.yarn/`, `assets/`, `public/`, `*.min.js` and `*.map`. Those lines
are counted in the `raw_*` totals and shown in their own table, but not in
`lines_added` / `lines_removed`.

Look for the project's own vendored trees:

```bash
for d in $REPOS; do
  git -C "$d" log --all --no-merges --numstat --format='' \
    | awk 'NF==3{a[$3]+=$1} END{for (p in a) print a[p], p}' \
    | sort -rn | head -20
done
```

If a third-party library committed into the repo shows up (e.g.
`charting_library/`, +76k lines), add its regex to `exclude_paths`. It is
**appended** to the defaults, not a replacement.

### 2e. Codex history

```bash
ls -d ~/.codex/sessions 2>/dev/null && find ~/.codex/sessions -name '*.jsonl' | wc -l
```

- If it exists, nothing needs configuring: the default is `~/.codex/sessions`, and
  sessions are attributed to the project by the working directory they record,
  compared against the audited repos.
- If Codex keeps its history elsewhere, point at it with `codex.sessions_dir`.
- If it does not exist, **that is not an error**: the Codex metrics read
  "Unavailable" and the report names the directory it looked in.

---

## Step 3 — Write the config

`<project-folder>/audit/audit.config.json`. Copy
`auditProcessPersonal/audit.config.example.json` and fill it with what you
measured. `README.md` has the field-by-field reference.

`repos[].path` values resolve against **the config file itself**, so from
`<project>/audit/` they are `../<repo>`.

---

## Step 4 — Run

```bash
cd <project-folder>/audit

# the month being reported
python3 /path/to/auditProcessPersonal/audit.py --month 2026-09

# or the full history
python3 /path/to/auditProcessPersonal/audit.py
```

`git fetch --all --prune` on each repo is **included and on by default**: the
audit reads `--all`, and normally only the default branch is checked out, so the
remote refs carry most of the history. Stale refs mean a stale report.

- Offline, or to read the clones as they are: `--no-fetch`.
- If a fetch fails, it is reported and **the run continues** with the refs the
  clone already had. Carry that warning into the final summary — a stale report
  with no warning is worse than no report.

No `pip install` needed: Python 3.9+ stdlib and `git` only.

---

## Step 5 — Validate before reporting

None of this is optional.

1. **The engine's suite** — if `auditProcessPersonal/` was touched:
   ```bash
   cd /path/to/auditProcessPersonal && python3 -m unittest discover -s tests -t . -q
   ```

2. **No unconfirmed identities.** If the summary prints `ATTENTION unconfirmed
   identities`, go back to step 2a: either they are yours and belong in
   `me.emails`, or they are not and the reason is written down.

3. **The commit count matches git.** The summary prints it; check it against the
   step 2b command, over the same range:
   ```bash
   for d in $REPOS; do
     git -C "$d" log --all --no-merges --author=<your-email> \
       --since=2026-09-01 --until=2026-10-01 --format='%H' | sort -u | wc -l
   done
   ```

4. **The active-day count matches.**
   ```bash
   for d in $REPOS; do
     git -C "$d" log --all --no-merges --author=<your-email> \
       --date=format:%Y-%m-%d --format='%ad' | sort -u | wc -l
   done
   ```

5. **The Codex metrics are credible.** If the report says "Unavailable", confirm
   that the directory it names is really the one Codex uses. If it gives a number,
   look at `coverage` in `metrics.json`: how many files it found, parsed, and
   attributed to the project. A wide gap between `files_parsed` and
   `sessions_matched` means the working-directory matching is not hitting.

6. **The top buckets say something.** Look at `hotspots.dirs` in `data.json`. If
   the first one is `repo/src` holding half the churn, the step 2c calibration
   stopped too early.

---

## Step 6 — Summarise

In the final message, in plain language:

- Path to the generated report
- The exact period, and whether it is "month to date"
- Commits, lines +/−, active days, per-repo breakdown
- Codex activity, or why it is unavailable
- Any identities left unconfirmed
- Any fetch that failed, or repo left out and why

**What is not said:** that a commit was written by Codex without a trailer saying
so, that recorded runtime is hours worked, or that time was saved. The report is
built not to assert any of the three.

---

## Extending the engine

If a project needs something the engine does not do, the change goes in
`auditProcessPersonal/` with a test, **not** in a per-project copy. That rule is
the reason this directory exists: every copy diverged, and the same fix had to be
re-applied in each one.

- Modules in `src/`, one per responsibility; the pipeline is orchestrated in `audit.py`
- Anything project-specific is config, never a literal in the code
- Test first, and run the whole suite before calling it done
