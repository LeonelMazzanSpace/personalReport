"""Render the personal audit data into one self-contained HTML report.

Layout and palette carried over from the team audit this engine grew out of. No
CDN, no external fonts, no build step: the only JavaScript is the calendar's
modal, and the only data is the JSON block that modal reads.

The report is written in English and for a client to read, which sets two rules
the renderers follow throughout:

* Every figure states what it actually measures. "Committed line changes", not
  "lines written". "Recorded Codex runtime", not "hours worked".
* A metric with no evidence behind it renders as "Unavailable", never as 0 — a
  zero is a claim, and an absent Codex history cannot support it.
"""
import html

from src.calendar_labels import month_name
from src.calendar_view import CALENDAR_CSS, CALENDAR_JS, CATEGORY_DOT_COLORS, render_calendar
from src.classify import CATEGORY_LABELS, CATEGORY_ORDER
from src.file_kinds import KIND_LABELS, KIND_ORDER
from src.format import fmt_duration, fmt_hours, fmt_int, fmt_signed, short_num

# 40 branch rows is a section; 800 is a wall. The rest are summarised in the hint.
BRANCH_ROWS_SHOWN = 40
# Above this many days, the daily table lists only days with activity: a
# full-history report would otherwise open with a thousand mostly-empty rows.
DAILY_FULL_TABLE_MAX_DAYS = 70
# Top files/directories are already capped upstream (src/hotspots.py).
HOTSPOT_FILE_ROWS = 20

UNAVAILABLE = '<span class="unavailable">Unavailable</span>'

RENDER_CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #F4F6F9; --surface: #FFFFFF; --border: #E0E6EF; --border-dark: #C5CFD9;
  --text: #1C2B3A; --text-sec: #526070; --text-muted: #8A9BB0;
  --blue: #1A56DB; --green: #0D9F6E; --red: #D43030; --amber: #B45309;
  --shadow-sm: 0 1px 3px rgba(0,0,0,.08), 0 1px 2px rgba(0,0,0,.05);
  --shadow-md: 0 4px 12px rgba(0,0,0,.08), 0 2px 4px rgba(0,0,0,.05);
  --shadow-lg: 0 12px 32px rgba(0,0,0,.16), 0 4px 8px rgba(0,0,0,.08);
  --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
}
body {
  background: var(--bg); color: var(--text);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 14px; line-height: 1.6; -webkit-font-smoothing: antialiased;
}
.page { max-width: 1240px; margin: 0 auto; padding: 0 24px 48px; }
.topbar { background: var(--text); color: #fff; padding: 0 24px; }
.topbar-inner {
  max-width: 1240px; margin: 0 auto; display: flex; align-items: center;
  justify-content: space-between; height: 52px;
}
.topbar-brand { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 15px; }
.topbar-brand-dot { width: 8px; height: 8px; border-radius: 50%; background: #4ADE80; }
.topbar-meta { font-family: var(--mono); font-size: 11px; color: rgba(255,255,255,.5); }
.report-header {
  background: var(--surface); border-bottom: 1px solid var(--border);
  padding: 32px 0; margin-bottom: 28px;
}
.report-header-inner {
  max-width: 1240px; margin: 0 auto; padding: 0 24px; display: flex;
  align-items: flex-end; justify-content: space-between; gap: 24px; flex-wrap: wrap;
}
.report-title { font-size: 26px; font-weight: 700; letter-spacing: -.3px; }
.report-subtitle { font-size: 13px; color: var(--text-sec); margin-top: 4px; }
.report-badges { display: flex; gap: 8px; flex-wrap: wrap; }
.badge {
  display: inline-flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 500;
  padding: 4px 10px; border-radius: 4px; border: 1px solid var(--border);
  color: var(--text-sec); background: var(--bg);
}
.badge-dot { width: 6px; height: 6px; border-radius: 50%; }
.kpi-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 28px; }
@media (max-width: 960px) { .kpi-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 600px) { .kpi-grid { grid-template-columns: 1fr; } }
.kpi-card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  padding: 20px; box-shadow: var(--shadow-sm);
}
.kpi-label {
  font-size: 11px; font-weight: 500; letter-spacing: .06em; text-transform: uppercase;
  color: var(--text-muted); margin-bottom: 8px;
}
.kpi-value { font-size: 26px; font-weight: 700; line-height: 1.1; font-variant-numeric: tabular-nums; }
.kpi-value.blue { color: var(--blue); } .kpi-value.green { color: var(--green); }
.kpi-value.red { color: var(--red); } .kpi-value.amber { color: var(--amber); }
.kpi-value.dark { color: var(--text); }
.kpi-sub { font-size: 11px; color: var(--text-muted); margin-top: 6px; }
.section { margin-bottom: 32px; }
.section-header {
  display: flex; align-items: baseline; justify-content: space-between;
  gap: 16px; margin-bottom: 12px; flex-wrap: wrap;
}
.section-title { font-size: 15px; font-weight: 700; display: flex; align-items: center; gap: 8px; }
.section-title::before {
  content: ''; display: inline-block; width: 3px; height: 16px;
  background: var(--blue); border-radius: 2px;
}
.section-hint { font-size: 12px; color: var(--text-muted); }
.card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; box-shadow: var(--shadow-sm); overflow: hidden;
}
table { width: 100%; border-collapse: collapse; }
th {
  text-align: left; font-size: 11px; font-weight: 600; text-transform: uppercase;
  letter-spacing: .05em; color: var(--text-muted); padding: 10px 14px;
  border-bottom: 1px solid var(--border); background: var(--bg); white-space: nowrap;
}
td { padding: 10px 14px; border-bottom: 1px solid var(--border); font-size: 13px; }
tbody tr:last-child td { border-bottom: none; }
tbody tr:hover { background: #F8FAFD; }
td.r, th.r { text-align: right; font-variant-numeric: tabular-nums; }
td.mono, .mono { font-family: var(--mono); font-size: 12px; }
.pos { color: var(--green); } .neg { color: var(--red); }
.avatar {
  width: 26px; height: 26px; border-radius: 50%; display: inline-flex;
  align-items: center; justify-content: center; font-size: 10px; font-weight: 700;
  flex-shrink: 0;
}
.dev-cell { display: flex; align-items: center; gap: 9px; }
.bar-track { height: 6px; background: var(--bg); border-radius: 3px; overflow: hidden; min-width: 70px; }
.bar-fill { height: 100%; border-radius: 3px; }
.stack { display: flex; height: 22px; border-radius: 4px; overflow: hidden; background: var(--bg); }
.stack-seg { height: 100%; }
.dev-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 16px; }
.dev-card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 18px; box-shadow: var(--shadow-sm); }
.dev-card-head { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
.dev-card-name { font-weight: 700; font-size: 15px; }
.dev-emails { font-family: var(--mono); font-size: 11px; color: var(--text-muted); word-break: break-all; margin-bottom: 14px; }
.dev-emails div { padding: 1px 0; }
.dev-stats { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 16px; }
.dev-stat-label { font-size: 10px; text-transform: uppercase; letter-spacing: .05em; color: var(--text-muted); }
.dev-stat-value { font-size: 15px; font-weight: 600; font-variant-numeric: tabular-nums; }
.charts-row { display: grid; grid-template-columns: 1fr 1.5fr; gap: 16px; }
@media (max-width: 860px) { .charts-row { grid-template-columns: 1fr; } }
.chart-title { font-size: 12px; font-weight: 600; color: var(--text-sec); margin-bottom: 14px; }
.vbars { display: flex; align-items: flex-end; gap: 4px; height: 140px; }
.vbar {
  flex: 1; min-width: 0; height: 100%;
  display: flex; flex-direction: column; justify-content: flex-end; align-items: center;
}
.vbar-fill { width: 100%; min-height: 2px; border-radius: 3px 3px 0 0; }
.vbar-label { font-size: 9px; color: var(--text-muted); margin-top: 5px; white-space: nowrap; }
.footer {
  max-width: 1240px; margin: 0 auto; padding: 20px 24px 40px;
  display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap;
  font-size: 11px; color: var(--text-muted); border-top: 1px solid var(--border);
}
.footer code { font-family: var(--mono); }
.note {
  background: #FEF3C7; border: 1px solid #FDE68A; color: #78350F;
  border-radius: 6px; padding: 10px 14px; font-size: 12px; margin-bottom: 16px;
}
.kind-badge {
  font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em;
  padding: 1px 5px; border-radius: 3px; border: 1px solid currentColor; margin-left: 6px;
}
.repo-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; margin-bottom: 16px; }
.repo-card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 18px; box-shadow: var(--shadow-sm); }
.repo-name { font-family: var(--mono); font-size: 13px; font-weight: 700; }
.repo-nums { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 14px; margin-top: 12px; }
.notes-row { display: grid; gap: 12px; margin-bottom: 20px; }
.note.info { background: #EBF0FC; border-color: #C7D8F8; color: #1E3A8A; }
.note.ai { background: #F5F3FF; border-color: #DDD6FE; color: #5B21B6; }
.note strong { font-weight: 700; }
.metric-table td:first-child { color: var(--text-sec); }
.metric-table td.v { font-weight: 700; font-variant-numeric: tabular-nums; text-align: right; }
.metric-table td.note-cell { font-size: 11px; color: var(--text-muted); }
.scroll-y { max-height: 560px; overflow-y: auto; }
.scroll-y thead th { position: sticky; top: 0; z-index: 1; }
tr.idle td { color: var(--text-muted); }
tr.total-row td { background: var(--bg); font-weight: 700; }
.pill {
  display: inline-block; font-size: 9px; font-weight: 700; letter-spacing: .04em;
  text-transform: uppercase; padding: 1px 5px; border-radius: 3px;
  border: 1px solid currentColor;
}
.pill.ai { color: #7C3AED; }
.unavailable { color: var(--text-muted); font-style: italic; font-weight: 500; }
.split-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 860px) { .split-row { grid-template-columns: 1fr; } }
"""


def esc(value):
    return html.escape(str(value))


def initials(name):
    parts = [p for p in str(name).split() if p]
    if len(parts) >= 2:
        return (parts[0][:1] + parts[-1][:1]).upper()
    return str(name)[:2].upper()


def period_label(meta):
    """The exact reporting period, spelled out. Full history says so explicitly."""
    period = meta.get("period")
    if not period:
        totals = meta.get("range") or {}
        first, last = totals.get("first"), totals.get("last")
        if not first:
            return "Full available history"
        return f"Full available history · {first} → {last}"
    suffix = " (month to date)" if period["month_to_date"] else ""
    return f"{period['label']}{suffix} · {period['start']} → {period['end']}"


def render_page_header(data):
    m = data["meta"]
    t = data["totals"]
    period = m.get("period")
    mtd = " · Month to date" if period and period["month_to_date"] else ""
    return f"""
<div class="topbar"><div class="topbar-inner">
  <div class="topbar-brand"><div class="topbar-brand-dot"></div>SpaceDev Engineering</div>
  <div class="topbar-meta">Personal development report · {esc(m['generated_at'])}</div>
</div></div>
<div class="report-header"><div class="report-header-inner">
  <div>
    <div class="report-title">{esc(m.get('project') or 'Project')} — monthly
      development report{esc(mtd)}</div>
    <div class="report-subtitle">
      {esc(m.get('person') or '—')} · {esc(period_label(m))} ·
      reporting timezone {esc(m.get('timezone') or 'UTC')}
    </div>
  </div>
  <div class="report-badges">
    <span class="badge"><span class="badge-dot" style="background:var(--blue)"></span>
      {fmt_int(t['commits'])} commits</span>
    <span class="badge">{fmt_signed(t['net_lines'])} net lines</span>
    <span class="badge">{fmt_int(t['active_days'])} active days</span>
    <span class="badge mono">{esc(m['scope'])}</span>
  </div>
</div></div>
"""


def render_notes(data):
    """Everything the reader must know BEFORE the first number, in reading order.

    Month-to-date first (it changes what every total means), then attribution
    ambiguity (it changes whose numbers these are), then the duplicate-content
    disclosure (it changes what a commit count counts).
    """
    m = data["meta"]
    out = []
    period = m.get("period")
    if period and period["month_to_date"]:
        out.append(
            f'<div class="note info"><strong>Month to date.</strong> '
            f'{esc(period["label"])} has not finished. Every figure covers '
            f'{esc(period["start"])} through {esc(period["end"])}, collected at '
            f'{esc(m.get("cutoff") or m["generated_at"])}, and is not comparable '
            f'to a full calendar month.</div>')

    ambiguous = (data.get("attribution") or {}).get("ambiguous") or []
    if ambiguous:
        listed = ", ".join(f'{esc(row["email"])} ({row["commits"]} commits)'
                           for row in ambiguous)
        out.append(
            f'<div class="note"><strong>Attribution needs confirmation.</strong> '
            f'These git identities carry the same author name but are not in the '
            f'configured identity list, so their commits are <em>excluded</em>: '
            f'{listed}. Add them to <code>me.emails</code> and re-run if they are '
            f'the same person.</div>')

    dup = (data.get("duplicates") or {}).get("total") or {}
    if dup.get("commits"):
        pct = round(dup["redundant"] / dup["commits"] * 100)
        out.append(
            f'<div class="note"><strong>Duplicate content in history.</strong> '
            f'This audit deliberately reads <code>--all</code>, including stale '
            f'<code>refs/remotes</code>, so no work reachable only from an old ref '
            f'is lost. Across the repositories, about {pct}% of non-merge commits '
            f'are content duplicates — rebase and cherry-pick copies surviving on '
            f'old refs, plus squash commits that duplicate their own feature '
            f'branch. Commits are deduplicated by full SHA, which cannot detect '
            f'those copies: they are distinct commits with identical diffs.</div>')

    if not out:
        return ""
    return '<div class="notes-row">' + "".join(out) + "</div>"


def _codex_value(codex, key, formatter=fmt_int):
    """A Codex figure, or the Unavailable marker when no history was read."""
    if not codex or not codex.get("available"):
        return UNAVAILABLE
    return formatter(codex.get(key) or 0)


def render_kpis(data):
    t = data["totals"]
    codex = data.get("codex") or {}
    dt = data.get("daily_totals") or {}
    cards = [
        ("Commits", "blue", fmt_int(t["commits"]),
         f"non-merge · authored by {esc(data['meta'].get('person') or '—')} · "
         f"{len(data['meta']['repos'])} repositories"),
        ("Lines added", "green", fmt_int(t["lines_added"]),
         f"committed line changes · raw incl. lockfiles {fmt_int(t['raw_added'])}"),
        ("Lines removed", "red", fmt_int(t["lines_removed"]),
         f"net {fmt_signed(t['net_lines'])} · raw incl. lockfiles "
         f"{fmt_int(t['raw_removed'])}"),
        ("Days with commits", "amber", fmt_int(dt.get("commit_days", t["active_days"])),
         f"{t['first_date'] or '—'} → {t['last_date'] or '—'}"),
        ("Codex tasks", "dark", _codex_value(codex, "tasks"),
         (f"{fmt_int(codex.get('turns') or 0)} turns · "
          f"{fmt_int(codex.get('active_days') or 0)} days with recorded activity")
         if codex.get("available") else "no local Codex history was readable"),
        ("Recorded Codex runtime", "dark",
         _codex_value(codex, "runtime_seconds", fmt_duration),
         "assistant execution time, incl. tool runs and waiting — not working hours"),
    ]
    out = ['<div class="kpi-grid">']
    for label, tone, value, sub in cards:
        out.append(
            f'<div class="kpi-card"><div class="kpi-label">{esc(label)}</div>'
            f'<div class="kpi-value {tone}">{value}</div>'
            f'<div class="kpi-sub">{sub}</div></div>'
        )
    out.append("</div>")
    return "".join(out)


def _metric_row(label, value, note=""):
    return (f'<tr><td>{esc(label)}</td><td class="v">{value}</td>'
            f'<td class="note-cell">{note}</td></tr>')


def render_summary(data):
    """The executive metrics table: every headline figure with its caveat attached."""
    t = data["totals"]
    dt = data.get("daily_totals") or {}
    codex = data.get("codex") or {}
    ev = data.get("codex_evidence") or {}
    available = bool(codex.get("available"))

    rows = [
        _metric_row("Reporting period", esc(period_label(data["meta"])),
                    "reporting timezone "
                    f"{esc(data['meta'].get('timezone') or 'UTC')}"),
        _metric_row("Commits (non-merge, mine)", fmt_int(t["commits"]),
                    "deduplicated by full SHA across all local and "
                    "remote-tracking refs"),
        _metric_row("Commits with Codex attribution", fmt_int(ev.get("attributed", 0)),
                    "explicit trailer or footer in the commit message"),
        _metric_row("Commits authored during a recorded Codex session",
                    fmt_int(ev.get("concurrent_only", 0)) if available else UNAVAILABLE,
                    "circumstantial only — the assistant was running, which is not "
                    "evidence that it wrote the commit"),
        _metric_row("Lines added", fmt_int(t["lines_added"]),
                    "committed line changes, not unique lines written"),
        _metric_row("Lines removed", fmt_int(t["lines_removed"]), ""),
        _metric_row("Net line change", fmt_signed(t["net_lines"]), ""),
        _metric_row("File changes", fmt_int(t["files_touched"]),
                    "one count per file per commit; binaries excluded"),
        _metric_row("Codex tasks", _codex_value(codex, "tasks"),
                    "counted once each, however many days they span"),
        _metric_row("Codex turns", _codex_value(codex, "turns"),
                    "instructions started inside the period"),
        _metric_row("Recorded Codex runtime",
                    _codex_value(codex, "runtime_seconds", fmt_duration),
                    (f"{fmt_hours(codex.get('runtime_seconds'))} h · merged "
                     "intervals, idle gaps between turns excluded")
                    if available else "no readable turn timestamps"),
        _metric_row("Human working hours", UNAVAILABLE,
                    "not reliably measurable from available records"),
        _metric_row("Days with commits", fmt_int(dt.get("commit_days",
                                                        t["active_days"]))),
        _metric_row("Days with recorded Codex activity",
                    _codex_value(codex, "active_days")),
        _metric_row("Days with either", fmt_int(dt.get("active_days",
                                                       t["active_days"]))),
    ]
    return ('<div class="section"><div class="section-header">'
            '<div class="section-title">Executive summary</div>'
            '<div class="section-hint">Each figure with the limit on how it can be '
            'read</div></div>'
            '<div class="card"><table class="metric-table"><thead><tr>'
            '<th>Metric</th><th class="r">Value</th><th>Basis</th>'
            '</tr></thead><tbody>' + "".join(rows) + "</tbody></table></div></div>")


def render_daily(data):
    """One row per day: git columns and Codex columns side by side.

    Over DAILY_FULL_TABLE_MAX_DAYS the idle rows are dropped rather than paginated,
    because the point of listing them is to show the shape of one month — over a
    year of history the shape lives in the calendar heatmap instead.
    """
    rows = data["daily"]
    totals = data.get("daily_totals") or {}
    codex_available = bool((data.get("codex") or {}).get("available"))
    if not rows:
        return ""

    listed = rows
    hint = f"{len(rows)} days, including days with no activity"
    if len(rows) > DAILY_FULL_TABLE_MAX_DAYS:
        listed = [r for r in rows if r["active"]]
        hint = (f"{len(listed)} days with activity, out of {len(rows)} in range — "
                "idle days omitted at this range length")

    out = ['<div class="section"><div class="section-header">',
           '<div class="section-title">Daily activity</div>',
           f'<div class="section-hint">{esc(hint)}</div></div>',
           '<div class="card scroll-y"><table><thead><tr>',
           '<th>Date</th><th class="r">Commits</th><th class="r">Lines +</th>',
           '<th class="r">Lines −</th><th class="r">Net</th>',
           '<th class="r">File changes</th><th class="r">Codex tasks</th>',
           '<th class="r">Turns</th><th class="r">Runtime</th>',
           '<th>Repositories</th></tr></thead><tbody>']
    for row in listed:
        idle = "" if row["active"] else ' class="idle"'
        codex_cells = (
            f'<td class="r">{row["tasks"] or "·"}</td>'
            f'<td class="r">{row["turns"] or "·"}</td>'
            f'<td class="r">{fmt_duration(row["runtime_seconds"]) if row["runtime_seconds"] else "·"}</td>'
            if codex_available else '<td class="r">—</td><td class="r">—</td>'
                                    '<td class="r">—</td>')
        out.append(
            f'<tr{idle}><td class="mono">{esc(row["date"])}</td>'
            f'<td class="r">{row["commits"] or "·"}</td>'
            f'<td class="r pos">{fmt_int(row["added"]) if row["added"] else "·"}</td>'
            f'<td class="r neg">{fmt_int(row["removed"]) if row["removed"] else "·"}</td>'
            f'<td class="r">{fmt_signed(row["net"]) if row["net"] else "·"}</td>'
            f'<td class="r">{row["files"] or "·"}</td>'
            f'{codex_cells}'
            f'<td class="mono">{esc(", ".join(row["repos"])) or "·"}</td></tr>'
        )
    # The tasks total comes from the period metric, NOT from summing the column:
    # a task active on three days appears in three rows and must still count once.
    tasks_total = (fmt_int((data.get("codex") or {}).get("tasks") or 0)
                   if codex_available else "—")
    runtime_total = (fmt_duration(totals.get("runtime_seconds", 0))
                     if codex_available else "—")
    out.append(
        f'<tr class="total-row"><td>Total</td>'
        f'<td class="r">{fmt_int(totals.get("commits", 0))}</td>'
        f'<td class="r pos">{fmt_int(totals.get("added", 0))}</td>'
        f'<td class="r neg">{fmt_int(totals.get("removed", 0))}</td>'
        f'<td class="r">{fmt_signed(totals.get("net", 0))}</td>'
        f'<td class="r">{fmt_int(totals.get("files", 0))}</td>'
        f'<td class="r">{tasks_total}</td>'
        f'<td class="r">{fmt_int(totals.get("turns", 0)) if codex_available else "—"}</td>'
        f'<td class="r">{runtime_total}</td><td></td></tr>')
    out.append("</tbody></table></div>")
    if codex_available:
        out.append(
            '<div class="note ai" style="margin-top:12px">The Codex task column '
            'counts a task on every day it was active, so it sums to more than the '
            'period total, which counts each task once. A day with commits and no '
            'turns is work done without the assistant, or history Codex did not '
            'record; a day with turns and no commits is review or investigation '
            'that produced no commit.</div>')
    out.append("</div>")
    return "".join(out)


def render_monthly(data):
    """Calendar-month rollup. Present even in single-month reports: it is the row
    a reader compares against the daily table's total."""
    months = data.get("monthly") or {}
    if not months:
        return ""
    codex_available = bool((data.get("codex") or {}).get("available"))
    peak = max((m["commits"] for m in months.values()), default=0) or 1

    out = ['<div class="section"><div class="section-header">',
           '<div class="section-title">Monthly breakdown</div>',
           '<div class="section-hint">Commits filed under their own calendar month'
           '</div></div>',
           '<div class="card"><table><thead><tr><th>Month</th>',
           '<th class="r">Commits</th><th class="r">Lines +</th>',
           '<th class="r">Lines −</th><th class="r">Net</th>',
           '<th class="r">Commit days</th><th class="r">Codex turns</th>',
           '<th class="r">Runtime</th><th style="width:160px">Share</th>',
           '</tr></thead><tbody>']
    for key, m in months.items():
        width = m["commits"] / peak * 100
        out.append(
            f'<tr><td>{esc(month_name(key))}</td>'
            f'<td class="r">{fmt_int(m["commits"])}</td>'
            f'<td class="r pos">{fmt_int(m["added"])}</td>'
            f'<td class="r neg">{fmt_int(m["removed"])}</td>'
            f'<td class="r">{fmt_signed(m["net"])}</td>'
            f'<td class="r">{m["commit_days"]}</td>'
            f'<td class="r">{fmt_int(m["turns"]) if codex_available else "—"}</td>'
            f'<td class="r">{fmt_duration(m["runtime_seconds"]) if codex_available else "—"}</td>'
            f'<td><div class="bar-track"><div class="bar-fill" '
            f'style="width:{width:.1f}%;background:var(--blue)"></div></div></td></tr>'
        )
    out.append("</tbody></table></div></div>")
    return "".join(out)


def render_repos(data):
    """Per-repository split of the same commits, so "which codebase" is answerable."""
    t = data["totals"]
    repos = data["meta"]["repos"]
    if not repos:
        return ""
    out = ['<div class="section"><div class="section-header">',
           '<div class="section-title">Repositories</div>',
           '<div class="section-hint">How the period\'s commits split across the '
           'audited repositories</div></div>', '<div class="repo-grid">']
    for repo in repos:
        stats = t["repos"].get(repo, {"commits": 0, "lines_added": 0,
                                      "lines_removed": 0, "files_touched": 0})
        share = round(stats["commits"] / t["commits"] * 100) if t["commits"] else 0
        out.append(
            f'<div class="repo-card"><div class="repo-name">{esc(repo)}</div>'
            f'<div class="kpi-sub">{share}% of commits · '
            f'{fmt_int(stats["files_touched"])} file changes</div>'
            f'<div class="repo-nums">'
            f'<div><div class="dev-stat-label">Commits</div>'
            f'<div class="dev-stat-value">{fmt_int(stats["commits"])}</div></div>'
            f'<div><div class="dev-stat-label">Net lines</div>'
            f'<div class="dev-stat-value">'
            f'{fmt_signed(stats["lines_added"] - stats["lines_removed"])}</div></div>'
            f'<div><div class="dev-stat-label">Lines +</div>'
            f'<div class="dev-stat-value pos">{fmt_int(stats["lines_added"])}</div></div>'
            f'<div><div class="dev-stat-label">Lines −</div>'
            f'<div class="dev-stat-value neg">{fmt_int(stats["lines_removed"])}</div></div>'
            f'</div></div>'
        )
    out.append("</div></div>")
    return "".join(out)


def render_work_type(data):
    """Conventional-commit categories, and the implemented / supporting split.

    The split is derived from commit subjects, which is the only local signal for
    it, so the hint says so: a feature commit is implementation, a docs or chore
    commit is supporting work. Reviews and investigations that produced no commit
    are not in this table at all — they show up as Codex turns on days with no
    commits, and in the narrative section.
    """
    t = data["totals"]
    categories = t["categories"]
    total = t["commits"] or 1
    conventional_pct = round(t["conventional_commits"] / total * 100)

    out = ['<div class="section"><div class="section-header">',
           '<div class="section-title">Type of work</div>',
           f'<div class="section-hint">{conventional_pct}% of commits follow the '
           'conventional-commit convention · categories derived from commit '
           'subjects</div></div>',
           '<div class="split-row">',
           '<div class="card"><table><thead><tr><th>Category</th>'
           '<th class="r">Commits</th><th class="r">Share</th>'
           '<th style="width:110px"></th></tr></thead><tbody>']
    for category in CATEGORY_ORDER:
        count = categories.get(category, 0)
        if not count:
            continue
        pct = count / total * 100
        color = CATEGORY_DOT_COLORS[category]
        out.append(
            f'<tr><td>{esc(CATEGORY_LABELS[category])}</td>'
            f'<td class="r">{fmt_int(count)}</td>'
            f'<td class="r">{pct:.0f}%</td>'
            f'<td><div class="bar-track"><div class="bar-fill" '
            f'style="width:{pct:.1f}%;background:{color}"></div></div></td></tr>')
    out.append('</tbody></table></div>')

    impl = t["implementation_commits"]
    supporting = t["supporting_commits"]
    largest = t.get("largest_commit") or {}
    out.append(
        '<div class="card" style="padding:18px">'
        '<div class="chart-title">Implemented work vs supporting work</div>'
        '<div class="dev-stats">'
        f'<div><div class="dev-stat-label">Features and fixes</div>'
        f'<div class="dev-stat-value">{fmt_int(impl)}</div></div>'
        f'<div><div class="dev-stat-label">Refactor, tests, docs, chores</div>'
        f'<div class="dev-stat-value">{fmt_int(supporting)}</div></div>'
        f'<div><div class="dev-stat-label">Avg lines changed per commit</div>'
        f'<div class="dev-stat-value">{t["avg_lines_per_commit"]}</div></div>'
        f'<div><div class="dev-stat-label">Avg commits per active day</div>'
        f'<div class="dev-stat-value">{t["avg_commits_per_active_day"]}</div></div>'
        '</div>'
        + (f'<div class="kpi-sub" style="margin-top:14px">Largest single commit: '
           f'<code class="mono">{esc(largest.get("hash", ""))}</code> in '
           f'{esc(largest.get("repo", ""))} on {esc(largest.get("date", ""))} — '
           f'{fmt_int(largest.get("lines", 0))} lines changed · '
           f'{esc(largest.get("subject", ""))}</div>' if largest else "")
        + '</div></div></div>')
    return "".join(out)


def render_line_kinds(data):
    """Where the committed line changes landed: source, tests, docs, config, generated.

    Two tables on purpose. The first covers the lines the headline totals count;
    the second covers the paths the audit excludes from those totals (lockfiles,
    vendored trees, build output), so the reader can see what was left out rather
    than wonder whether it was quietly included.
    """
    kinds = data.get("line_kinds") or {}
    counted = kinds.get("counted") or {}
    excluded = kinds.get("excluded") or {}
    if not counted and not excluded:
        return ""

    total = sum(v["added"] + v["removed"] for v in counted.values()) or 1
    out = ['<div class="section"><div class="section-header">',
           '<div class="section-title">Line changes by file type</div>',
           '<div class="section-hint">Committed line changes, classified by path · '
           'binaries carry no line counts and are excluded</div></div>',
           '<div class="card"><table><thead><tr><th>File type</th>',
           '<th class="r">Lines +</th><th class="r">Lines −</th>',
           '<th class="r">Net</th><th class="r">File changes</th>',
           '<th class="r">Commits</th><th class="r">Share</th>',
           '<th style="width:110px"></th></tr></thead><tbody>']
    for kind in KIND_ORDER:
        bucket = counted.get(kind)
        if not bucket:
            continue
        lines = bucket["added"] + bucket["removed"]
        pct = lines / total * 100
        out.append(
            f'<tr><td>{esc(KIND_LABELS[kind])}</td>'
            f'<td class="r pos">{fmt_int(bucket["added"])}</td>'
            f'<td class="r neg">{fmt_int(bucket["removed"])}</td>'
            f'<td class="r">{fmt_signed(bucket["added"] - bucket["removed"])}</td>'
            f'<td class="r">{fmt_int(bucket["files"])}</td>'
            f'<td class="r">{fmt_int(bucket["commits"])}</td>'
            f'<td class="r">{pct:.0f}%</td>'
            f'<td><div class="bar-track"><div class="bar-fill" '
            f'style="width:{pct:.1f}%;background:var(--blue)"></div></div></td></tr>')
    out.append("</tbody></table></div>")

    if excluded:
        rows = "".join(
            f'<tr><td>{esc(KIND_LABELS[kind])}</td>'
            f'<td class="r pos">{fmt_int(bucket["added"])}</td>'
            f'<td class="r neg">{fmt_int(bucket["removed"])}</td></tr>'
            for kind in KIND_ORDER if (bucket := excluded.get(kind)))
        out.append(
            '<div class="card" style="margin-top:14px"><table><thead><tr>'
            '<th>Excluded from the totals above</th><th class="r">Lines +</th>'
            '<th class="r">Lines −</th></tr></thead><tbody>' + rows +
            "</tbody></table></div>")
    out.append("</div>")
    return "".join(out)


def render_codex(data):
    """Codex activity, its definitions, and how complete the underlying history is.

    Always rendered, including when nothing could be read: the reader needs to know
    that a metric is missing and why, and an absent section reads as if the metric
    were never part of the report.
    """
    codex = data.get("codex") or {}
    coverage = codex.get("coverage") or {}
    definitions = codex.get("definitions") or {}

    out = ['<div class="section"><div class="section-header">',
           '<div class="section-title">Codex activity</div>',
           '<div class="section-hint">From the local Codex session history on the '
           'machine that ran this audit</div></div>']

    if not codex.get("available"):
        out.append(
            '<div class="note"><strong>Codex metrics unavailable.</strong> No '
            'readable Codex session history was found'
            + (f' under <code>{esc(coverage.get("sessions_dir"))}</code>'
               if coverage.get("sessions_dir") else "")
            + '. Task, turn, runtime and Codex-active-day figures are reported as '
              'Unavailable rather than zero: this data cannot support the claim '
              'that no assistant work happened. Commit-level attribution below '
              'comes from commit messages and is unaffected.</div>')
    else:
        out.append('<div class="kpi-grid">')
        for label, value, sub in [
            ("Tasks", fmt_int(codex["tasks"]),
             "distinct sessions active in the period"),
            ("Turns", fmt_int(codex["turns"]),
             "instructions started in the period"),
            ("Recorded runtime", fmt_duration(codex["runtime_seconds"]),
             f"{fmt_hours(codex['runtime_seconds'])} h of merged turn intervals"),
            ("Days with activity", fmt_int(codex["active_days"]),
             f"{codex.get('first_date') or '—'} → {codex.get('last_date') or '—'}"),
        ]:
            out.append(f'<div class="kpi-card"><div class="kpi-label">{esc(label)}'
                       f'</div><div class="kpi-value dark">{value}</div>'
                       f'<div class="kpi-sub">{esc(sub)}</div></div>')
        out.append("</div>")

    ev = data.get("codex_evidence") or {}
    out.append(
        '<div class="card"><table><thead><tr><th>Commit-level evidence</th>'
        '<th class="r">Commits</th><th>What it means</th></tr></thead><tbody>'
        f'<tr><td>Explicit attribution <span class="pill ai">AI</span></td>'
        f'<td class="r">{fmt_int(ev.get("attributed", 0))}</td>'
        f'<td class="note-cell">The commit message names the assistant in a '
        f'trailer or footer. Direct evidence.</td></tr>'
        f'<tr><td>Authored during a recorded session</td>'
        f'<td class="r">{fmt_int(ev.get("concurrent_only", 0)) if codex.get("available") else UNAVAILABLE}</td>'
        f'<td class="note-cell">The assistant was running when the commit was '
        f'authored. Circumstantial: it is not evidence that the assistant wrote '
        f'it.</td></tr>'
        f'<tr><td>No assistant evidence</td>'
        f'<td class="r">{fmt_int(ev.get("no_evidence", 0))}</td>'
        f'<td class="note-cell">Neither signal is present.</td></tr>'
        "</tbody></table></div>")

    if definitions:
        out.append('<div class="card" style="margin-top:14px"><table><thead><tr>'
                   '<th>Definition</th><th>Meaning</th></tr></thead><tbody>')
        for key in ("task", "turn", "recorded_runtime", "active_day"):
            if key in definitions:
                out.append(f'<tr><td>{esc(key.replace("_", " ").title())}</td>'
                           f'<td class="note-cell">{esc(definitions[key])}</td></tr>')
        out.append("</tbody></table></div>")

    if coverage.get("files_found") is not None:
        gaps = []
        if coverage.get("files_failed"):
            gaps.append(f'{coverage["files_failed"]} session files could not be read')
        if coverage.get("unreadable_lines"):
            gaps.append(f'{fmt_int(coverage["unreadable_lines"])} history lines '
                        'carried no usable timestamp')
        if coverage.get("sessions_without_cwd"):
            gaps.append(f'{coverage["sessions_without_cwd"]} sessions recorded no '
                        'working directory and could not be attributed to this '
                        'project')
        if coverage.get("turns_without_duration"):
            gaps.append(f'{coverage["turns_without_duration"]} turns had no end '
                        'timestamp and contribute no runtime')
        out.append(
            '<div class="note ai" style="margin-top:14px"><strong>Data coverage.'
            f'</strong> {coverage.get("files_found", 0)} session files found, '
            f'{coverage.get("files_parsed", 0)} parsed, '
            f'{coverage.get("sessions_matched", 0)} attributed to this project'
            + ("; " + "; ".join(gaps) if gaps else "")
            + ".</div>")
    out.append("</div>")
    return "".join(out)


def render_rhythm(data):
    """Day-of-week and hour-of-day distribution of the commits counted above."""
    rhythm = data.get("rhythm") or {}
    dow = rhythm.get("dow") or []
    hours = rhythm.get("hours") or []
    if not any(d["commits"] for d in dow):
        return ""
    max_dow = max(d["commits"] for d in dow) or 1
    max_hour = max((h["commits"] for h in hours), default=0) or 1
    total = sum(d["commits"] for d in dow) or 1
    weekend_pct = round(rhythm.get("weekend_commits", 0) / total * 100)
    off_pct = round(rhythm.get("off_hours_commits", 0) / total * 100)

    out = ['<div class="section"><div class="section-header">',
           '<div class="section-title">Working rhythm</div>',
           f'<div class="section-hint">{weekend_pct}% of commits on weekends · '
           f'{off_pct}% outside 08:00–20:00 · each commit rendered in its own '
           'recorded offset</div></div>',
           '<div class="charts-row">',
           '<div class="card" style="padding:18px">'
           '<div class="chart-title">By day of week</div><div class="vbars">']
    for day in dow:
        height = day["commits"] / max_dow * 100
        out.append(f'<div class="vbar" title="{esc(day["label"])}: '
                   f'{fmt_int(day["commits"])} commits">'
                   f'<div class="vbar-fill" style="height:{height:.1f}%;'
                   f'background:var(--blue)"></div>'
                   f'<div class="vbar-label">{esc(day["label"])}</div></div>')
    out.append('</div></div>')
    out.append('<div class="card" style="padding:18px">'
               '<div class="chart-title">By hour of day</div><div class="vbars">')
    for hour in hours:
        height = hour["commits"] / max_hour * 100
        label = f'{hour["hour"]:02d}' if hour["hour"] % 3 == 0 else ""
        out.append(f'<div class="vbar" title="{hour["hour"]:02d}:00 — '
                   f'{fmt_int(hour["commits"])} commits">'
                   f'<div class="vbar-fill" style="height:{height:.1f}%;'
                   f'background:var(--green)"></div>'
                   f'<div class="vbar-label">{label}</div></div>')
    out.append('</div></div></div></div>')
    return "".join(out)


def render_hotspots(data):
    """The files and directories this month's work actually concentrated in."""
    hotspots = data.get("hotspots") or {}
    files = (hotspots.get("files") or [])[:HOTSPOT_FILE_ROWS]
    dirs = hotspots.get("dirs") or []
    if not files and not dirs:
        return ""

    out = ['<div class="section"><div class="section-header">',
           '<div class="section-title">Code hotspots</div>',
           f'<div class="section-hint">'
           f'{fmt_int(hotspots.get("total_files_touched", 0))} distinct files '
           'touched in the period</div></div>', '<div class="split-row">']

    if dirs:
        peak = max(d["files"] for d in dirs) or 1
        out.append('<div class="card"><table><thead><tr><th>Directory</th>'
                   '<th class="r">File changes</th><th class="r">Commits</th>'
                   '<th style="width:90px"></th></tr></thead><tbody>')
        for row in dirs:
            width = row["files"] / peak * 100
            out.append(f'<tr><td class="mono">{esc(row["dir"])}</td>'
                       f'<td class="r">{fmt_int(row["files"])}</td>'
                       f'<td class="r">{fmt_int(row["commits"])}</td>'
                       f'<td><div class="bar-track"><div class="bar-fill" '
                       f'style="width:{width:.1f}%;background:var(--amber)">'
                       f'</div></div></td></tr>')
        out.append("</tbody></table></div>")

    if files:
        out.append('<div class="card"><table><thead><tr><th>File</th>'
                   '<th class="r">Commits</th><th class="r">Lines +</th>'
                   '<th class="r">Lines −</th></tr></thead><tbody>')
        for row in files:
            out.append(f'<tr><td class="mono">{esc(row["repo"])}/'
                       f'{esc(row["path"])}</td>'
                       f'<td class="r">{fmt_int(row["commits"])}</td>'
                       f'<td class="r pos">{fmt_int(row["added"])}</td>'
                       f'<td class="r neg">{fmt_int(row["removed"])}</td></tr>')
        out.append("</tbody></table></div>")
    out.append("</div></div>")
    return "".join(out)


def render_branches(data):
    """Branches whose tip commit is this developer's — not every branch in the repo."""
    branches = data.get("branches") or []
    if not branches:
        return ""
    shown = branches[:BRANCH_ROWS_SHOWN]
    hint = f"{len(branches)} branches whose latest commit is mine"
    if len(branches) > BRANCH_ROWS_SHOWN:
        hint += f" · showing the {BRANCH_ROWS_SHOWN} largest"
    out = ['<div class="section"><div class="section-header">',
           '<div class="section-title">Branches</div>',
           f'<div class="section-hint">{esc(hint)} · attribution is by tip commit '
           'only, so a branch whose last commit is someone else\'s is not listed'
           '</div></div>',
           '<div class="card scroll-y"><table><thead><tr><th>Branch</th>',
           '<th>Repository</th><th>Where</th><th class="r">Commits to tip</th>',
           '<th>Latest commit</th><th>Subject</th></tr></thead><tbody>']
    for row in shown:
        where = "remote" if row["is_remote"] else "local"
        out.append(f'<tr><td class="mono">{esc(row["name"])}</td>'
                   f'<td class="mono">{esc(row["repo"])}</td>'
                   f'<td>{where}</td>'
                   f'<td class="r">{fmt_int(row["commits"])}</td>'
                   f'<td class="mono">{esc(row["tip_date"])}</td>'
                   f'<td>{esc(row["tip_subject"])}</td></tr>')
    out.append("</tbody></table></div></div>")
    return "".join(out)


def render_methodology(data):
    """How every figure was collected, and what the collection cannot see.

    This section is not optional garnish. The report's numbers are only defensible
    with the limits stated next to them, and a client-facing document that states
    them once, in full, is harder to misread than one that footnotes them.
    """
    m = data["meta"]
    identity = data.get("attribution") or {}
    emails = ", ".join(m.get("emails") or []) or "—"

    items = [
        ("Scope", f'Read-only analysis of {len(m["repos"])} local clone(s): '
                  f'<code>{esc(", ".join(m["repos"]))}</code>. Git is read with '
                  f'<code>git log {esc(m["scope"])} --numstat</code> over all local '
                  f'and remote-tracking refs. No branch was switched, no commit '
                  f'created, nothing pushed.'),
        ("Identity", f'Commits are counted as mine when the author email is one of: '
                     f'<code>{esc(emails)}</code>, resolved from '
                     f'{esc(identity.get("source") or "config")}. Commits by other '
                     f'authors and by bots are excluded.'),
        ("Deduplication", 'Commits are deduplicated by full SHA. Merge commits are excluded. '
                          'Cherry-pick, rebase and squash copies are '
                          'distinct SHAs with identical diffs and are therefore '
                          'counted separately; the duplicate-content note above '
                          'quantifies them where the scan ran.'),
        ("Line counts", 'Additions and deletions come from the same commits counted '
                        'above, via <code>--numstat</code>. They are committed line '
                        'changes, not unique lines written: a line edited in three '
                        'commits counts three times, and a moved file counts as both '
                        'a deletion and an addition. Binary files carry no line '
                        'counts and are excluded. Lockfiles, vendored trees and '
                        'build output are excluded from the totals and reported '
                        'separately.'),
        ("Uncommitted work", 'Working-tree changes that were never committed are '
                             'outside every total in this report.'),
        ("Codex activity", 'Tasks, turns, runtime and Codex-active days come from '
                           'the local Codex session history. Runtime is the union '
                           'of turn intervals, clipped to the reporting period and '
                           'merged so overlapping work counts once; idle time '
                           'between turns is excluded. Runtime includes tool '
                           'execution and waiting. It is recorded assistant runtime '
                           'and not developer working hours, and no time saved is '
                           'inferred from it.'),
        ("Human working hours", 'Not reliably measurable from available records, and '
                                'therefore not reported.'),
        ("Timezone", f'All day boundaries use {esc(m.get("timezone") or "UTC")}. '
                     f'Commit times are recorded in each commit\'s own offset and '
                     f'are read as local time in that zone, which is an '
                     f'approximation for any commit authored in a different offset.'),
        ("Collection cutoff", esc(m.get("cutoff") or m.get("generated_at") or "—")),
    ]
    rows = "".join(f'<tr><td style="white-space:nowrap">{esc(label)}</td>'
                   f'<td class="note-cell">{body}</td></tr>' for label, body in items)
    return ('<div class="section"><div class="section-header">'
            '<div class="section-title">Methodology and data coverage</div>'
            '<div class="section-hint">What was measured, and what the measurement '
            'cannot see</div></div>'
            '<div class="card"><table><thead><tr><th>Topic</th><th>Detail</th>'
            f'</tr></thead><tbody>{rows}</tbody></table></div></div>')


def render_footer(data):
    m = data["meta"]
    return f"""
<div class="footer">
  <span>Generated by <code>auditProcessPersonal/audit.py</code> ·
    {esc(m['generated_at'])}</span>
  <span><code>git log {esc(m['scope'])} --numstat</code> over
    <code>{esc(" + ".join(m["repos"]))}</code></span>
</div>
"""


def generate_report(data):
    body = "".join([
        render_page_header(data),
        '<div class="page">',
        render_notes(data),
        render_kpis(data),
        render_summary(data),
        render_daily(data),
        render_calendar(data),
        render_monthly(data),
        render_repos(data),
        render_work_type(data),
        render_line_kinds(data),
        render_codex(data),
        render_rhythm(data),
        render_hotspots(data),
        render_branches(data),
        render_methodology(data),
        "</div>",
        render_footer(data),
        CALENDAR_JS,
    ])
    project = data["meta"].get("project") or ""
    person = data["meta"].get("person") or ""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f"<title>{esc(project)} — development report · {esc(person)}</title>\n"
        f"<style>{RENDER_CSS}{CALENDAR_CSS}</style>\n</head>\n<body>\n"
        f"{body}\n</body>\n</html>\n"
    )
