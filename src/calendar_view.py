"""The day calendar heatmap and its drill-down modal.

A personal report has one subject, so the team audit's person x month grid would
be a single row. The useful axis is time at day resolution: weeks as columns,
Monday-to-Sunday as rows, one cell per calendar day — the layout that shows a
month's working rhythm at a glance, including the days with nothing on them.

Two things here are load-bearing:

* Cell heat is scaled to the busiest day in the range, so a quiet month does not
  render as a wall of pale cells against some absolute scale.
* Every "<" in the embedded JSON is escaped to \\u003c. A commit subject containing
  "</script>" would otherwise close the block early.
"""
import html
import json
import math

from src.calendar_labels import (DOW_LABELS, iso_week_key, month_label,
                                 week_bounds, week_range)
from src.classify import CATEGORY_ORDER
from src.format import fmt_duration, fmt_int, short_num

HEAT_COLORS = [
    {"bg": "#F4F6F9", "fg": "#C5CFD9"},
    {"bg": "#DBE7FB", "fg": "#1C2B3A"},
    {"bg": "#A9C6F5", "fg": "#1C2B3A"},
    {"bg": "#5A8DE8", "fg": "#FFFFFF"},
    {"bg": "#1A56DB", "fg": "#FFFFFF"},
]

CATEGORY_DOT_COLORS = {
    "feature": "#1A56DB", "fix": "#D43030", "refactor": "#B45309",
    "test": "#0D9F6E", "docs": "#0891B2", "revert": "#9333EA",
    "wip": "#C2410C", "other": "#8A9BB0",
}
assert set(CATEGORY_DOT_COLORS) == set(CATEGORY_ORDER)

CALENDAR_CSS = """
.cal-legend {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  font-size: 11px; color: var(--text-muted); margin-bottom: 10px;
}
.cal-swatch { width: 14px; height: 14px; border-radius: 3px; border: 1px solid var(--border); }
.cal-outer {
  overflow-x: auto; background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; box-shadow: var(--shadow-sm); padding: 12px;
}
/* width:auto overrides the global `table { width: 100% }`: a day grid is sized by
   its cells, and stretching it strands the columns against the right edge. */
.cal-table { width: auto; border-collapse: separate; border-spacing: 3px; }
.cal-table th, .cal-table td { border: none; padding: 0; background: none; }
.cal-dow-th {
  font-size: 10px; font-weight: 600; color: var(--text-muted); text-align: right;
  padding-right: 8px; white-space: nowrap; text-transform: none; letter-spacing: 0;
}
.cal-month-th {
  font-size: 10px; font-weight: 700; color: var(--text-sec); text-align: left;
  padding-bottom: 4px; white-space: nowrap; text-transform: none; letter-spacing: 0;
}
.cal-cell {
  width: 26px; height: 26px; border-radius: 4px; cursor: pointer;
  outline: 2px solid transparent; outline-offset: 1px; transition: outline-color .1s;
  font-size: 10px; font-weight: 700; text-align: center; vertical-align: middle;
  font-variant-numeric: tabular-nums;
}
.cal-cell.empty { cursor: default; }
.cal-cell.outside { opacity: .35; }
.cal-cell[data-codex="1"] { box-shadow: inset 0 -3px 0 rgba(147,51,234,.75); }
.cal-cell:not(.empty):hover, .cal-cell:focus-visible, .cal-cell.is-open {
  outline-color: var(--blue);
}
.cal-blank { width: 26px; height: 26px; }

#cal-modal {
  position: fixed; z-index: 50; display: none; width: 440px;
  max-width: calc(100vw - 24px); max-height: 74vh; overflow-y: auto;
  background: var(--surface); border: 1px solid var(--border-dark);
  border-radius: 10px; box-shadow: var(--shadow-lg);
}
#cal-modal.open { display: block; }
.cal-modal-head {
  display: flex; align-items: flex-start; justify-content: space-between; gap: 12px;
  padding: 12px 14px; border-bottom: 1px solid var(--border);
  background: var(--bg); border-radius: 10px 10px 0 0; position: sticky; top: 0;
}
.cal-modal-title { font-size: 13px; font-weight: 700; }
.cal-modal-sub { font-size: 11px; color: var(--text-muted); margin-top: 2px; }
.cal-modal-close {
  border: 1px solid var(--border); background: var(--surface); color: var(--text-sec);
  cursor: pointer; border-radius: 5px; height: 22px; width: 22px; line-height: 1;
  font-size: 13px; padding: 0; display: none; flex-shrink: 0;
}
#cal-modal.pinned .cal-modal-close { display: block; }
.cal-modal-codex {
  padding: 8px 14px; font-size: 11px; color: #5B21B6; background: #F5F3FF;
  border-bottom: 1px solid #DDD6FE;
}
.cal-item {
  display: flex; gap: 7px; align-items: baseline; padding: 6px 14px; font-size: 11px;
  border-bottom: 1px solid var(--border);
}
.cal-item:last-child { border-bottom: none; }
.cal-item-time { font-family: var(--mono); color: var(--text-muted); flex-shrink: 0; }
.cal-item-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.cal-item-repo {
  font-size: 9px; font-weight: 600; padding: 0 4px; border-radius: 3px;
  background: var(--bg); border: 1px solid var(--border); color: var(--text-muted);
  flex-shrink: 0;
}
.cal-item-ai {
  font-size: 9px; font-weight: 700; color: #7C3AED; flex-shrink: 0;
}
.cal-item-subject { color: var(--text-sec); word-break: break-word; }
.cal-item-lines {
  margin-left: auto; font-family: var(--mono); font-size: 10px; flex-shrink: 0;
  white-space: nowrap;
}
.cal-empty { padding: 12px 14px; font-size: 11px; color: var(--text-muted); }
"""


def heat_level(commits, max_commits):
    """0 for no activity, then 1..4. One commit against a max of 40 must still
    reach level 1, which is why this ceils rather than rounds."""
    if commits <= 0 or max_commits <= 0:
        return 0
    return max(1, min(4, math.ceil(commits / max_commits * 4)))


def calendar_weeks(days):
    """The ISO week keys spanning a list of YYYY-MM-DD days, oldest first."""
    if not days:
        return []
    return week_range(iso_week_key(min(days)), iso_week_key(max(days)))


def month_header(weeks):
    """[(label, colspan)] so each month's name sits over its own week columns."""
    groups = []
    for week in weeks:
        key = week_bounds(week)[0][:7]
        if groups and groups[-1][0] == key:
            groups[-1][1] += 1
        else:
            groups.append([key, 1])
    return [(month_label(key), span) for key, span in groups]


def _esc(value):
    return html.escape(str(value))


def embed_json(payload):
    """Serialise the modal payload, neutralising "<" so no subject can break out.

    A bare "</"-only escape still leaves a subject like "<!--<script" able to drive
    the HTML tokenizer into script-data-double-escaped state, where a later literal
    "</script>" no longer closes the element. Escaping every "<" removes the whole
    class of issue and is still valid JSON, since \\u003c decodes to "<".
    """
    return json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")


def _legend():
    out = ['<div class="cal-legend"><span>Fewer commits</span>']
    for color in HEAT_COLORS:
        out.append(f'<div class="cal-swatch" style="background:{color["bg"]}"></div>')
    out.append('<span>More</span>')
    out.append('<span style="margin-left:14px">A purple underline marks a day with '
               'recorded Codex activity. Click any day for its commits.</span></div>')
    return "".join(out)


def _cell(day, row, max_commits, in_period):
    """One day cell, or a blank when the week column has no such day in range."""
    if day is None:
        return '<td class="cal-blank"></td>'
    commits = row["commits"] if row else 0
    level = heat_level(commits, max_commits)
    color = HEAT_COLORS[level]
    classes = "cal-cell" + ("" if row else " empty") + ("" if in_period else " outside")
    codex = "1" if row and (row["turns"] or row["codex_attributed"]) else "0"
    return (
        f'<td class="{classes}" tabindex="0" data-date="{_esc(day)}"'
        f' data-codex="{codex}" style="background:{color["bg"]};color:{color["fg"]}">'
        f'{commits or ""}</td>'
    )


def render_calendar(data):
    """The heatmap section, plus the #cal-data payload and #cal-modal the JS needs."""
    rows = {row["date"]: row for row in data["daily"]}
    days = sorted(rows)
    weeks = calendar_weeks(days)
    if not weeks:
        return ('<div class="section"><div class="section-header">'
                '<div class="section-title">Activity calendar</div></div>'
                '<div class="card" style="padding:14px">No activity in range.</div>'
                '</div>')

    max_commits = max((r["commits"] for r in rows.values()), default=0)
    in_range = set(days)

    out = ['<div class="section"><div class="section-header">',
           '<div class="section-title">Activity calendar</div>',
           '<div class="section-hint">One cell per calendar day, weeks as columns'
           '</div></div>', _legend(), '<div class="cal-outer">',
           '<table class="cal-table"><thead><tr><th></th>']
    for label, span in month_header(weeks):
        out.append(f'<th class="cal-month-th" colspan="{span}">{_esc(label)}</th>')
    out.append('</tr></thead><tbody>')

    for dow in range(7):
        out.append(f'<tr><th class="cal-dow-th">{_esc(DOW_LABELS[dow])}</th>')
        for week in weeks:
            monday = week_bounds(week)[0]
            day = _shift(monday, dow)
            out.append(_cell(day if day in in_range else None,
                             rows.get(day), max_commits, True))
        out.append("</tr>")
    out.append("</tbody></table></div>")

    payload = {
        "days": {d: _modal_row(rows[d], data["day_items"].get(d, [])) for d in days},
        "categoryColors": CATEGORY_DOT_COLORS,
    }
    out.append(f'<script type="application/json" id="cal-data">{embed_json(payload)}'
               '</script>')
    out.append('<div id="cal-modal" role="dialog" aria-label="Day detail"></div>')
    out.append("</div>")
    return "".join(out)


def _shift(monday, dow):
    from datetime import date, timedelta
    return (date.fromisoformat(monday) + timedelta(days=dow)).isoformat()


def _modal_row(row, items):
    return {
        "commits": row["commits"], "added": row["added"], "removed": row["removed"],
        "files": row["files"], "tasks": row["tasks"], "turns": row["turns"],
        "runtime": fmt_duration(row["runtime_seconds"]),
        "hasCodex": bool(row["turns"]),
        "items": items,
    }


CALENDAR_JS = """
<script>
(function () {
  var node = document.getElementById('cal-data');
  var modal = document.getElementById('cal-modal');
  if (!node || !modal) return;
  var DATA = JSON.parse(node.textContent);
  var openTimer = null, closeTimer = null, pinned = false, current = null;

  function fmt(n) { return (n || 0).toLocaleString('en-US'); }

  function esc(text) {
    var holder = document.createElement('div');
    holder.textContent = text == null ? '' : String(text);
    return holder.innerHTML.replace(/"/g, '&quot;');
  }

  function longDate(iso) {
    var parts = (iso || '').split('-');
    var when = new Date(Date.UTC(+parts[0], +parts[1] - 1, +parts[2]));
    return when.toLocaleDateString('en-US', {
      weekday: 'long', year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC'
    });
  }

  function itemHtml(item) {
    var color = DATA.categoryColors[item.category] || DATA.categoryColors.other;
    return '<div class="cal-item">'
      + '<span class="cal-item-dot" style="background:' + color + '"></span>'
      + '<span class="cal-item-time">' + esc(item.time) + '</span>'
      + '<span class="cal-item-repo">' + esc(item.repo) + '</span>'
      + (item.codex ? '<span class="cal-item-ai">AI</span>' : '')
      + '<span class="cal-item-subject">' + esc(item.subject) + '</span>'
      + '<span class="cal-item-lines"><span style="color:#0D9F6E">+' + fmt(item.added)
      + '</span> <span style="color:#D43030">-' + fmt(item.removed) + '</span></span>'
      + '</div>';
  }

  function render(date) {
    var day = DATA.days[date];
    if (!day) return '';
    var sub = day.commits + (day.commits === 1 ? ' commit' : ' commits')
      + ' \\u00b7 +' + fmt(day.added) + ' \\u2212' + fmt(day.removed)
      + ' \\u00b7 ' + day.files + ' file changes';
    var head = '<div class="cal-modal-head"><div>'
      + '<div class="cal-modal-title">' + esc(longDate(date)) + '</div>'
      + '<div class="cal-modal-sub">' + sub + '</div></div>'
      + '<button class="cal-modal-close" type="button" aria-label="Close">&times;</button>'
      + '</div>';
    var codex = day.hasCodex
      ? '<div class="cal-modal-codex">Codex: ' + day.tasks
        + (day.tasks === 1 ? ' task' : ' tasks') + ' \\u00b7 ' + day.turns
        + (day.turns === 1 ? ' turn' : ' turns') + ' \\u00b7 ' + esc(day.runtime)
        + ' recorded runtime</div>'
      : '';
    var body = day.items.length
      ? day.items.map(itemHtml).join('')
      : '<div class="cal-empty">No commits recorded on this day.</div>';
    return head + codex + body;
  }

  function place(cell) {
    var box = cell.getBoundingClientRect();
    modal.style.visibility = 'hidden';
    modal.classList.add('open');
    var height = modal.offsetHeight, width = modal.offsetWidth;
    var top = box.bottom + 8;
    if (top + height > window.innerHeight - 8) {
      top = Math.max(8, box.top - height - 8);
    }
    var left = Math.min(Math.max(8, box.left - width / 2 + box.width / 2),
                        window.innerWidth - width - 8);
    modal.style.top = top + 'px';
    modal.style.left = left + 'px';
    modal.style.visibility = '';
  }

  function open(cell, pin) {
    var date = cell.getAttribute('data-date');
    if (!DATA.days[date]) return;
    clearTimeout(closeTimer);
    if (current && current !== cell) current.classList.remove('is-open');
    current = cell;
    cell.classList.add('is-open');
    pinned = !!pin;
    modal.className = 'open' + (pinned ? ' pinned' : '');
    modal.innerHTML = render(date);
    place(cell);
  }

  function close() {
    modal.className = '';
    pinned = false;
    if (current) { current.classList.remove('is-open'); current = null; }
  }

  document.addEventListener('mouseover', function (event) {
    var cell = event.target.closest && event.target.closest('.cal-cell:not(.empty)');
    if (!cell || pinned) return;
    clearTimeout(openTimer);
    openTimer = setTimeout(function () { open(cell, false); }, 90);
  });

  document.addEventListener('mouseout', function (event) {
    if (pinned) return;
    var to = event.relatedTarget;
    if (to && to.closest && (to.closest('#cal-modal') || to.closest('.cal-cell'))) return;
    clearTimeout(openTimer);
    closeTimer = setTimeout(close, 180);
  });

  document.addEventListener('click', function (event) {
    var cell = event.target.closest && event.target.closest('.cal-cell:not(.empty)');
    if (cell) { open(cell, true); return; }
    if (event.target.closest && event.target.closest('.cal-modal-close')) {
      close(); return;
    }
    if (pinned && !(event.target.closest && event.target.closest('#cal-modal'))) close();
  });

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') close();
    if (event.key !== 'Enter' && event.key !== ' ') return;
    var cell = event.target.closest && event.target.closest('.cal-cell:not(.empty)');
    if (cell) { event.preventDefault(); open(cell, true); }
  });
})();
</script>
"""
