# auditProcessPersonal

A **personal** contribution audit engine: it reads a set of local clones plus the
local Codex history, and produces a self-contained, client-ready HTML report in
English, alongside the full dataset and a reproducible metrics file.

It measures **your work only**. The identity comes from `audit.config.json`, or —
when that is absent — from the `user.email` the audited clones have configured.

The engine knows nothing about any particular project: the repos, the name, the
identity and the directory-bucketing knobs all come from an `audit.config.json`
that lives next to the project being audited. A new project is ~20 lines of
config and zero lines of code.

- **To run an audit** (including how to calibrate the config): [`AUDIT.md`](./AUDIT.md)
- **The prompt you run with Codex:** [`PROMPT.md`](./PROMPT.md)
- **Config reference:** below

Requires Python 3.9+ (stdlib only) and `git`. There is nothing to install.

---

## Usage

```bash
cd <project>/audit
python3 /path/to/auditProcessPersonal/audit.py                 # full history
python3 /path/to/auditProcessPersonal/audit.py --month 2026-09 # one calendar month
```

| Flag | Default | What it does |
|---|---|---|
| `--config PATH` | `./audit.config.json` | Which config to use |
| `--month YYYY-MM` | full history | Clips **every** figure to one calendar month |
| `--output-dir PATH` | `output/` next to the config | Where to write |
| `--no-fetch` | (fetch enabled) | Skip `git fetch`; read the clones as they are |

`git fetch --all --prune` runs on each repo by default, because the audit reads
`--all` and the remote refs carry most of the history. It touches `refs/remotes`
only: never the working tree, the index, or any local branch. If a fetch fails
the run reports it and continues with whatever refs the clone already had.

Apart from the fetch, the audited repos are **read-only**: `git log`,
`git for-each-ref`, `git rev-list`, `git config --get`. The Codex history is read
and nothing more: only counts, durations and coverage figures reach the report —
never prompt text, task identifiers, or filesystem paths.

A month that has not finished yet is clipped at the collection cutoff and the
report labels itself **"Month to date."**

---

## Outputs

In `<project>/audit/output/`:

- `report<Project>.html` — the report, self-contained, open it in a browser
- `data.json` — the full dataset (everything the HTML shows, and more)
- `metrics.json` — aggregates, definitions and collection cutoff, for reproducibility

Report sections: executive summary, daily activity, activity calendar, monthly
breakdown, repositories, type of work, line changes by file type, Codex activity,
working rhythm, code hotspots, branches, and methodology.

---

## Layout

```
auditProcessPersonal/         # the engine (this)
├── AUDIT.md                  # the end-to-end process
├── PROMPT.md                 # the prompt for Codex
├── README.md
├── audit.py                  # CLI + pipeline orchestration
├── audit.config.example.json
├── src/                      # the pipeline modules
└── tests/                    # 420 tests, stdlib unittest

<project>/audit/              # one instance
├── audit.config.json         # the only per-project file that is written
└── output/                   # generated
    ├── report<Project>.html
    ├── data.json
    └── metrics.json
```

Run the suite:

```bash
python3 -m unittest discover -s tests -t . -q
```

---

## Config reference

See [`audit.config.example.json`](./audit.config.example.json).

| Field | Req. | Default | What it is |
|---|---|---|---|
| `project` | yes | — | The name shown on the report |
| `repos` | yes | — | List of `{path, label}`; `path` is relative to the config |
| `repos[].label` | no | directory name | How the repo appears in the report |
| `me.emails` | no | `git config user.email` | The emails whose commits are yours |
| `me.name` | no | `git config user.name` | Your name, as it appears on the report |
| `timezone` | no | `America/Montevideo` | Timezone for all day boundaries |
| `report_name` | no | `report<Project>.html` | Name of the HTML file |
| `output_dir` | no | `output` | Relative to the config |
| `hotspots.deep_roots` | no | `[]` | Top-level directories that keep a 2nd segment |
| `hotspots.nested_segments` | no | `[]` | Segments inside a deep root that keep a 3rd |
| `exclude_paths` | no | `[]` | Extra exclusion regexes, **appended** to the defaults |
| `codex.sessions_dir` | no | `~/.codex/sessions` | Where the Codex history lives |
| `codex.project_paths` | no | the audited repos | Which working directories count as "this project" |
| `codex.commit_evidence` | no | engine defaults | Regexes that mark a commit as assisted |
| `duplicate_scan` | no | `true` | Run the duplicate-content scan (`git patch-id`) |

`load_config` fails early and in detail: missing config, invalid JSON, missing
`project`, empty `repos`, a path that is not a git repo, duplicate labels, an
invalid regex.

### `me`

The question this report answers is **"is this mine?"**, and it has to answer it
without losing work: the same developer commits from a laptop address, from a
`users.noreply` address via a web UI, and occasionally from a personal one.

- If `me.emails` is set, it wins: listing one address is a deliberate choice to
  count one address.
- If it is absent, each audited repo's `user.email` is used (`git config --get`
  already falls back to the global file), and the report says where it came from.
- The engine also **detects** history emails whose git author name matches yours
  but which are not on the list, and reports them as *"attribution needs
  confirmation."* It **never adds them on its own** — guessing an identity is how
  a report ends up claiming someone else's commits. If they are yours, add them
  to `me.emails` and re-run.

### `codex`

A **task** is one Codex session (one rollout file). A **turn** is one instruction
from you plus the assistant work that follows it. **Recorded runtime** is the
union of the turn intervals — it includes tool execution and waiting, and it is
**not** hours worked.

If no history can be read, those metrics read **"Unavailable"**, never `0`: a
zero would assert that no assistant work happened, and this data cannot support
that claim.

### `hotspots`

The two knobs that set the depth at which directories are grouped. They are
**measured** against the repos (`AUDIT.md` step 2c), not guessed. With both
empty, each directory groups at one segment — correct for a flat repo and merely
coarse everywhere else.

---

## Design decisions

The ones that change how the numbers read:

- **An ambiguous identity is reported, never assumed.** An unlisted email whose
  git author name matches yours is left **out** of every total and listed on the
  report for you to confirm.
- **No evidence means "Unavailable", not `0`.** This applies to tasks, turns,
  runtime, Codex-active days and commit concurrency. In `metrics.json` those
  fields are `null`.
- **Assistance evidence comes in two strengths, never added together.**
  *Attributed* is an explicit trailer in the commit message — direct evidence.
  *Concurrent* is having committed during a recorded session — circumstantial,
  and the report says so.
- **Committed line changes, not lines written.** A line edited in three commits
  counts three times; a moved file counts as both a deletion and an addition.
- **Excluded files are shown, not omitted.** Lockfiles, vendored trees and build
  output stay out of the totals and appear in their own table, so the reader can
  see what the headline number leaves out.
- **`--all` deliberately pulls in content duplicates.** Rebases, cherry-picks on
  stale refs and PR squashes are distinct SHAs with identical diffs: SHA-level
  deduplication cannot see them, and the report discloses the percentage.
- **Runtime is measured over merged intervals.** Two sessions running side by
  side are one stretch of runtime, not two; idle time between turns never counts.
- **Days are cut at local midnight** in the configured timezone, not UTC
  midnight: a turn from 23:40 to 00:20 contributes to two days.
- **A task counts once in the period total** however many days it spans; the
  daily table counts it on each day it was active, so that column sums to more
  than the total. The report states this.
- Times are rendered in **each commit's own recorded offset** (`--date=format:`,
  not `format-local:`), so the hour and day-of-week axes are the author's local
  wall-clock time, not that of the machine running the audit.
