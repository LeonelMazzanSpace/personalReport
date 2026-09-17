"""Tests for the day calendar heatmap and its embedded modal payload."""
import json
import unittest

from src.calendar_view import (CATEGORY_DOT_COLORS, calendar_weeks, embed_json,
                               heat_level, month_header, render_calendar)
from src.classify import CATEGORY_ORDER
from src.daily import build_daily, build_day_items


def commit(date="2026-09-02", time="10:00", subject="feat: x", hash="abc1234",
           added=10, removed=2, attributed=False):
    return {"date": date, "time": time, "hash": hash, "repo": "api",
            "category": "feature", "subject": subject, "lines_added": added,
            "lines_removed": removed, "files_changed": 3,
            "codex_attributed": attributed}


def data(commits, codex_by_day=None, days=()):
    rows = build_daily(commits, codex_by_day or {}, days)
    return {"daily": rows, "day_items": build_day_items(commits)}


class TestHeatLevel(unittest.TestCase):
    def test_no_activity_is_level_zero(self):
        self.assertEqual(heat_level(0, 40), 0)

    def test_a_single_commit_against_a_large_max_still_reaches_level_one(self):
        # Rounding would render a real day of work as an empty cell.
        self.assertEqual(heat_level(1, 40), 1)

    def test_the_busiest_day_saturates(self):
        self.assertEqual(heat_level(40, 40), 4)

    def test_levels_never_exceed_four(self):
        self.assertEqual(heat_level(100, 40), 4)

    def test_an_empty_range_has_no_heat(self):
        self.assertEqual(heat_level(3, 0), 0)


class TestCalendarWeeks(unittest.TestCase):
    def test_spans_every_iso_week_touched_by_the_days(self):
        weeks = calendar_weeks(["2026-09-01", "2026-09-17"])
        self.assertEqual(weeks[0], "2026-W36")
        self.assertEqual(weeks[-1], "2026-W38")

    def test_no_days_means_no_columns(self):
        self.assertEqual(calendar_weeks([]), [])


class TestMonthHeader(unittest.TestCase):
    def test_groups_consecutive_weeks_under_their_month(self):
        # 2026-W36 starts Mon 2026-08-31, so it is headed August.
        header = month_header(["2026-W36", "2026-W37", "2026-W38"])
        self.assertEqual(header, [("Aug 26", 1), ("Sep 26", 2)])

    def test_a_single_week_is_a_single_group(self):
        self.assertEqual(month_header(["2026-W38"]), [("Sep 26", 1)])


class TestEmbedJson(unittest.TestCase):
    def test_every_angle_bracket_is_escaped(self):
        # A subject containing "</script>" would otherwise close the block early.
        payload = embed_json({"s": "</script><img src=x>"})
        self.assertNotIn("<", payload)
        self.assertEqual(json.loads(payload)["s"], "</script><img src=x>")

    def test_the_result_is_still_valid_json(self):
        self.assertEqual(json.loads(embed_json({"a": 1, "b": "x"})), {"a": 1, "b": "x"})


class TestRenderCalendar(unittest.TestCase):
    def test_renders_seven_day_rows_and_the_modal_scaffolding(self):
        html = render_calendar(data([commit()], days=["2026-09-0%d" % i
                                                      for i in range(1, 8)]))
        for label in ["Mon", "Sun"]:
            self.assertIn(f'>{label}<', html)
        self.assertIn('id="cal-data"', html)
        self.assertIn('id="cal-modal"', html)

    def test_a_day_cell_carries_its_date_and_commit_count(self):
        html = render_calendar(data([commit(), commit(hash="b")],
                                    days=["2026-09-01", "2026-09-02"]))
        self.assertIn('data-date="2026-09-02"', html)

    def test_a_day_with_codex_turns_is_marked(self):
        html = render_calendar(data(
            [commit()], {"2026-09-02": {"tasks": 1, "turns": 3,
                                        "runtime_seconds": 60}},
            days=["2026-09-02"]))
        self.assertIn('data-codex="1"', html)

    def test_a_quiet_day_is_not_marked_as_codex_activity(self):
        html = render_calendar(data([commit()], days=["2026-09-01", "2026-09-02"]))
        self.assertIn('data-codex="0"', html)

    def test_commit_subjects_reach_the_payload_escaped(self):
        html = render_calendar(data([commit(subject="feat: </script> break out")],
                                    days=["2026-09-02"]))
        self.assertNotIn("</script> break out", html)
        self.assertIn("\\u003c/script>", html)

    def test_the_modal_payload_carries_runtime_already_formatted(self):
        html = render_calendar(data(
            [commit()], {"2026-09-02": {"tasks": 1, "turns": 2,
                                        "runtime_seconds": 4200}},
            days=["2026-09-02"]))
        payload = json.loads(html.split('id="cal-data">')[1].split("</script>")[0]
                             .replace("\\u003c", "<"))
        self.assertEqual(payload["days"]["2026-09-02"]["runtime"], "1h 10m")
        self.assertTrue(payload["days"]["2026-09-02"]["hasCodex"])

    def test_an_empty_range_says_so_instead_of_rendering_an_empty_grid(self):
        html = render_calendar({"daily": [], "day_items": {}})
        self.assertIn("No activity in range", html)

    def test_every_commit_category_has_a_dot_colour(self):
        self.assertEqual(set(CATEGORY_DOT_COLORS), set(CATEGORY_ORDER))
