import unittest

from src.format import fmt_duration, fmt_hours, fmt_int, fmt_signed, short_num


class TestFmtInt(unittest.TestCase):
    def test_inserts_comma_as_thousands_separator(self):
        self.assertEqual(fmt_int(50689), "50,689")

    def test_leaves_small_numbers_alone(self):
        self.assertEqual(fmt_int(7), "7")

    def test_handles_millions(self):
        self.assertEqual(fmt_int(1234567), "1,234,567")

    def test_handles_zero(self):
        self.assertEqual(fmt_int(0), "0")


class TestFmtSigned(unittest.TestCase):
    def test_positive_carries_an_explicit_plus(self):
        self.assertEqual(fmt_signed(1232), "+1,232")

    def test_negative_keeps_its_minus(self):
        self.assertEqual(fmt_signed(-30), "-30")

    def test_zero_is_unsigned(self):
        self.assertEqual(fmt_signed(0), "0")


class TestShortNum(unittest.TestCase):
    def test_zero_renders_empty_so_dense_cells_stay_readable(self):
        self.assertEqual(short_num(0), "")

    def test_under_a_thousand_is_verbatim(self):
        self.assertEqual(short_num(999), "999")

    def test_thousands_use_a_point_decimal(self):
        self.assertEqual(short_num(1234), "1.2k")

    def test_ten_thousand_and_up_drops_the_decimal(self):
        self.assertEqual(short_num(12345), "12k")


class TestFmtDuration(unittest.TestCase):
    def test_zero_is_explicit_rather_than_blank(self):
        self.assertEqual(fmt_duration(0), "0m")

    def test_none_is_treated_as_zero(self):
        self.assertEqual(fmt_duration(None), "0m")

    def test_under_a_minute_never_rounds_down_to_nothing(self):
        # A recorded turn that really happened must not render as "0m".
        self.assertEqual(fmt_duration(30), "<1m")

    def test_minutes_only_below_an_hour(self):
        self.assertEqual(fmt_duration(1800), "30m")

    def test_hours_pad_their_minutes(self):
        self.assertEqual(fmt_duration(4200), "1h 10m")
        self.assertEqual(fmt_duration(3660), "1h 01m")


class TestFmtHours(unittest.TestCase):
    def test_renders_one_decimal(self):
        self.assertEqual(fmt_hours(4200), "1.2")

    def test_none_is_zero(self):
        self.assertEqual(fmt_hours(None), "0.0")
