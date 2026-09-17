"""Tests for the headline totals block."""
import unittest

from src.totals import build_totals


def commit(added=10, removed=2, raw_added=None, raw_removed=None, files=2,
           date="2026-09-02", email="ana@work.example", category="feature",
           ctype="feat", conventional=True, refactor=False, repo="api",
           hash="abcdef1234", subject="feat: x", attributed=False,
           concurrent=False):
    return {
        "lines_added": added, "lines_removed": removed,
        "raw_added": raw_added if raw_added is not None else added,
        "raw_removed": raw_removed if raw_removed is not None else removed,
        "files_changed": files, "date": date, "email": email,
        "category": category, "type": ctype, "is_conventional": conventional,
        "is_refactor": refactor, "repo": repo, "hash": hash, "subject": subject,
        "codex_attributed": attributed, "codex_concurrent": concurrent,
    }


class TestBuildTotals(unittest.TestCase):
    def test_sums_lines_and_derives_net_and_total(self):
        t = build_totals([commit(added=10, removed=2), commit(added=5, removed=8)])
        self.assertEqual((t["lines_added"], t["lines_removed"]), (15, 10))
        self.assertEqual(t["net_lines"], 5)
        self.assertEqual(t["total_lines_changed"], 25)

    def test_raw_totals_track_the_excluded_paths_separately(self):
        t = build_totals([commit(added=10, removed=2, raw_added=900, raw_removed=40)])
        self.assertEqual((t["raw_added"], t["raw_removed"]), (900, 40))
        self.assertEqual(t["lines_added"], 10)

    def test_breaks_down_by_repository(self):
        t = build_totals([commit(repo="api"), commit(repo="web", added=1, removed=0)])
        self.assertEqual(t["repos"]["api"]["commits"], 1)
        self.assertEqual(t["repos"]["web"]["lines_added"], 1)

    def test_active_days_counts_distinct_dates_and_span_is_inclusive(self):
        t = build_totals([commit(date="2026-09-01"), commit(date="2026-09-01"),
                          commit(date="2026-09-03")])
        self.assertEqual(t["active_days"], 2)
        self.assertEqual((t["first_date"], t["last_date"]),
                         ("2026-09-01", "2026-09-03"))
        self.assertEqual(t["span_days"], 3)

    def test_a_single_day_spans_one_day_not_zero(self):
        self.assertEqual(build_totals([commit(date="2026-09-01")])["span_days"], 1)

    def test_collects_every_email_the_commits_were_authored_from(self):
        t = build_totals([commit(email="ana@work.example"),
                          commit(email="ana@personal.com")])
        self.assertEqual(t["emails"], ["ana@personal.com", "ana@work.example"])

    def test_features_and_fixes_are_implementation_the_rest_is_supporting(self):
        t = build_totals([commit(category="feature"), commit(category="fix"),
                          commit(category="docs"), commit(category="refactor")])
        self.assertEqual(t["implementation_commits"], 2)
        self.assertEqual(t["supporting_commits"], 2)

    def test_the_two_work_buckets_always_sum_to_the_commit_count(self):
        t = build_totals([commit(category=c) for c in
                          ["feature", "fix", "test", "docs", "wip", "other"]])
        self.assertEqual(t["implementation_commits"] + t["supporting_commits"],
                         t["commits"])

    def test_attribution_takes_precedence_over_concurrency(self):
        t = build_totals([commit(attributed=True, concurrent=True),
                          commit(concurrent=True)])
        self.assertEqual(t["codex_attributed_commits"], 1)
        self.assertEqual(t["codex_concurrent_commits"], 1)

    def test_largest_commit_is_by_total_lines_changed(self):
        t = build_totals([commit(added=10, removed=2, hash="small12"),
                          commit(added=100, removed=900, hash="biggest1234")])
        self.assertEqual(t["largest_commit"]["hash"], "biggest")
        self.assertEqual(t["largest_commit"]["lines"], 1000)

    def test_averages_are_rounded_to_one_decimal(self):
        t = build_totals([commit(added=10, removed=2), commit(added=1, removed=0)])
        self.assertEqual(t["avg_lines_per_commit"], 6.5)
        self.assertEqual(t["avg_commits_per_active_day"], 2.0)

    def test_counts_conventional_and_refactor_commits(self):
        t = build_totals([commit(conventional=True, refactor=True),
                          commit(conventional=False, ctype=None)])
        self.assertEqual(t["conventional_commits"], 1)
        self.assertEqual(t["refactor_commits"], 1)

    def test_an_untyped_commit_does_not_land_in_the_type_table(self):
        t = build_totals([commit(ctype=None, conventional=False)])
        self.assertEqual(t["types"], {})

    def test_an_empty_history_yields_zeros_and_no_dates(self):
        t = build_totals([])
        self.assertEqual(t["commits"], 0)
        self.assertIsNone(t["first_date"])
        self.assertIsNone(t["largest_commit"])
        self.assertEqual(t["span_days"], 0)
        self.assertEqual(t["avg_lines_per_commit"], 0.0)
