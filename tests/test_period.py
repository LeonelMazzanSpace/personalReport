"""Tests for the reporting period — the thing every other figure is clipped to."""
import unittest
from datetime import date

from src.period import PeriodError, in_period, month_period, parse_month, period_days


class TestParseMonth(unittest.TestCase):
    def test_splits_a_well_formed_month(self):
        self.assertEqual(parse_month("2026-09"), (2026, 9))

    def test_rejects_a_missing_zero_pad(self):
        with self.assertRaises(PeriodError):
            parse_month("2026-9")

    def test_rejects_a_full_date(self):
        with self.assertRaises(PeriodError):
            parse_month("2026-09-17")

    def test_rejects_a_month_outside_one_to_twelve(self):
        with self.assertRaises(PeriodError):
            parse_month("2026-13")

    def test_rejects_prose(self):
        with self.assertRaises(PeriodError):
            parse_month("september")


class TestMonthPeriod(unittest.TestCase):
    def test_a_finished_month_runs_to_its_last_day(self):
        p = month_period("2024-03", today=date(2026, 9, 17))
        self.assertEqual((p["start"], p["end"]), ("2024-03-01", "2024-03-31"))
        self.assertFalse(p["month_to_date"])
        self.assertEqual(p["label"], "March 2024")

    def test_a_running_month_is_clipped_to_today_and_flagged(self):
        p = month_period("2026-09", today=date(2026, 9, 17))
        self.assertEqual((p["start"], p["end"]), ("2026-09-01", "2026-09-17"))
        self.assertTrue(p["month_to_date"])
        # full_end still names the calendar month's real last day, so the report
        # can say what it is NOT covering.
        self.assertEqual(p["full_end"], "2026-09-30")

    def test_the_last_day_of_a_running_month_is_not_month_to_date(self):
        p = month_period("2026-09", today=date(2026, 9, 30))
        self.assertFalse(p["month_to_date"])
        self.assertEqual(p["end"], "2026-09-30")

    def test_february_in_a_leap_year(self):
        p = month_period("2024-02", today=date(2026, 9, 17))
        self.assertEqual(p["end"], "2024-02-29")

    def test_a_future_month_is_an_error_not_an_empty_report(self):
        # An empty report reads as "no work happened"; a typo must not say that.
        with self.assertRaises(PeriodError):
            month_period("2027-01", today=date(2026, 9, 17))


class TestInPeriod(unittest.TestCase):
    def setUp(self):
        self.period = month_period("2026-09", today=date(2026, 9, 17))

    def test_both_endpoints_are_inclusive(self):
        self.assertTrue(in_period("2026-09-01", self.period))
        self.assertTrue(in_period("2026-09-17", self.period))

    def test_outside_the_window_is_excluded(self):
        self.assertFalse(in_period("2026-08-31", self.period))
        self.assertFalse(in_period("2026-09-18", self.period))

    def test_no_period_means_no_filter(self):
        self.assertTrue(in_period("1999-01-01", None))


class TestPeriodDays(unittest.TestCase):
    def test_lists_every_day_including_idle_ones(self):
        days = period_days(month_period("2026-09", today=date(2026, 9, 17)))
        self.assertEqual(len(days), 17)
        self.assertEqual((days[0], days[-1]), ("2026-09-01", "2026-09-17"))

    def test_no_period_lists_nothing(self):
        self.assertEqual(period_days(None), [])
