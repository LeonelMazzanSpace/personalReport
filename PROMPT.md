# The prompt

This is what you paste into Codex to generate your monthly report.

## How to use it

1. Open Codex **in the folder of the project you want to report on** (the one
   holding the clones, not this repo).
2. Copy the block below.
3. Replace the four placeholders:
   - `[ENGINE_PATH]` → the absolute path of **this** repo
   - `[PROJECT]` → the project name, as you want it on the report
   - `[YYYY-MM]` → the month to report
   - `[TIMEZONE]` → your timezone, if it is not `America/Montevideo`

This repo's path on this machine:

```
/run/media/leonel/4f37aba0-a422-4ae0-b330-35fcb650f362/trabajo/proyectos/auditProcessPersonal
```

---

## The prompt (copy from here)

```text
Generate a client-ready monthly report of my development work on [PROJECT].

Reporting month: [YYYY-MM]
Reporting timezone: [TIMEZONE]
Report language: English

Use the audit engine at [ENGINE_PATH]. Read its AUDIT.md and follow that process
end to end — it is the authority on how this report is produced. Read its
README.md for the config reference. Do not reimplement the analysis in an ad-hoc
script, and do not modify the engine unless something in it is actually broken;
if it is, fix it there with a test and run its suite, never in a per-project copy.

Perform read-only analysis. Do not modify application code, switch branches,
create commits, push changes, or send the report to anyone. The engine's one
write is `git fetch --all --prune` on the audited clones, which updates
refs/remotes only; that is expected and must not be disabled unless I am offline.

Use the entire calendar month. If the month is still in progress, the engine
stops at the collection cutoff and labels the report "Month to date" — keep that
label.

Before running anything, do the measuring in AUDIT.md step 2. In particular:

- Step 2a, identity, is not optional. Enumerate every author identity in the
  history and find all of mine — the laptop address, a second company domain, a
  users.noreply address, a hostname-based one. Put all of them in `me.emails`.
  If any identity is ambiguous, ASK me before deciding. Do not add one on a hunch
  and do not silently drop one.
- Step 2c, the hotspot buckets, is measured against the repos, not guessed.
- Step 2e: check whether local Codex history exists and where. If it does not,
  that is not an error — the Codex metrics will read "Unavailable" and the report
  will say so.

Scope:
- Include only [PROJECT]-related repositories. Ask before leaving one out.
- Only my commits. Other authors and bots are excluded by the engine.
- Exclude work on this report itself.
- A Codex session opened in the project directory is not automatically about
  [PROJECT]; the engine attributes sessions by recorded working directory, and
  the coverage figures disclose what it could not attribute.
- Do not compare against previous reports.

Then validate, per AUDIT.md step 5, before you tell me anything:
- The engine's own test suite passes, if you touched the engine.
- No unconfirmed identities remain in the summary output.
- The commit count and the active-day count match plain `git log` for the same
  month and the same author identities. Show me both numbers.
- The Codex coverage figures in metrics.json are credible: if `files_parsed` is
  far above `sessions_matched`, the working-directory matching is wrong — say so
  rather than reporting the low number as fact.

Deliverables — the engine writes all three into <project>/audit/output/:
- report[PROJECT].html — the report, self-contained
- data.json — the full dataset
- metrics.json — aggregates, definitions and collection cutoff

Give me the path to the HTML at the end.

Honesty constraints, which the engine already enforces and you must not
undermine in your summary:
- A metric with no evidence behind it is "Unavailable", never 0.
- Committed line changes are not unique lines written.
- Recorded Codex runtime is assistant execution time including tool runs and
  waiting. It is not my working hours, and no time saved may be inferred from it.
- Human working hours are not reliably measurable from these records.
- A commit is "Codex-assisted" only with explicit attribution in its message.
  Having been authored while a session was running is circumstantial and must
  stay labelled as such.
- Do not claim work was merged or deployed without evidence.
- Keep personal information, credentials, raw conversations, local filesystem
  paths and internal session identifiers out of the report body.

Finally, summarise for me in plain language: the exact period covered, commits,
lines added/removed/net, active days, Codex activity (or why it is unavailable),
the main features, fixes, reviews and investigations the month covered, anything
in the data that stands out, and any repository or identity you left out and why.
```

---

## What to expect

The report opens with the executive summary and **every caveat before the first
number**: whether the month is still running, whether any identity is
unconfirmed, and what share of the history is duplicate content.

If the Codex metrics read "Unavailable", the report names the directory it looked
in. It is almost always one of two things: Codex keeps its history somewhere else
(fix with `codex.sessions_dir`), or the sessions ran in a working directory
outside the audited repos (fix with `codex.project_paths`).

## Running it directly, without Codex

If `audit.config.json` is already written:

```bash
cd <project>/audit
python3 /path/to/auditProcessPersonal/audit.py --month 2026-09
```
