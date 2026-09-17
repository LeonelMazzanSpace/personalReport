import unittest

from src.duplicates import duplicate_stats, parse_patch_ids


class TestParsePatchIds(unittest.TestCase):
    def test_maps_sha_to_patch_id(self):
        output = "abc123 sha1111\ndef456 sha2222\n"
        self.assertEqual(parse_patch_ids(output), {
            "sha1111": "abc123", "sha2222": "def456",
        })

    def test_ignores_blank_lines(self):
        output = "abc123 sha1111\n\n\ndef456 sha2222\n"
        self.assertEqual(len(parse_patch_ids(output)), 2)

    def test_a_commit_with_an_empty_diff_emits_no_line_and_is_simply_absent(self):
        # git patch-id prints nothing for a commit with no diff content — it is
        # not present with an empty patch-id, it is not present at all.
        output = "abc123 sha1111\n"
        result = parse_patch_ids(output)
        self.assertEqual(len(result), 1)
        self.assertNotIn("sha_with_no_diff", result)

    def test_empty_output_yields_an_empty_mapping(self):
        self.assertEqual(parse_patch_ids(""), {})

    def test_malformed_lines_are_skipped_not_fatal(self):
        output = "abc123 sha1111\nnot-two-fields\nabc123 def456 sha3333\n"
        self.assertEqual(parse_patch_ids(output), {"sha1111": "abc123"})


class TestDuplicateStats(unittest.TestCase):
    def test_no_duplicates_when_every_patch_id_is_distinct(self):
        stats = duplicate_stats({"s1": "p1", "s2": "p2", "s3": "p3"})
        self.assertEqual(stats, {"redundant": 0, "groups": 0, "unique": 3})

    def test_counts_every_extra_commit_in_a_duplicate_group_as_redundant(self):
        # Three commits share patch-id p1: the first is the "original", the
        # other two are redundant copies.
        stats = duplicate_stats({"s1": "p1", "s2": "p1", "s3": "p1"})
        self.assertEqual(stats["redundant"], 2)
        self.assertEqual(stats["unique"], 1)
        self.assertEqual(stats["groups"], 1)

    def test_groups_counts_duplicate_clusters_not_duplicate_commits(self):
        # Two separate pairs of duplicates: 2 groups, 2 redundant commits (one
        # per pair), 2 unique patch-ids overall.
        stats = duplicate_stats({
            "s1": "p1", "s2": "p1",
            "s3": "p2", "s4": "p2",
        })
        self.assertEqual(stats, {"redundant": 2, "groups": 2, "unique": 2})

    def test_mixes_duplicated_and_singleton_patch_ids(self):
        stats = duplicate_stats({
            "s1": "p1", "s2": "p1", "s3": "p1",   # group of 3 -> 2 redundant
            "s4": "p2",                             # singleton
            "s5": "p3", "s6": "p3",                # group of 2 -> 1 redundant
        })
        self.assertEqual(stats, {"redundant": 3, "groups": 2, "unique": 3})

    def test_empty_mapping_yields_zeroed_stats(self):
        self.assertEqual(duplicate_stats({}),
                         {"redundant": 0, "groups": 0, "unique": 0})
