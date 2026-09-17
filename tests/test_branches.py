import unittest

from src.branches import FIELD_SEP, count_by_tip, mine, parse_branch_lines


def line(ref, sha="a" * 40, date="2026-09-03", email="<me@work.example>",
         subject="feat: x"):
    return (f"{ref}{FIELD_SEP}{sha}{FIELD_SEP}{date}{FIELD_SEP}{email}"
            f"{FIELD_SEP}{subject}")


class TestParseBranchLines(unittest.TestCase):
    def test_strips_the_local_prefix(self):
        rows = parse_branch_lines([line("refs/heads/dev")], "webapp")
        self.assertEqual(rows[0]["name"], "dev")
        self.assertFalse(rows[0]["is_remote"])
        self.assertEqual(rows[0]["repo"], "webapp")

    def test_strips_the_remote_prefix_and_keeps_the_remote_name(self):
        rows = parse_branch_lines([line("refs/remotes/origin/dev")], "webapp")
        self.assertEqual(rows[0]["name"], "origin/dev")
        self.assertTrue(rows[0]["is_remote"])

    def test_drops_the_symbolic_head_ref(self):
        self.assertEqual(parse_branch_lines([line("refs/remotes/origin/HEAD")],
                                            "webapp"), [])

    def test_ignores_tags_and_other_ref_namespaces(self):
        self.assertEqual(parse_branch_lines([line("refs/tags/v1.0")], "webapp"), [])

    def test_ignores_blank_and_malformed_lines(self):
        self.assertEqual(parse_branch_lines(["", "   ", "refs/heads/dev"], "webapp"), [])

    def test_carries_the_tip_sha_date_and_subject(self):
        rows = parse_branch_lines(
            [line("refs/heads/dev", sha="b" * 40, date="2026-08-01",
                  subject="fix: guard")], "webapp")
        self.assertEqual(rows[0]["tip_sha"], "b" * 40)
        self.assertEqual(rows[0]["tip_date"], "2026-08-01")
        self.assertEqual(rows[0]["tip_subject"], "fix: guard")

    def test_tip_email_is_unwrapped_and_lowercased(self):
        rows = parse_branch_lines(
            [line("refs/heads/dev", email="<Me@Work.Example>")], "webapp")
        self.assertEqual(rows[0]["tip_email"], "me@work.example")

    def test_a_separator_inside_the_subject_stays_in_the_subject(self):
        rows = parse_branch_lines(
            [line("refs/heads/dev", subject=f"feat: a{FIELD_SEP}b")], "webapp")
        self.assertEqual(rows[0]["tip_subject"], f"feat: a{FIELD_SEP}b")

    def test_branch_name_with_slashes_survives(self):
        rows = parse_branch_lines([line("refs/heads/feat/coin_detail_chart")],
                                  "webapp")
        self.assertEqual(rows[0]["name"], "feat/coin_detail_chart")


class TestCountByTip(unittest.TestCase):
    """One rev-list per distinct tip SHA, not per ref. 829 refs, far fewer tips."""

    def test_fans_one_count_out_to_every_ref_sharing_the_tip(self):
        rows = [
            {"name": "dev", "tip_sha": "aaa", "commits": 0},
            {"name": "origin/dev", "tip_sha": "aaa", "commits": 0},
            {"name": "main", "tip_sha": "bbb", "commits": 0},
        ]
        calls = []

        def fake_count(sha):
            calls.append(sha)
            return {"aaa": 5481, "bbb": 4000}[sha]

        count_by_tip(rows, fake_count)
        self.assertEqual(sorted(calls), ["aaa", "bbb"])       # 2 calls, not 3
        self.assertEqual([r["commits"] for r in rows], [5481, 5481, 4000])

    def test_no_refs_means_no_calls(self):
        calls = []
        count_by_tip([], lambda sha: calls.append(sha) or 0)
        self.assertEqual(calls, [])


class TestMine(unittest.TestCase):
    """Branch attribution is by TIP author only — see the note in branches.mine."""

    def test_keeps_only_branches_whose_tip_is_one_of_the_emails(self):
        rows = parse_branch_lines([
            line("refs/heads/feature/x", email="<me@work.example>"),
            line("refs/heads/other", email="<someone@else.com>"),
        ], "webapp")
        self.assertEqual([r["name"] for r in mine(rows, ["me@work.example"])],
                         ["feature/x"])

    def test_matching_ignores_case_on_both_sides(self):
        rows = parse_branch_lines([line("refs/heads/dev", email="<ME@Work.example>")],
                                  "webapp")
        self.assertEqual(len(mine(rows, ["me@WORK.EXAMPLE"])), 1)

    def test_no_emails_matches_nothing(self):
        rows = parse_branch_lines([line("refs/heads/dev")], "webapp")
        self.assertEqual(mine(rows, []), [])
