import unittest
from src.extract_commits import parse_log, MARKER, FIELD_SEP

class TestRhythmTimezone(unittest.TestCase):
    def parse(self, stamp):
        line = MARKER + FIELD_SEP.join(['abc', 'dev@example.test', 'Dev', stamp, 'fix: example'])
        return parse_log(line, 'repo', timezone_name='America/Montevideo',
                         timezone_changes=[{'from':'2026-09-13','timezone':'America/Los_Angeles'}])[0]

    def test_mixed_git_offset_converts_to_travel_timezone(self):
        c=self.parse('2026-09-15 21:00:55 -0400')
        self.assertEqual((c.date,c.hour,c.time),('2026-09-15',18,'18:00'))

    def test_midnight_conversion_updates_weekday_and_date(self):
        c=self.parse('2026-09-17 01:30:00 +0000')
        self.assertEqual((c.date,c.hour,c.dow),('2026-09-16',18,2))

    def test_before_travel_uses_uruguay(self):
        c=self.parse('2026-09-10 15:00:00 +0000')
        self.assertEqual(c.hour,12)
