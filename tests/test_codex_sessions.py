"""Tests for the Codex rollout parser.

The rollout schema has changed across Codex versions, so the parser is tolerant by
design. These tests pin both shapes it accepts and, just as importantly, what it
must NOT count: injected context messages, and lines it cannot read.
"""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.codex_sessions import (belongs_to_project, classify_event, clip,
                                find_session_files, merge_intervals, parse_timestamp,
                                parse_session_lines)


def at(stamp):
    return datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)


def envelope(stamp, kind, payload=None):
    return json.dumps({"timestamp": stamp, "type": kind, "payload": payload or {}})


def user_msg(stamp, text):
    return envelope(stamp, "response_item",
                    {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": text}]})


def other(stamp):
    return envelope(stamp, "response_item", {"type": "function_call", "name": "shell"})


class TestParseTimestamp(unittest.TestCase):
    def test_reads_a_zulu_timestamp(self):
        self.assertEqual(parse_timestamp("2026-09-10T10:00:00.000Z"),
                         at("2026-09-10T10:00:00"))

    def test_reads_an_explicit_offset(self):
        parsed = parse_timestamp("2026-09-10T07:00:00-03:00")
        self.assertEqual(parsed.astimezone(timezone.utc), at("2026-09-10T10:00:00"))

    def test_a_naive_timestamp_is_read_as_utc(self):
        # Treating it as local would shift every interval by the auditing
        # machine's offset with no evidence that is what was meant.
        self.assertEqual(parse_timestamp("2026-09-10T10:00:00"),
                         at("2026-09-10T10:00:00"))

    def test_garbage_and_empties_return_none(self):
        for value in ["", None, "not a time", 12345]:
            self.assertIsNone(parse_timestamp(value))


class TestClassifyEvent(unittest.TestCase):
    def test_a_typed_user_message_opens_a_turn(self):
        stamp, role = classify_event(json.loads(user_msg("2026-09-10T10:00:00Z", "go")))
        self.assertEqual(role, "user")
        self.assertEqual(stamp, at("2026-09-10T10:00:00"))

    def test_an_event_msg_user_message_also_counts(self):
        stamp, role = classify_event(json.loads(envelope(
            "2026-09-10T10:00:00Z", "event_msg",
            {"type": "user_message", "message": "go"})))
        self.assertEqual(role, "user")

    def test_injected_context_is_not_an_instruction(self):
        for tag in ["<environment_context>x", "<user_instructions>x", "# AGENTS.md"]:
            _stamp, role = classify_event(
                json.loads(user_msg("2026-09-10T10:00:00Z", tag)))
            self.assertEqual(role, "other", tag)

    def test_leading_whitespace_does_not_hide_an_injected_tag(self):
        _stamp, role = classify_event(
            json.loads(user_msg("2026-09-10T10:00:00Z", "\n  <environment_context>x")))
        self.assertEqual(role, "other")

    def test_assistant_work_is_other(self):
        _stamp, role = classify_event(json.loads(other("2026-09-10T10:00:00Z")))
        self.assertEqual(role, "other")

    def test_a_line_with_no_timestamp_is_unusable(self):
        self.assertEqual(classify_event({"type": "response_item"}), (None, None))

    def test_a_non_dict_record_is_unusable(self):
        self.assertEqual(classify_event("just a string"), (None, None))


class TestParseSessionLines(unittest.TestCase):
    def test_completion_and_abort_exclude_later_idle_events(self):
        for kind in ("task_complete", "turn_aborted"):
            with self.subTest(kind=kind):
                parsed = parse_session_lines([
                    user_msg("2026-09-10T10:00:00Z", "go"),
                    envelope("2026-09-10T10:05:00Z", "event_msg", {"type": kind}),
                    envelope("2026-09-11T10:00:00Z", "turn_context"),
                    user_msg("2026-09-11T10:01:00Z", "again"),
                    other("2026-09-11T10:03:00Z"),
                ])
                self.assertEqual(len(parsed["turns"]), 2)
                self.assertEqual(parsed["turns"][0]["end"], at("2026-09-10T10:05:00"))
                self.assertEqual(parsed["turns"][1]["start"], at("2026-09-11T10:01:00"))

    def test_final_response_closes_legacy_turn_without_completion_event(self):
        parsed = parse_session_lines([
            user_msg("2026-09-10T10:00:00Z", "go"),
            envelope("2026-09-10T10:05:00Z", "response_item",
                     {"type": "message", "role": "assistant", "phase": "final_answer"}),
            envelope("2026-09-11T10:00:00Z", "turn_context"),
        ])
        self.assertEqual(parsed["turns"][0]["end"], at("2026-09-10T10:05:00"))

    def test_reads_the_session_id_and_cwd_from_the_meta_line(self):
        session = parse_session_lines([
            envelope("2026-09-10T10:00:00Z", "session_meta",
                     {"id": "s1", "cwd": "/proj/catalyst"}),
        ])
        self.assertEqual((session["id"], session["cwd"]), ("s1", "/proj/catalyst"))

    def test_a_turn_runs_from_the_instruction_to_the_last_event_before_the_next(self):
        session = parse_session_lines([
            user_msg("2026-09-10T10:00:00Z", "fix the bug"),
            other("2026-09-10T10:05:00Z"),
            user_msg("2026-09-10T10:20:00Z", "now add a test"),
            other("2026-09-10T10:23:00Z"),
        ])
        self.assertEqual(len(session["turns"]), 2)
        self.assertEqual(session["turns"][0]["end"], at("2026-09-10T10:05:00"))
        self.assertEqual(session["turns"][1]["end"], at("2026-09-10T10:23:00"))

    def test_the_idle_gap_between_turns_is_outside_both_turns(self):
        session = parse_session_lines([
            user_msg("2026-09-10T10:00:00Z", "a"),
            other("2026-09-10T10:05:00Z"),
            user_msg("2026-09-10T10:20:00Z", "b"),
            other("2026-09-10T10:23:00Z"),
        ])
        total = sum((t["end"] - t["start"]).total_seconds() for t in session["turns"])
        self.assertEqual(total, 300 + 180)

    def test_injected_context_does_not_open_a_turn(self):
        session = parse_session_lines([
            user_msg("2026-09-10T10:00:00Z", "<environment_context>x"),
            user_msg("2026-09-10T10:00:05Z", "fix the bug"),
            other("2026-09-10T10:05:00Z"),
        ])
        self.assertEqual(len(session["turns"]), 1)
        self.assertEqual(session["turns"][0]["start"], at("2026-09-10T10:00:05"))

    def test_a_trailing_turn_with_no_later_event_has_no_duration(self):
        session = parse_session_lines([user_msg("2026-09-10T10:00:00Z", "go")])
        self.assertEqual(session["turns_without_duration"], 1)
        self.assertEqual(session["turns"][0]["start"], session["turns"][0]["end"])

    def test_session_start_and_end_span_every_readable_event(self):
        session = parse_session_lines([
            other("2026-09-10T10:00:00Z"),
            other("2026-09-10T11:30:00Z"),
        ])
        self.assertEqual(session["start"], at("2026-09-10T10:00:00"))
        self.assertEqual(session["end"], at("2026-09-10T11:30:00"))

    def test_unparseable_lines_are_counted_not_fatal(self):
        session = parse_session_lines([
            "{not json",
            envelope("2026-09-10T10:00:00Z", "response_item", {"type": "x"}),
            json.dumps({"type": "response_item"}),
        ])
        self.assertEqual(session["unreadable_lines"], 2)
        self.assertEqual(session["events"], 1)

    def test_blank_lines_are_ignored_entirely(self):
        session = parse_session_lines(["", "   ", other("2026-09-10T10:00:00Z")])
        self.assertEqual(session["unreadable_lines"], 0)
        self.assertEqual(session["events"], 1)

    def test_an_empty_file_yields_an_empty_session(self):
        session = parse_session_lines([])
        self.assertEqual(session["turns"], [])
        self.assertIsNone(session["start"])


class TestBelongsToProject(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "api" / "src").mkdir(parents=True)

    def test_a_session_inside_the_project_matches(self):
        self.assertTrue(belongs_to_project({"cwd": str(self.root / "api" / "src")},
                                           [str(self.root / "api")]))

    def test_the_project_root_itself_matches(self):
        self.assertTrue(belongs_to_project({"cwd": str(self.root / "api")},
                                           [str(self.root / "api")]))

    def test_a_sibling_directory_does_not_match(self):
        self.assertFalse(belongs_to_project({"cwd": str(self.root)},
                                            [str(self.root / "api")]))

    def test_no_configured_paths_means_no_filtering(self):
        self.assertTrue(belongs_to_project({"cwd": "/anywhere"}, []))

    def test_a_session_with_no_cwd_cannot_be_attributed(self):
        self.assertFalse(belongs_to_project({"cwd": None}, [str(self.root / "api")]))


class TestMergeIntervals(unittest.TestCase):
    def test_overlapping_intervals_become_one(self):
        merged = merge_intervals([(at("2026-09-10T10:00:00"), at("2026-09-10T10:30:00")),
                                  (at("2026-09-10T10:20:00"), at("2026-09-10T10:50:00"))])
        self.assertEqual(merged, [(at("2026-09-10T10:00:00"),
                                   at("2026-09-10T10:50:00"))])

    def test_touching_intervals_merge(self):
        merged = merge_intervals([(at("2026-09-10T10:00:00"), at("2026-09-10T10:30:00")),
                                  (at("2026-09-10T10:30:00"), at("2026-09-10T10:40:00"))])
        self.assertEqual(len(merged), 1)

    def test_a_contained_interval_is_absorbed(self):
        merged = merge_intervals([(at("2026-09-10T10:00:00"), at("2026-09-10T11:00:00")),
                                  (at("2026-09-10T10:10:00"), at("2026-09-10T10:20:00"))])
        self.assertEqual(merged, [(at("2026-09-10T10:00:00"),
                                   at("2026-09-10T11:00:00"))])

    def test_disjoint_intervals_stay_separate_and_sorted(self):
        merged = merge_intervals([(at("2026-09-10T12:00:00"), at("2026-09-10T12:10:00")),
                                  (at("2026-09-10T10:00:00"), at("2026-09-10T10:10:00"))])
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0][0], at("2026-09-10T10:00:00"))

    def test_zero_length_intervals_are_dropped(self):
        self.assertEqual(
            merge_intervals([(at("2026-09-10T10:00:00"), at("2026-09-10T10:00:00"))]), [])


class TestClip(unittest.TestCase):
    def test_clips_an_overhanging_interval_to_the_window(self):
        clipped = clip((at("2026-09-10T09:00:00"), at("2026-09-10T11:00:00")),
                       at("2026-09-10T10:00:00"), at("2026-09-10T10:30:00"))
        self.assertEqual(clipped, (at("2026-09-10T10:00:00"),
                                   at("2026-09-10T10:30:00")))

    def test_an_interval_entirely_outside_the_window_is_dropped(self):
        self.assertIsNone(clip((at("2026-09-09T10:00:00"), at("2026-09-09T11:00:00")),
                               at("2026-09-10T00:00:00"), at("2026-09-11T00:00:00")))


class TestFindSessionFiles(unittest.TestCase):
    def test_finds_rollouts_nested_under_dated_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            nested = Path(tmp) / "2026" / "09" / "10"
            nested.mkdir(parents=True)
            (nested / "rollout-a.jsonl").write_text("")
            (nested / "notes.txt").write_text("")
            found = find_session_files(tmp)
            self.assertEqual([p.name for p in found], ["rollout-a.jsonl"])

    def test_a_missing_directory_is_not_an_error(self):
        # Codex may simply not be installed on the machine running the audit.
        self.assertEqual(find_session_files("/nonexistent/codex/sessions"), [])
