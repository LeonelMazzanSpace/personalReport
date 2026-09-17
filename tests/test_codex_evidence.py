"""Tests for assistant-assistance evidence on commits.

The distinction these pin is the one the report exists to be honest about:
explicit attribution is evidence, running at the same time is not.
"""
import unittest
from datetime import datetime, timezone

from src.codex_evidence import (DEFAULT_EVIDENCE_PATTERNS, annotate, commit_instant,
                                compile_patterns, has_attribution, summarize)

UTC = timezone.utc


def commit(hash="a1", subject="feat: x", date="2026-09-10", time="13:10"):
    return {"hash": hash, "subject": subject, "date": date, "time": time}


def at(stamp):
    return datetime.fromisoformat(stamp).replace(tzinfo=UTC)


class TestHasAttribution(unittest.TestCase):
    def setUp(self):
        self.patterns = compile_patterns()

    def test_a_codex_co_author_trailer_counts(self):
        self.assertTrue(has_attribution(
            "feat: x\n\nCo-authored-by: Codex <noreply@openai.com>", self.patterns))

    def test_a_claude_co_author_trailer_counts(self):
        self.assertTrue(has_attribution(
            "fix: y\n\nCo-Authored-By: Claude <noreply@anthropic.com>", self.patterns))

    def test_a_generated_with_footer_counts(self):
        self.assertTrue(has_attribution(
            "feat: x\n\nGenerated with [Claude Code](https://claude.com)",
            self.patterns))

    def test_an_assisted_by_trailer_counts(self):
        self.assertTrue(has_attribution("feat: x\n\nAssisted-by: Codex",
                                        self.patterns))

    def test_the_trailer_must_start_its_own_line(self):
        # "as discussed, co-authored-by codex" in prose is not an attribution.
        self.assertFalse(has_attribution(
            "feat: mention that this was co-authored-by codex somewhere",
            self.patterns))

    def test_merely_naming_the_tool_is_not_attribution(self):
        self.assertFalse(has_attribution("feat: add codex integration endpoint",
                                         self.patterns))

    def test_an_empty_or_missing_message_is_not_attribution(self):
        self.assertFalse(has_attribution("", self.patterns))
        self.assertFalse(has_attribution(None, self.patterns))

    def test_a_project_can_supply_its_own_patterns(self):
        patterns = compile_patterns([r"(?im)^\s*x-robot:"])
        self.assertTrue(has_attribution("feat: x\n\nX-Robot: yes", patterns))
        self.assertFalse(has_attribution("feat: x\n\nCo-authored-by: Codex", patterns))

    def test_the_default_patterns_all_compile(self):
        self.assertEqual(len(compile_patterns()), len(DEFAULT_EVIDENCE_PATTERNS))


class TestCommitInstant(unittest.TestCase):
    def test_reads_the_commit_wall_clock_in_the_reporting_zone(self):
        self.assertEqual(commit_instant(commit(date="2026-09-10", time="13:10"), UTC),
                         at("2026-09-10T13:10:00"))


class TestAnnotate(unittest.TestCase):
    def test_marks_attribution_from_the_commit_body(self):
        commits = [commit()]
        annotate(commits, {"a1": "body\n\nCo-authored-by: Codex <x@y>"})
        self.assertTrue(commits[0]["codex_attributed"])

    def test_marks_attribution_from_the_subject_alone(self):
        commits = [commit(subject="feat: x\n")]
        annotate(commits, {"a1": "Assisted-by: Codex"})
        self.assertTrue(commits[0]["codex_attributed"])

    def test_a_commit_with_no_body_is_not_attributed(self):
        commits = [commit()]
        annotate(commits, {})
        self.assertFalse(commits[0]["codex_attributed"])

    def test_concurrency_is_flagged_only_inside_a_recorded_interval(self):
        commits = [commit(hash="a1", time="13:10"), commit(hash="a2", time="19:00")]
        annotate(commits, {},
                 [(at("2026-09-10T13:00:00"), at("2026-09-10T13:30:00"))], zone=UTC)
        self.assertTrue(commits[0]["codex_concurrent"])
        self.assertFalse(commits[1]["codex_concurrent"])

    def test_without_intervals_nothing_is_concurrent(self):
        commits = [commit()]
        annotate(commits, {}, [], zone=UTC)
        self.assertFalse(commits[0]["codex_concurrent"])

    def test_annotate_returns_the_same_list_it_mutated(self):
        commits = [commit()]
        self.assertIs(annotate(commits, {}), commits)


class TestSummarize(unittest.TestCase):
    def test_attribution_takes_precedence_over_mere_concurrency(self):
        # A commit that is both must be counted once, as the stronger signal.
        result = summarize([{"codex_attributed": True, "codex_concurrent": True},
                            {"codex_attributed": False, "codex_concurrent": True},
                            {"codex_attributed": False, "codex_concurrent": False}])
        self.assertEqual(result, {"commits": 3, "attributed": 1,
                                  "concurrent_only": 1, "no_evidence": 1})

    def test_the_three_buckets_always_sum_to_the_commit_count(self):
        result = summarize([{"codex_attributed": True, "codex_concurrent": True}] * 5)
        self.assertEqual(result["attributed"] + result["concurrent_only"]
                         + result["no_evidence"], result["commits"])

    def test_commits_without_the_flags_are_counted_as_no_evidence(self):
        self.assertEqual(summarize([{}])["no_evidence"], 1)

    def test_an_empty_list_is_all_zeros(self):
        self.assertEqual(summarize([]), {"commits": 0, "attributed": 0,
                                         "concurrent_only": 0, "no_evidence": 0})
