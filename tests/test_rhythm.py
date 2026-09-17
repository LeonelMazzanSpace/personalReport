import unittest

from src.rhythm import build_rhythm


def commit(dow=0, hour=10, added=10, removed=1):
    return {
        "repo": "webapp", "email": "a@x.com",
        "hash": "h", "date": "2026-07-30", "time": f"{hour:02d}:00",
        "month": "2026-07", "dow": dow, "hour": hour,
        "subject": "feat: x", "lines_added": added, "lines_removed": removed,
        "raw_added": added, "raw_removed": removed, "files_changed": 1, "files": [],
        "type": "feat", "scope": None, "is_conventional": True,
        "category": "feature", "is_refactor": False,
    }


class TestBuildRhythm(unittest.TestCase):
    def test_dow_has_seven_labelled_buckets(self):
        r = build_rhythm([commit(dow=0), commit(dow=0), commit(dow=3)])
        self.assertEqual(len(r["dow"]), 7)
        self.assertEqual([d["label"] for d in r["dow"]],
                         ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
        self.assertEqual(r["dow"][0]["commits"], 2)
        self.assertEqual(r["dow"][3]["commits"], 1)
        self.assertEqual(r["dow"][5]["commits"], 0)

    def test_dow_sums_lines(self):
        r = build_rhythm([commit(dow=0, added=10, removed=1), commit(dow=0, added=5, removed=2)])
        self.assertEqual(r["dow"][0]["added"], 15)
        self.assertEqual(r["dow"][0]["removed"], 3)

    def test_hours_has_twentyfour_buckets(self):
        r = build_rhythm([commit(hour=15), commit(hour=15), commit(hour=3)])
        self.assertEqual(len(r["hours"]), 24)
        self.assertEqual(r["hours"][15]["commits"], 2)
        self.assertEqual(r["hours"][3]["commits"], 1)
        self.assertEqual(r["hours"][9]["commits"], 0)


    def test_identifies_peaks(self):
        r = build_rhythm([commit(dow=1, hour=15), commit(dow=1, hour=15), commit(dow=4, hour=9)])
        self.assertEqual(r["peak_dow"], "Tue")
        self.assertEqual(r["peak_hour"], 15)

    def test_counts_weekend_and_off_hours(self):
        r = build_rhythm([
            commit(dow=5, hour=12),   # Saturday, in hours
            commit(dow=6, hour=23),   # Sunday, off hours
            commit(dow=1, hour=3),    # Tuesday, off hours
            commit(dow=1, hour=10),   # Tuesday, in hours
        ])
        self.assertEqual(r["weekend_commits"], 2)
        self.assertEqual(r["off_hours_commits"], 2)

    def test_off_hours_boundary_hours(self):
        r = build_rhythm([
            commit(dow=1, hour=7),    # 07:xx is OFF-hours
            commit(dow=1, hour=8),    # 08:xx is IN-hours
            commit(dow=1, hour=19),   # 19:xx is IN-hours
            commit(dow=1, hour=20),   # 20:xx is OFF-hours
        ])
        self.assertEqual(r["off_hours_commits"], 2)

    def test_empty_input_is_safe(self):
        r = build_rhythm([])
        self.assertEqual(sum(d["commits"] for d in r["dow"]), 0)
        self.assertIsNone(r["peak_dow"])
        self.assertIsNone(r["peak_hour"])


class TestWebappRhythmEdges(unittest.TestCase):
    def test_hour_boundaries_of_the_off_hours_window(self):
        # 08:00 is inside the working window; 20:00 is outside. An off-by-one here
        # would silently move hundreds of commits between buckets.
        from src.rhythm import WORK_END_HOUR, WORK_START_HOUR
        self.assertEqual((WORK_START_HOUR, WORK_END_HOUR), (8, 20))
        rows = [commit(hour=h) for h in (7, 8, 19, 20)]
        self.assertEqual(build_rhythm(rows)["off_hours_commits"], 2)

    def test_saturday_and_sunday_count_as_weekend(self):
        rows = [commit(dow=4), commit(dow=5), commit(dow=6)]
        self.assertEqual(build_rhythm(rows)["weekend_commits"], 2)
