import unittest
from datetime import datetime

from src.extract_commits import (BODY_SEP, FIELD_SEP, MARKER, Commit,
                                 is_excluded_path, iso_week_key,
                                 normalize_numstat_path, parse_bodies, parse_log)


def log_line(hash="abc1234", email="ediaz@work.example", name="Elena Diaz",
             stamp="2026-08-04 15:04:22", subject="feat: add coin list"):
    return (f"{MARKER}{hash}{FIELD_SEP}{email}{FIELD_SEP}{name}"
            f"{FIELD_SEP}{stamp}{FIELD_SEP}{subject}")


class TestIsExcludedPath(unittest.TestCase):
    def test_excludes_generated_and_binary_paths(self):
        for path in ("yarn.lock", "frontend/yarn.lock", "package-lock.json",
                     "pnpm-lock.yaml", "node_modules/react/index.js",
                     "backend/dist/app.js", "frontend/build/main.js",
                     "coverage/lcov.info", ".yarn/releases/yarn-4.0.cjs",
                     "frontend/src/assets/logo.svg", "vendor/lib.min.js",
                     "frontend/dist/main.js.map", "frontend/public/favicon.ico"):
            with self.subTest(path=path):
                self.assertTrue(is_excluded_path(path))

    def test_keeps_real_source_paths(self):
        for path in ("frontend/src/modules/coins/CoinList.tsx",
                     "backend/src/services/pnl.ts",
                     "shared/providers/mobula.ts",
                     "azure-pipelines.yml",
                     "2 - Development/main.bicep",
                     "docs/README.md"):
            with self.subTest(path=path):
                self.assertFalse(is_excluded_path(path))

    def test_a_file_merely_named_dist_is_not_excluded(self):
        # The patterns anchor on a path separator, so `dist` must be a directory.
        self.assertFalse(is_excluded_path("backend/src/dist.ts"))


class TestNormalizeNumstatPath(unittest.TestCase):
    def test_plain_path_is_untouched(self):
        self.assertEqual(normalize_numstat_path("backend/src/app.ts"),
                         "backend/src/app.ts")

    def test_simple_rename_keeps_the_new_path(self):
        self.assertEqual(normalize_numstat_path("old/a.ts => new/b.ts"), "new/b.ts")

    def test_braced_rename_is_reassembled(self):
        self.assertEqual(
            normalize_numstat_path("frontend/src/{old => new}/CoinList.tsx"),
            "frontend/src/new/CoinList.tsx",
        )

    def test_braced_rename_with_an_empty_side(self):
        self.assertEqual(normalize_numstat_path("shared/{ => utils}/fmt.ts"),
                         "shared/utils/fmt.ts")

    def test_locates_the_marker_brace_not_merely_the_first_one(self):
        # A literal brace in an unchanged prefix must not be mistaken for git's
        # rename marker. This is open bug #1 in the reference tool's FOLLOWUPS.
        self.assertEqual(
            normalize_numstat_path("config{env}/{a => b}.ts"),
            "config{env}/b.ts",
        )


class TestIsoWeekKey(unittest.TestCase):
    def test_pads_the_week_number(self):
        self.assertEqual(iso_week_key(datetime(2026, 1, 5)), "2026-W02")

    def test_late_december_can_belong_to_the_next_iso_year(self):
        self.assertEqual(iso_week_key(datetime(2025, 12, 29)), "2026-W01")


class TestParseLog(unittest.TestCase):
    def test_parses_a_single_commit_with_its_repo_label(self):
        output = "\n".join([log_line(), "12\t3\tbackend/src/app.ts", ""])
        commits = parse_log(output, "webapp")
        self.assertEqual(len(commits), 1)
        c = commits[0]
        self.assertEqual(c.repo, "webapp")
        self.assertEqual(c.hash, "abc1234")
        self.assertEqual(c.email, "ediaz@work.example")
        self.assertEqual(c.date, "2026-08-04")
        self.assertEqual(c.time, "15:04")
        self.assertEqual(c.iso_week, "2026-W32")
        self.assertEqual(c.month, "2026-08")
        self.assertEqual(c.dow, 1)        # Tuesday
        self.assertEqual(c.hour, 15)
        self.assertEqual(c.lines_added, 12)
        self.assertEqual(c.lines_removed, 3)
        self.assertEqual(c.files_changed, 1)

    def test_month_is_the_commit_date_not_its_week(self):
        # 2026-08-02 is a Sunday; its ISO week starts 2026-07-27.
        c = parse_log(log_line(stamp="2026-08-02 10:00:00"), "webapp")[0]
        self.assertEqual(c.iso_week, "2026-W31")
        self.assertEqual(c.month, "2026-08")

    def test_excluded_paths_count_only_toward_raw_totals(self):
        output = "\n".join([
            log_line(),
            "12\t3\tbackend/src/app.ts",
            "9000\t8000\tyarn.lock",
        ])
        c = parse_log(output, "webapp")[0]
        self.assertEqual((c.lines_added, c.lines_removed), (12, 3))
        self.assertEqual((c.raw_lines_added, c.raw_lines_removed), (9012, 8003))
        self.assertEqual(c.files_changed, 1)

    def test_binary_files_are_skipped_entirely(self):
        output = "\n".join([log_line(), "-\t-\tdocs/diagram.png"])
        c = parse_log(output, "webapp")[0]
        self.assertEqual(c.files, [])
        self.assertEqual((c.raw_lines_added, c.raw_lines_removed), (0, 0))

    def test_a_separator_inside_the_subject_stays_in_the_subject(self):
        c = parse_log(log_line(subject=f"feat: a{FIELD_SEP}b"), "webapp")[0]
        self.assertEqual(c.subject, f"feat: a{FIELD_SEP}b")

    def test_parses_several_commits_and_keeps_stats_separate(self):
        output = "\n".join([
            log_line(hash="aaa", stamp="2026-08-04 15:04:22"),
            "10\t1\tbackend/src/a.ts",
            "",
            log_line(hash="bbb", stamp="2026-08-05 09:00:00"),
            "5\t5\tfrontend/src/b.tsx",
            "7\t0\tshared/utils/c.ts",
        ])
        commits = parse_log(output, "infra")
        self.assertEqual([c.hash for c in commits], ["aaa", "bbb"])
        self.assertEqual(commits[1].files_changed, 2)
        self.assertEqual(commits[1].lines_added, 12)
        self.assertTrue(all(c.repo == "infra" for c in commits))

    def test_empty_output_yields_no_commits(self):
        self.assertEqual(parse_log("", "webapp"), [])

    def test_numstat_lines_before_any_commit_are_ignored(self):
        self.assertEqual(parse_log("10\t2\ta.ts", "webapp"), [])

    def test_a_path_containing_spaces_survives(self):
        output = "\n".join([log_line(), "4\t0\t2 - Development/main.bicep"])
        c = parse_log(output, "infra")[0]
        self.assertEqual(c.files, [(4, 0, "2 - Development/main.bicep")])


class TestCommitProperties(unittest.TestCase):
    def test_line_counts_sum_the_kept_files(self):
        c = Commit(hash="a", repo="webapp", email="e", name="n", date="2026-08-04",
                   time="10:00", iso_week="2026-W32", month="2026-08", dow=1, hour=10,
                   subject="feat: x", files=[(3, 1, "a.ts"), (4, 2, "b.ts")])
        self.assertEqual((c.lines_added, c.lines_removed, c.files_changed), (7, 3, 2))

    def test_a_commit_with_no_kept_files_reports_zeroes(self):
        c = Commit(hash="a", repo="webapp", email="e", name="n", date="2026-08-04",
                   time="10:00", iso_week="2026-W32", month="2026-08", dow=1, hour=10,
                   subject="chore: bump", files=[], raw_added=500, raw_removed=400)
        self.assertEqual((c.lines_added, c.lines_removed, c.files_changed), (0, 0, 0))
        self.assertEqual((c.raw_lines_added, c.raw_lines_removed), (500, 400))


class TestExcludedFilesAreKept(unittest.TestCase):
    """Excluded paths stay out of the line totals but must remain visible.

    The report shows what the headline number leaves out; dropping these tuples
    on the floor would make that impossible (src/file_kinds.classify_lines).
    """

    def parse(self, *rows):
        header = MARKER + FIELD_SEP.join(
            ["abc", "a@b.c", "Ana", "2026-09-10 10:00:00", "feat: x"])
        return parse_log("\n".join([header, *rows]), "api")[0]

    def test_an_excluded_path_lands_in_excluded_files_not_files(self):
        commit = self.parse("5\t2\tsrc/a.ts", "900\t40\tyarn.lock")
        self.assertEqual(commit.files, [(5, 2, "src/a.ts")])
        self.assertEqual(commit.excluded_files, [(900, 40, "yarn.lock")])

    def test_the_line_totals_still_exclude_them(self):
        commit = self.parse("5\t2\tsrc/a.ts", "900\t40\tyarn.lock")
        self.assertEqual((commit.lines_added, commit.lines_removed), (5, 2))
        self.assertEqual((commit.raw_lines_added, commit.raw_lines_removed), (905, 42))

    def test_files_changed_counts_only_the_included_paths(self):
        commit = self.parse("5\t2\tsrc/a.ts", "900\t40\tyarn.lock")
        self.assertEqual(commit.files_changed, 1)

    def test_a_binary_file_lands_in_neither_list(self):
        # git reports "-" for binaries: no line counts exist to attribute.
        commit = self.parse("-\t-\tlogo.png", "5\t2\tsrc/a.ts")
        self.assertEqual(commit.excluded_files, [])
        self.assertEqual(commit.files, [(5, 2, "src/a.ts")])

    def test_a_commit_with_no_excluded_paths_has_an_empty_list(self):
        self.assertEqual(self.parse("5\t2\tsrc/a.ts").excluded_files, [])


class TestParseBodies(unittest.TestCase):
    """Commit bodies ride in their own pass: a body is multi-line by definition
    and cannot share the line-based numstat stream."""

    def test_reads_one_body_per_record(self):
        output = (f"abc{FIELD_SEP}line one\nline two{BODY_SEP}"
                  f"def{FIELD_SEP}other{BODY_SEP}")
        self.assertEqual(parse_bodies(output),
                         {"abc": "line one\nline two", "def": "other"})

    def test_a_trailer_survives_intact(self):
        output = (f"abc{FIELD_SEP}feat: x\n\nCo-authored-by: Codex <x@y>{BODY_SEP}")
        self.assertIn("Co-authored-by: Codex", parse_bodies(output)["abc"])

    def test_an_empty_body_is_simply_absent_or_empty(self):
        self.assertEqual(parse_bodies(f"abc{FIELD_SEP}{BODY_SEP}"), {"abc": ""})

    def test_blank_records_are_skipped(self):
        self.assertEqual(parse_bodies(f"{BODY_SEP}   {BODY_SEP}"), {})

    def test_empty_output_yields_no_bodies(self):
        self.assertEqual(parse_bodies(""), {})
