"""Tests for the supporting metrics document.

The rule this file exists to protect: a metric with no evidence behind it is
null, never 0. A zero in this JSON is a claim that the month had no such activity.
"""
import json
import unittest

from src.metrics import build_metrics
from src.totals import build_totals


def commit(**over):
    base = {"lines_added": 10, "lines_removed": 2, "raw_added": 12, "raw_removed": 2,
            "files_changed": 2, "date": "2026-09-02", "email": "ana@work.example",
            "category": "feature", "type": "feat", "is_conventional": True,
            "is_refactor": False, "repo": "api", "hash": "abcdef1", "subject": "feat: x",
            "codex_attributed": False, "codex_concurrent": False}
    base.update(over)
    return base


def data(codex=None, evidence=None, commits=None):
    return {
        "meta": {"project": "Catalyst", "person": "Ana Perez",
                 "emails": ["ana@work.example"], "repos": ["api"],
                 "timezone": "America/Montevideo", "scope": "--all --no-merges",
                 "generated_at": "2026-09-17 18:00", "cutoff": "2026-09-17 18:00",
                 "period": {"label": "September 2026", "start": "2026-09-01",
                            "end": "2026-09-17", "month_to_date": True}},
        "totals": build_totals(commits if commits is not None else [commit()]),
        "codex": codex if codex is not None else {"available": False, "coverage": {}},
        "codex_evidence": evidence or {"attributed": 0, "concurrent_only": 0,
                                       "no_evidence": 1},
        "daily_totals": {"commit_days": 1, "active_days": 1, "days_listed": 17},
        "line_kinds": {"counted": {"code": {"added": 10, "removed": 2, "files": 2,
                                            "commits": 1}}, "excluded": {}},
        "attribution": {"source": "config", "ambiguous": []},
        "duplicates": {},
    }


AVAILABLE = {"available": True, "tasks": 12, "turns": 80, "runtime_seconds": 7200,
             "active_days": 9, "by_day": {"2026-09-02": {"tasks": 1, "turns": 3,
                                                         "runtime_seconds": 600}},
             "coverage": {"files_parsed": 20}}


class TestReportBlock(unittest.TestCase):
    def test_carries_the_report_identity_and_cutoff(self):
        report = build_metrics(data())["report"]
        self.assertEqual(report["project"], "Catalyst")
        self.assertEqual(report["person"], "Ana Perez")
        self.assertEqual(report["identities"], ["ana@work.example"])
        self.assertEqual(report["identity_source"], "config")
        self.assertEqual(report["collection_cutoff"], "2026-09-17 18:00")

    def test_the_period_is_reproduced_verbatim(self):
        period = build_metrics(data())["report"]["period"]
        self.assertTrue(period["month_to_date"])
        self.assertEqual(period["start"], "2026-09-01")

    def test_full_history_gets_a_period_built_from_the_data_range(self):
        payload = data()
        payload["meta"]["period"] = None
        period = build_metrics(payload)["report"]["period"]
        self.assertEqual(period["label"], "Full available history")
        self.assertEqual(period["start"], "2026-09-02")
        self.assertFalse(period["month_to_date"])


class TestUnavailableMetricsAreNull(unittest.TestCase):
    def test_codex_figures_are_null_when_no_history_was_read(self):
        activity = build_metrics(data())["activity"]
        for key in ["codex_tasks", "codex_turns", "codex_recorded_runtime_seconds",
                    "codex_active_days", "by_day"]:
            self.assertIsNone(activity[key], key)

    def test_human_working_hours_is_always_null(self):
        # Not reliably measurable from these records, in either direction.
        self.assertIsNone(build_metrics(data())["activity"]["human_working_hours"])
        self.assertIsNone(
            build_metrics(data(codex=AVAILABLE))["activity"]["human_working_hours"])

    def test_concurrency_is_null_without_session_history(self):
        self.assertIsNone(build_metrics(data())["commits"]["codex_concurrent_only"])

    def test_days_with_codex_activity_is_null_not_zero(self):
        self.assertIsNone(build_metrics(data())["days"]["with_codex_activity"])

    def test_real_figures_survive_when_history_is_available(self):
        metrics = build_metrics(data(codex=AVAILABLE))
        self.assertEqual(metrics["activity"]["codex_tasks"], 12)
        self.assertEqual(metrics["activity"]["codex_recorded_runtime_seconds"], 7200)
        self.assertEqual(metrics["days"]["with_codex_activity"], 9)
        self.assertIsNotNone(metrics["activity"]["by_day"])


class TestCommitAndLineBlocks(unittest.TestCase):
    def test_commit_counts_split_implementation_from_supporting(self):
        commits = [commit(category="feature"), commit(category="docs", hash="b")]
        block = build_metrics(data(commits=commits))["commits"]
        self.assertEqual((block["total"], block["implementation"],
                          block["supporting"]), (2, 1, 1))

    def test_lines_carry_both_the_counted_and_the_raw_figures(self):
        lines = build_metrics(data())["lines"]
        self.assertEqual((lines["added"], lines["removed"], lines["net"]), (10, 2, 8))
        self.assertEqual(lines["raw_added_including_excluded"], 12)

    def test_the_file_type_breakdown_travels_with_the_totals(self):
        self.assertEqual(build_metrics(data())["lines"]["by_file_type"]["code"]["added"],
                         10)


class TestCoverageAndDefinitions(unittest.TestCase):
    def test_availability_is_stated_explicitly(self):
        self.assertFalse(build_metrics(data())["coverage"]["codex_metrics_available"])
        self.assertTrue(
            build_metrics(data(codex=AVAILABLE))["coverage"]["codex_metrics_available"])

    def test_unresolved_identities_are_disclosed(self):
        payload = data()
        payload["attribution"]["ambiguous"] = [{"email": "ana@personal.com",
                                                "commits": 3}]
        self.assertEqual(
            build_metrics(payload)["coverage"]["unresolved_identities"][0]["commits"], 3)

    def test_every_reported_metric_family_has_a_definition(self):
        definitions = build_metrics(data())["definitions"]
        for key in ["commit", "committed_line_change", "commit_day", "task", "turn",
                    "recorded_runtime", "active_day"]:
            self.assertIn(key, definitions)

    def test_the_standing_caveats_are_always_present(self):
        notes = " ".join(build_metrics(data())["coverage"]["notes"])
        self.assertIn("Uncommitted", notes)
        self.assertIn("deduplicated by full SHA", notes)
        self.assertIn("not developer working hours", notes)

    def test_the_whole_document_is_json_serialisable(self):
        # It is written to disk verbatim; a stray set or datetime must not slip in.
        json.dumps(build_metrics(data(codex=AVAILABLE)))
