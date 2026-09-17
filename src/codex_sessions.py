"""Read local Codex CLI history: tasks, turns, and recorded runtime.

Codex writes one JSONL rollout file per session under `~/.codex/sessions/`, one
line per event, each carrying an ISO-8601 timestamp. That file is the only local
evidence of how the assistant was actually used, so it is what the activity and
runtime metrics are built from.

The parser is deliberately tolerant, for two reasons. The rollout schema has
changed across Codex versions (bare response items in early builds, a
`{timestamp, type, payload}` envelope in current ones), and a report that crashes
on one unfamiliar line is worse than one that says how much it could not read. So
every file is parsed on a best-effort basis and the run reports `coverage`:
how many files were found, parsed, and left unrecognised. When nothing can be
read, the caller reports the metric as "Unavailable" rather than zero — a zero
would claim the month had no assistant activity.

Definitions, which the report prints verbatim:

* A **task** is one Codex session: one rollout file, one conversation started in
  one working directory.
* A **turn** is one instruction from the developer plus the assistant work that
  follows it, up to the next instruction or the end of the session.
* **Recorded runtime** is the union of those turn intervals. It is wall-clock time
  during which Codex was working — which includes tool execution and waiting —
  and it is not developer working hours.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_SESSIONS_DIR = "~/.codex/sessions"

# Codex injects context into the conversation as user-role messages. They are not
# instructions the developer typed, so counting them would inflate the turn count
# on every session. Matched on the opening tag of the message text.
SYNTHETIC_USER_PREFIXES = (
    "<environment_context>",
    "<user_instructions>",
    "<user_shell>",
    "<system_reminder>",
    "<plan_mode>",
    "# AGENTS.md",
)

# Payload `type` values that mean "the developer asked for something". Anything
# else in the stream extends the current turn but never opens a new one.
USER_EVENT_TYPES = frozenset({"user_message", "user_turn"})


def parse_timestamp(value):
    """ISO-8601 (with Z or an offset) -> aware datetime, or None.

    A naive timestamp is read as UTC: early rollout files wrote them without an
    offset, and treating them as local time would shift every interval by the
    machine's offset without any evidence that that is what they meant.
    """
    if not isinstance(value, str) or not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _text_of(content):
    """Flatten a message `content` field to plain text, whatever shape it has."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get("text") or "")
        return "".join(parts)
    return ""


def _is_synthetic(text):
    stripped = (text or "").lstrip()
    return stripped.startswith(SYNTHETIC_USER_PREFIXES)


def classify_event(record):
    """Return (timestamp, role) for one rollout line. role is 'user' or 'other'.

    Handles both the current `{timestamp, type, payload}` envelope and the older
    flat records, and returns (None, None) for a line with no usable timestamp so
    the caller can count it as unread instead of guessing a time for it.
    """
    if not isinstance(record, dict):
        return None, None
    payload = record.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    stamp = (parse_timestamp(record.get("timestamp"))
             or parse_timestamp(payload.get("timestamp"))
             or parse_timestamp(record.get("ts")))
    if stamp is None:
        return None, None

    kind = payload.get("type") or record.get("type") or record.get("record_type")
    role = payload.get("role") or record.get("role")
    text = _text_of(payload.get("content") or record.get("content")
                    or payload.get("message"))

    is_user = kind in USER_EVENT_TYPES or (role == "user" and kind in
                                           {"message", "input_text", None})
    if is_user and not _is_synthetic(text):
        return stamp, "user"
    return stamp, "other"


def _session_meta(record):
    """Pull cwd/id out of a session_meta line, whichever nesting it uses."""
    payload = record.get("payload") if isinstance(record, dict) else None
    payload = payload if isinstance(payload, dict) else {}
    if (record.get("type") or record.get("record_type")) not in {"session_meta",
                                                                "session.meta",
                                                                "session"}:
        return None
    return {
        "id": payload.get("id") or record.get("id"),
        "cwd": payload.get("cwd") or (payload.get("git") or {}).get("repository_url"),
    }


def parse_session_lines(lines, path=None):
    """Turn one rollout file's lines into a session dict.

    Turns are closed by the NEXT user message: a turn runs from the instruction to
    the last recorded event before the following instruction, which is the only
    end time the rollout actually records. A turn with no subsequent event has no
    measurable duration and is counted in `turns` but contributes nothing to
    runtime — reported as `turns_without_duration` so the gap is visible.
    """
    session = {
        "path": str(path) if path else None,
        "id": None, "cwd": None,
        "start": None, "end": None,
        "turns": [], "events": 0, "unreadable_lines": 0,
        "turns_without_duration": 0,
    }
    open_turn = None
    last_stamp = None

    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            session["unreadable_lines"] += 1
            continue

        meta = _session_meta(record)
        if meta:
            session["id"] = session["id"] or meta["id"]
            session["cwd"] = session["cwd"] or meta["cwd"]

        stamp, role = classify_event(record)
        if stamp is None:
            session["unreadable_lines"] += 1
            continue

        session["events"] += 1
        if session["start"] is None or stamp < session["start"]:
            session["start"] = stamp
        if session["end"] is None or stamp > session["end"]:
            session["end"] = stamp

        if role == "user":
            if open_turn is not None:
                _close_turn(session, open_turn, last_stamp)
            open_turn = stamp
        last_stamp = stamp

    if open_turn is not None:
        _close_turn(session, open_turn, last_stamp)
    return session


def _close_turn(session, start, end):
    if end is None or end <= start:
        session["turns_without_duration"] += 1
        session["turns"].append({"start": start, "end": start})
        return
    session["turns"].append({"start": start, "end": end})


def find_session_files(sessions_dir):
    """Every rollout file under the sessions directory, oldest path first."""
    root = Path(sessions_dir).expanduser()
    if not root.is_dir():
        return []
    return sorted(root.rglob("*.jsonl"))


def belongs_to_project(session, project_paths):
    """True when the session's working directory sits inside an audited path.

    No configured paths means no filter — a sessions directory that only ever held
    this project needs no matching. A session whose rollout records no cwd cannot
    be attributed and is excluded when paths ARE configured, and counted in
    `coverage.sessions_without_cwd` so the omission is disclosed.
    """
    if not project_paths:
        return True
    cwd = session.get("cwd")
    if not cwd:
        return False
    try:
        resolved = Path(cwd).expanduser().resolve()
    except (OSError, RuntimeError):
        return False
    for base in project_paths:
        base = Path(base).expanduser().resolve()
        if resolved == base or base in resolved.parents:
            return True
    return False


def merge_intervals(intervals):
    """Merge overlapping (start, end) pairs so concurrent turns count once."""
    ordered = sorted((i for i in intervals if i[1] > i[0]), key=lambda i: i[0])
    merged = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def clip(interval, start, end):
    """Clip one interval to a window, or None when it falls entirely outside."""
    lo, hi = max(interval[0], start), min(interval[1], end)
    return (lo, hi) if hi > lo else None
