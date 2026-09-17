"""Tests for the daily activity table and its rollups."""
import unittest

from src.daily import build_daily, build_day_items, by_month, daily_totals


def commit(date="2026-09-02", added=10, removed=2, files=3, repo="api",
           attributed=False, time="10:00", hash="abc1234", category="feature",
           subject="feat: x"):
    return {"date": date, "time": time, "hash": hash, "repo": repo,
            "category": category, "subject": subject,
            "lines_added": added, "lines_removed": removed, "files_changed": files,
            "codex_attributed": attributed}


DAYS = ["2026-09-01", "2026-09-02", "2026-09-03"]


class TestBuildDaily(unittest.TestCase):
    def test_every_day_of_the_period_gets_a_row_including_idle_ones(self):
        # A table that lists only busy days reads as if the month were busier.
        rows = build_daily([commit()], {}, DAYS)
        self.assertEqual([r["date"] for r in rows], DAYS)
        self.assertFalse(rows[0]["active"])
        self.assertTrue(rows[1]["active"])

    def test_sums_commits_lines_and_file_changes_per_day(self):
        rows = build_daily([commit(added=10, removed=2, files=3),
                            commit(added=5, removed=1, files=2)], {}, DAYS)
        row = rows[1]
        self.assertEqual((row["commits"], row["added"], row["removed"],
                          row["files"], row["net"]), (2, 15, 3, 5, 12))

    def test_lists_the_repositories_touched_that_day(self):
        rows = build_daily([commit(repo="api"), commit(repo="web")], {}, DAYS)
        self.assertEqual(rows[1]["repos"], ["api", "web"])

    def test_codex_columns_come_from_the_activity_rows(self):
        rows = build_daily([], {"2026-09-02": {"tasks": 2, "turns": 5,
                                               "runtime_seconds": 3600}}, DAYS)
        self.assertEqual((rows[1]["tasks"], rows[1]["turns"],
                          rows[1]["runtime_seconds"]), (2, 5, 3600))

    def test_a_day_with_turns_and_no_commits_is_active(self):
        # Review and investigation produce turns and no commits; that is still work.
        rows = build_daily([], {"2026-09-03": {"tasks": 1, "turns": 3,
                                               "runtime_seconds": 60}}, DAYS)
        self.assertTrue(rows[2]["active"])
        self.assertEqual(rows[2]["commits"], 0)

    def test_activity_outside_the_period_still_gets_a_row(self):
        # A mismatch between the period and the data must never hide a commit.
        rows = build_daily([commit(date="2026-10-05")], {}, DAYS)
        self.assertEqual([r["date"] for r in rows], DAYS + ["2026-10-05"])

    def test_counts_codex_attributed_commits_per_day(self):
        rows = build_daily([commit(attributed=True), commit()], {}, DAYS)
        self.assertEqual(rows[1]["codex_attributed"], 1)

    def test_no_period_lists_only_the_days_that_carry_activity(self):
        rows = build_daily([commit(date="2026-09-02")], {}, [])
        self.assertEqual([r["date"] for r in rows], ["2026-09-02"])

    def test_rows_come_back_in_date_order(self):
        rows = build_daily([commit(date="2026-09-09"), commit(date="2026-09-04")],
                           {}, [])
        self.assertEqual([r["date"] for r in rows], ["2026-09-04", "2026-09-09"])


class TestDailyTotals(unittest.TestCase):
    def test_reports_the_three_active_day_counts_separately(self):
        rows = build_daily([commit(date="2026-09-02")],
                           {"2026-09-03": {"tasks": 1, "turns": 2,
                                           "runtime_seconds": 60}}, DAYS)
        totals = daily_totals(rows)
        self.assertEqual(totals["commit_days"], 1)
        self.assertEqual(totals["codex_days"], 1)
        self.assertEqual(totals["active_days"], 2)
        self.assertEqual(totals["days_listed"], 3)

    def test_sums_every_numeric_column(self):
        rows = build_daily([commit(added=10, removed=2, files=3),
                            commit(date="2026-09-03", added=1, removed=0, files=1)],
                           {}, DAYS)
        totals = daily_totals(rows)
        self.assertEqual((totals["commits"], totals["added"], totals["removed"],
                          totals["net"], totals["files"]), (2, 11, 2, 9, 4))

    def test_empty_input_is_all_zeros(self):
        self.assertEqual(daily_totals([])["commits"], 0)


class TestByMonth(unittest.TestCase):
    def test_rolls_days_up_into_calendar_months(self):
        rows = build_daily([commit(date="2026-08-31"), commit(date="2026-09-02")],
                           {}, [])
        months = by_month(rows)
        self.assertEqual(sorted(months), ["2026-08", "2026-09"])
        self.assertEqual(months["2026-08"]["commits"], 1)

    def test_counts_commit_days_and_codex_days_per_month(self):
        rows = build_daily([commit(date="2026-09-02"), commit(date="2026-09-02")],
                           {"2026-09-03": {"tasks": 1, "turns": 1,
                                           "runtime_seconds": 60}}, DAYS)
        month = by_month(rows)["2026-09"]
        self.assertEqual(month["commit_days"], 1)
        self.assertEqual(month["codex_days"], 1)

    def test_carries_a_net_figure(self):
        rows = build_daily([commit(added=10, removed=2)], {}, [])
        self.assertEqual(by_month(rows)["2026-09"]["net"], 8)


class TestBuildDayItems(unittest.TestCase):
    def test_groups_commits_by_day_oldest_first(self):
        items = build_day_items([commit(time="17:00", hash="b"),
                                 commit(time="09:00", hash="a")])
        self.assertEqual([i["time"] for i in items["2026-09-02"]], ["09:00", "17:00"])

    def test_carries_what_the_modal_renders_and_nothing_else(self):
        items = build_day_items([commit(attributed=True)])
        self.assertEqual(set(items["2026-09-02"][0]),
                         {"hash", "time", "repo", "category", "subject", "added",
                          "removed", "codex"})

    def test_the_hash_is_shortened_for_display(self):
        items = build_day_items([commit(hash="abcdef1234567")])
        self.assertEqual(items["2026-09-02"][0]["hash"], "abcdef1")

    def test_no_commits_yields_no_days(self):
        self.assertEqual(build_day_items([]), {})
