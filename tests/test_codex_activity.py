"""Tests for Codex activity aggregation: tasks, turns, runtime, active days.

The rules pinned here are the ones the report prints as definitions, so a change
that breaks one of these changes what the report is claiming.
"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.codex_activity import (build_activity, collect_codex_activity, get_zone,
                                split_by_day)
from src.period import month_period


def at(stamp):
    return datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)


def session(id="s1", turns=(), path="r.jsonl"):
    return {"id": id, "path": path,
            "turns": [{"start": at(s), "end": at(e)} for s, e in turns]}


MVD = "America/Montevideo"          # UTC-3, no DST


class TestGetZone(unittest.TestCase):
    def test_resolves_a_real_zone(self):
        self.assertIsNotNone(get_zone(MVD))

    def test_an_unknown_zone_falls_back_to_utc_rather_than_failing_the_run(self):
        self.assertEqual(get_zone("Mars/Olympus"), timezone.utc)

    def test_no_zone_is_utc(self):
        self.assertEqual(get_zone(None), timezone.utc)


class TestSplitByDay(unittest.TestCase):
    def test_a_single_day_interval_stays_whole(self):
        parts = split_by_day((at("2026-09-10T13:00:00"), at("2026-09-10T13:30:00")),
                             get_zone(MVD))
        self.assertEqual(parts, [("2026-09-10", 1800)])

    def test_an_interval_crossing_local_midnight_splits_there(self):
        # 02:40Z .. 03:20Z is 23:40 .. 00:20 in Montevideo: 20 minutes each side.
        parts = split_by_day((at("2026-09-11T02:40:00"), at("2026-09-11T03:20:00")),
                             get_zone(MVD))
        self.assertEqual(parts, [("2026-09-10", 1200), ("2026-09-11", 1200)])

    def test_the_split_uses_local_midnight_not_utc_midnight(self):
        parts = split_by_day((at("2026-09-10T23:00:00"), at("2026-09-11T01:00:00")),
                             get_zone(MVD))
        self.assertEqual([d for d, _s in parts], ["2026-09-10"])


class TestBuildActivity(unittest.TestCase):
    def test_travel_schedule_assigns_each_period_to_its_local_day(self):
        activity = build_activity([session(turns=[
            ("2026-09-10T04:00:00", "2026-09-10T05:00:00"),
            ("2026-09-16T04:00:00", "2026-09-16T05:00:00"),
            ("2026-09-13T06:30:00", "2026-09-13T07:30:00"),
        ])], timezone_name=MVD, coverage={"files_parsed": 1},
            timezone_changes=[{"from": "2026-09-13", "timezone": "America/Los_Angeles"}])
        self.assertEqual(activity["by_day"]["2026-09-10"]["runtime_seconds"], 3600)
        self.assertEqual(activity["by_day"]["2026-09-15"]["runtime_seconds"], 3600)
        self.assertEqual(activity["by_day"]["2026-09-13"]["runtime_seconds"], 3600)
        self.assertEqual(activity["by_day"]["2026-09-13"]["turns"], 1)
        self.assertEqual(activity["runtime_seconds"], 10800)
        self.assertEqual(activity["turns"], 3)

    def test_travel_schedule_uses_destination_timezone_at_month_end(self):
        activity = build_activity([session(turns=[
            ("2026-10-01T05:00:00", "2026-10-01T06:00:00"),
        ])], period=month_period("2026-09", today=datetime(2026, 9, 30).date()),
            timezone_name=MVD, coverage={"files_parsed": 1},
            timezone_changes=[{"from": "2026-09-13", "timezone": "America/Los_Angeles"}])
        self.assertEqual(activity["by_day"]["2026-09-30"]["runtime_seconds"], 3600)

    def test_counts_tasks_turns_and_merged_runtime(self):
        activity = build_activity(
            [session(turns=[("2026-09-10T13:00:00", "2026-09-10T13:30:00"),
                            ("2026-09-10T14:00:00", "2026-09-10T14:10:00")])],
            timezone_name=MVD, coverage={"files_parsed": 1})
        self.assertEqual((activity["tasks"], activity["turns"]), (1, 2))
        self.assertEqual(activity["runtime_seconds"], 1800 + 600)

    def test_idle_time_between_turns_is_not_runtime(self):
        activity = build_activity(
            [session(turns=[("2026-09-10T13:00:00", "2026-09-10T13:10:00"),
                            ("2026-09-10T15:00:00", "2026-09-10T15:10:00")])],
            timezone_name=MVD, coverage={"files_parsed": 1})
        self.assertEqual(activity["runtime_seconds"], 1200)

    def test_overlapping_sessions_count_their_shared_time_once(self):
        activity = build_activity([
            session(id="a", turns=[("2026-09-10T13:00:00", "2026-09-10T13:30:00")]),
            session(id="b", turns=[("2026-09-10T13:15:00", "2026-09-10T13:45:00")]),
        ], timezone_name=MVD, coverage={"files_parsed": 1})
        self.assertEqual(activity["runtime_seconds"], 2700)
        self.assertEqual(activity["tasks"], 2)

    def test_daily_runtime_merges_overlap_across_midnight(self):
        activity = build_activity([
            session(id="a", turns=[("2026-09-10T23:00:00", "2026-09-11T02:00:00")]),
            session(id="b", turns=[("2026-09-10T23:30:00", "2026-09-11T01:00:00")]),
        ], timezone_name="UTC", coverage={"files_parsed": 2})
        self.assertEqual(activity["by_day"]["2026-09-10"]["runtime_seconds"], 3600)
        self.assertEqual(activity["by_day"]["2026-09-11"]["runtime_seconds"], 7200)
        self.assertEqual(sum(d["runtime_seconds"] for d in activity["by_day"].values()),
                         activity["runtime_seconds"])
        self.assertEqual(activity["by_day"]["2026-09-10"]["tasks"], 2)

    def test_a_task_spanning_two_days_counts_once_overall_but_on_both_days(self):
        activity = build_activity(
            [session(turns=[("2026-09-11T02:40:00", "2026-09-11T03:20:00")])],
            timezone_name=MVD, coverage={"files_parsed": 1})
        self.assertEqual(activity["tasks"], 1)
        self.assertEqual(sorted(activity["by_day"]), ["2026-09-10", "2026-09-11"])
        self.assertEqual(sum(d["tasks"] for d in activity["by_day"].values()), 2)

    def test_active_days_counts_distinct_calendar_days(self):
        activity = build_activity(
            [session(turns=[("2026-09-10T13:00:00", "2026-09-10T13:30:00"),
                            ("2026-09-12T13:00:00", "2026-09-12T13:30:00")])],
            timezone_name=MVD, coverage={"files_parsed": 1})
        self.assertEqual(activity["active_days"], 2)
        self.assertEqual((activity["first_date"], activity["last_date"]),
                         ("2026-09-10", "2026-09-12"))

    def test_turns_outside_the_period_are_dropped(self):
        period = month_period("2026-09", today=datetime(2026, 9, 30).date())
        activity = build_activity(
            [session(turns=[("2026-08-31T13:00:00", "2026-08-31T13:30:00"),
                            ("2026-09-10T13:00:00", "2026-09-10T13:30:00")])],
            period=period, timezone_name=MVD, coverage={"files_parsed": 1})
        self.assertEqual(activity["turns"], 1)
        self.assertEqual(activity["runtime_seconds"], 1800)

    def test_a_turn_straddling_the_period_edge_is_clipped_not_dropped(self):
        period = month_period("2026-09", today=datetime(2026, 9, 30).date())
        # 2026-09-01 02:40Z is 2026-08-31 23:40 local: 20 min before the period,
        # 20 min inside it.
        activity = build_activity(
            [session(turns=[("2026-09-01T02:40:00", "2026-09-01T03:20:00")])],
            period=period, timezone_name=MVD, coverage={"files_parsed": 1})
        self.assertEqual(activity["runtime_seconds"], 1200)

    def test_a_zero_length_turn_still_counts_as_a_turn(self):
        activity = build_activity(
            [session(turns=[("2026-09-10T13:00:00", "2026-09-10T13:00:00")])],
            timezone_name=MVD, coverage={"files_parsed": 1})
        self.assertEqual(activity["turns"], 1)
        self.assertEqual(activity["runtime_seconds"], 0)
        self.assertEqual(activity["coverage"]["turns_without_duration"], 1)

    def test_available_is_false_when_no_file_could_be_parsed(self):
        # The report prints "Unavailable" off this flag rather than zeros.
        activity = build_activity([], coverage={"files_found": 0, "files_parsed": 0})
        self.assertFalse(activity["available"])

    def test_available_is_true_once_a_file_parsed_even_with_no_turns(self):
        activity = build_activity([], coverage={"files_parsed": 3})
        self.assertTrue(activity["available"])
        self.assertEqual(activity["tasks"], 0)

    def test_merged_intervals_are_exposed_for_commit_annotation(self):
        activity = build_activity(
            [session(turns=[("2026-09-10T13:00:00", "2026-09-10T13:30:00")])],
            timezone_name=MVD, coverage={"files_parsed": 1})
        self.assertEqual(activity["_intervals"],
                         [(at("2026-09-10T13:00:00"), at("2026-09-10T13:30:00"))])

    def test_definitions_travel_with_the_metrics(self):
        activity = build_activity([], coverage={"files_parsed": 1})
        self.assertEqual(set(activity["definitions"]),
                         {"task", "turn", "recorded_runtime", "active_day"})


class TestCollectCodexActivity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sessions = self.root / "sessions"
        self.sessions.mkdir()
        self.project = self.root / "proj"
        self.project.mkdir()

    def write(self, name, cwd, turns):
        lines = [json.dumps({"timestamp": "2026-09-10T09:00:00Z",
                             "type": "session_meta",
                             "payload": {"id": name, "cwd": cwd}})]
        for start, end in turns:
            lines.append(json.dumps({
                "timestamp": start, "type": "event_msg",
                "payload": {"type": "user_message", "message": "go"}}))
            lines.append(json.dumps({
                "timestamp": end, "type": "event_msg",
                "payload": {"type": "agent_message", "message": "done"}}))
        (self.sessions / f"{name}.jsonl").write_text("\n".join(lines))

    def test_reads_only_sessions_that_ran_inside_the_project(self):
        self.write("a", str(self.project),
                   [("2026-09-10T13:00:00Z", "2026-09-10T13:30:00Z")])
        self.write("b", "/elsewhere",
                   [("2026-09-10T14:00:00Z", "2026-09-10T14:30:00Z")])
        activity = collect_codex_activity(self.sessions, [str(self.project)],
                                          timezone_name=MVD)
        self.assertEqual(activity["tasks"], 1)
        self.assertEqual(activity["coverage"]["files_found"], 2)
        self.assertEqual(activity["coverage"]["sessions_matched"], 1)

    def test_a_missing_sessions_directory_reports_unavailable_not_zero(self):
        activity = collect_codex_activity("/nonexistent", [str(self.project)])
        self.assertFalse(activity["available"])
        self.assertEqual(activity["coverage"]["files_found"], 0)

    def test_the_directory_looked_in_is_recorded_for_the_report_to_name(self):
        activity = collect_codex_activity("/nonexistent", [])
        self.assertEqual(activity["coverage"]["sessions_dir"], "/nonexistent")

    def test_a_session_without_a_cwd_is_counted_as_unattributable(self):
        self.write("a", None, [("2026-09-10T13:00:00Z", "2026-09-10T13:30:00Z")])
        activity = collect_codex_activity(self.sessions, [str(self.project)])
        self.assertEqual(activity["coverage"]["sessions_without_cwd"], 1)
        self.assertEqual(activity["coverage"]["sessions_matched"], 0)
