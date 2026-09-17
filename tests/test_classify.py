import unittest
from dataclasses import dataclass

from src.classify import (CATEGORY_LABELS, CATEGORY_ORDER, TYPE_TO_CATEGORY,
                          classify, parse_subject)


@dataclass
class FakeCommit:
    subject: str


class TestParseSubject(unittest.TestCase):
    def test_plain_type(self):
        self.assertEqual(parse_subject("feat: add coin list"),
                         {"type": "feat", "scope": None, "is_conventional": True})

    def test_type_with_scope(self):
        self.assertEqual(parse_subject("fix(Backend): null guard"),
                         {"type": "fix", "scope": "backend", "is_conventional": True})

    def test_breaking_change_bang(self):
        self.assertEqual(parse_subject("feat!: drop v1 api")["type"], "feat")

    def test_uppercase_type_is_normalised(self):
        self.assertEqual(parse_subject("FEAT: x")["type"], "feat")

    def test_prose_with_a_colon_is_not_conventional(self):
        self.assertEqual(parse_subject("Merge branch dev: conflicts"),
                         {"type": None, "scope": None, "is_conventional": False})

    def test_no_colon_is_not_conventional(self):
        self.assertEqual(parse_subject("update readme")["is_conventional"], False)

    def test_word_not_in_the_table_is_not_conventional(self):
        # Typos and prose prefixes: efactor, ix, fesat, parallel, update.
        for subject in ("efactor: dedupe", "ix: bug", "fesat: thing",
                        "parallel: runs", "subject: x"):
            with self.subTest(subject=subject):
                self.assertEqual(parse_subject(subject)["is_conventional"], False)

    def test_empty_description_is_not_conventional(self):
        self.assertEqual(parse_subject("feat:")["is_conventional"], False)


class TestTypeTable(unittest.TestCase):
    def test_revert_has_its_own_category_not_other(self):
        # 11 real revert commits. Mapping them to `other` would render them under
        # the label "No convention" despite being valid conventional commits.
        self.assertEqual(TYPE_TO_CATEGORY["revert"], "revert")
        self.assertEqual(classify(FakeCommit("revert: undo pnl change"))["category"],
                         "revert")
        self.assertTrue(classify(FakeCommit("revert: undo"))["is_conventional"])

    def test_wip_and_debug_and_spike_land_in_wip(self):
        for ctype in ("wip", "debug", "spike"):
            with self.subTest(ctype=ctype):
                self.assertEqual(TYPE_TO_CATEGORY[ctype], "wip")

    def test_hotfix_counts_as_a_fix(self):
        self.assertEqual(classify(FakeCommit("hotfix: prod down"))["category"], "fix")

    def test_chore_perf_style_build_ci_count_as_refactor(self):
        for ctype in ("chore", "perf", "style", "build", "ci"):
            with self.subTest(ctype=ctype):
                self.assertEqual(TYPE_TO_CATEGORY[ctype], "refactor")

    def test_only_refactor_itself_sets_is_refactor(self):
        self.assertTrue(classify(FakeCommit("refactor: split service"))["is_refactor"])
        self.assertFalse(classify(FakeCommit("chore: bump dep"))["is_refactor"])


class TestClassify(unittest.TestCase):
    def test_unconventional_subject_falls_into_other(self):
        result = classify(FakeCommit("just some work"))
        self.assertEqual(result["category"], "other")
        self.assertIsNone(result["type"])
        self.assertFalse(result["is_conventional"])

    def test_scope_is_carried_through_lowercased(self):
        self.assertEqual(classify(FakeCommit("feat(PnL): x"))["scope"], "pnl")


class TestCategoryMetadata(unittest.TestCase):
    def test_every_category_in_the_table_is_ordered_and_labelled(self):
        categories = set(TYPE_TO_CATEGORY.values()) | {"other"}
        self.assertEqual(categories, set(CATEGORY_ORDER))
        self.assertEqual(categories, set(CATEGORY_LABELS))

    def test_other_is_last_so_the_stacked_bar_ends_with_the_unlabelled_bucket(self):
        self.assertEqual(CATEGORY_ORDER[-1], "other")

    def test_labels_are_spanish(self):
        self.assertEqual(CATEGORY_LABELS["revert"], "Reverts")
        self.assertEqual(CATEGORY_LABELS["wip"], "WIP / debug")
        self.assertEqual(CATEGORY_LABELS["other"], "No convention")
