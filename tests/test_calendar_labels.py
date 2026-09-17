import unittest

from src.calendar_labels import (DOW_LABELS, MONTH_ABBR, iso_week_key, month_key,
                                 month_label, month_name, month_range,
                                 week_bounds, week_range)


class TestLabels(unittest.TestCase):
    def test_dow_labels_start_on_monday(self):
        self.assertEqual(DOW_LABELS,
                         ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])

    def test_month_abbr_has_twelve_entries_starting_january(self):
        self.assertEqual(len(MONTH_ABBR), 12)
        self.assertEqual(MONTH_ABBR[0], "Jan")
        self.assertEqual(MONTH_ABBR[11], "Dec")


class TestMonthKey(unittest.TestCase):
    def test_takes_the_calendar_month_of_the_date(self):
        self.assertEqual(month_key("2026-08-04"), "2026-08")

    def test_a_sunday_belongs_to_its_own_calendar_month(self):
        # 2026-08-02 is the Sunday of ISO week 2026-W31, whose Monday is in July.
        # The month grid must file it under August. See design decision D3.
        self.assertEqual(month_key("2026-08-02"), "2026-08")


class TestMonthRange(unittest.TestCase):
    def test_includes_every_month_between_the_endpoints(self):
        self.assertEqual(month_range("2025-11", "2026-02"),
                         ["2025-11", "2025-12", "2026-01", "2026-02"])

    def test_single_month_range(self):
        self.assertEqual(month_range("2026-05", "2026-05"), ["2026-05"])

    def test_spans_the_full_history(self):
        keys = month_range("2025-08", "2026-09")
        self.assertEqual(len(keys), 14)
        self.assertEqual(keys[0], "2025-08")
        self.assertEqual(keys[-1], "2026-09")

    def test_empty_when_an_endpoint_is_missing(self):
        self.assertEqual(month_range(None, "2026-05"), [])
        self.assertEqual(month_range("2026-05", None), [])


class TestMonthLabel(unittest.TestCase):
    def test_renders_abbreviated_month_and_two_digit_year(self):
        self.assertEqual(month_label("2026-08"), "Aug 26")

    def test_january(self):
        self.assertEqual(month_label("2026-01"), "Jan 26")


class TestMonthName(unittest.TestCase):
    def test_spells_the_month_out_for_headings(self):
        self.assertEqual(month_name("2026-08"), "August 2026")


class TestIsoWeekHelpers(unittest.TestCase):
    def test_week_key_from_a_string_or_a_date(self):
        from datetime import date
        self.assertEqual(iso_week_key("2026-09-17"), "2026-W38")
        self.assertEqual(iso_week_key(date(2026, 9, 17)), "2026-W38")

    def test_week_bounds_run_monday_to_sunday(self):
        self.assertEqual(week_bounds("2026-W38"), ("2026-09-14", "2026-09-20"))

    def test_week_range_includes_idle_weeks_between_the_endpoints(self):
        self.assertEqual(week_range("2026-W36", "2026-W38"),
                         ["2026-W36", "2026-W37", "2026-W38"])

    def test_week_range_crosses_a_year_boundary(self):
        keys = week_range("2025-W52", "2026-W02")
        self.assertEqual(keys[0], "2025-W52")
        self.assertEqual(keys[-1], "2026-W02")

    def test_week_range_is_empty_when_an_endpoint_is_missing(self):
        self.assertEqual(week_range(None, "2026-W38"), [])
