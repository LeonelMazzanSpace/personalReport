"""Tests for identity resolution — the question "whose commits is this?".

Getting this wrong is the worst failure the report has: it either claims someone
else's work or silently drops a month of your own.
"""
import unittest

from src.extract_commits import Commit
from src.me import (IdentityError, ambiguous_identities, filter_mine, is_mine,
                    resolve_identity)


def commit(email, name="Ana Perez", hash="a1", repo="api"):
    return Commit(hash=hash, repo=repo, email=email, name=name, date="2026-09-01",
                  time="10:00", iso_week="2026-W36", month="2026-09", dow=1,
                  hour=10, subject="feat: x")


def reader(values):
    """Stand in for `git config --get`, keyed by (repo path, key)."""
    return lambda path, key: values.get((path, key))


REPOS = [{"path": "api", "label": "api"}, {"path": "web", "label": "web"}]


class TestResolveIdentity(unittest.TestCase):
    def test_config_emails_win_and_are_reported_as_such(self):
        identity = resolve_identity(
            {"name": "Ana Perez", "emails": ["ana@work.example"]}, REPOS,
            read=reader({("api", "user.email"): "other@work.example"}))
        self.assertEqual(identity["emails"], ["ana@work.example"])
        self.assertEqual(identity["source"], "config")

    def test_falls_back_to_the_repos_own_git_config(self):
        identity = resolve_identity(None, REPOS, read=reader({
            ("api", "user.email"): "ana@work.example",
            ("api", "user.name"): "Ana Perez",
        }))
        self.assertEqual(identity["emails"], ["ana@work.example"])
        self.assertEqual(identity["name"], "Ana Perez")
        self.assertEqual(identity["source"], "git config")

    def test_two_repos_configured_differently_yield_both_identities(self):
        identity = resolve_identity(None, REPOS, read=reader({
            ("api", "user.email"): "ana@work.example",
            ("web", "user.email"): "ana@client.example",
        }))
        self.assertEqual(identity["emails"],
                         ["ana@client.example", "ana@work.example"])

    def test_emails_are_normalised_but_the_raw_form_is_kept_for_display(self):
        identity = resolve_identity({"emails": ["Ana@Work.Example"]}, REPOS,
                                    read=reader({}))
        self.assertEqual(identity["emails"], ["ana@work.example"])
        self.assertEqual(identity["display_emails"], ["Ana@Work.Example"])

    def test_no_config_and_no_git_config_is_a_hard_error(self):
        # Guessing here would attribute someone else's commits.
        with self.assertRaises(IdentityError) as ctx:
            resolve_identity(None, REPOS, read=reader({}))
        self.assertIn("me.emails", str(ctx.exception))

    def test_name_falls_back_to_the_first_email_when_git_has_none(self):
        identity = resolve_identity({"emails": ["ana@work.example"]}, REPOS,
                                    read=reader({}))
        self.assertEqual(identity["name"], "ana@work.example")


class TestIsMine(unittest.TestCase):
    def test_matching_ignores_case_and_surrounding_space(self):
        identity = {"emails": ["ana@work.example"], "name": "Ana"}
        self.assertTrue(is_mine("  Ana@Work.Example ", identity))
        self.assertFalse(is_mine("beto@work.example", identity))


class TestFilterMine(unittest.TestCase):
    def setUp(self):
        self.identity = {"emails": ["ana@work.example"], "name": "Ana Perez"}

    def test_keeps_only_my_commits(self):
        kept = filter_mine([commit("ana@work.example"),
                            commit("beto@work.example", hash="b1")], self.identity)
        self.assertEqual([c.hash for c in kept], ["a1"])

    def test_deduplicates_by_repo_and_full_sha(self):
        kept = filter_mine([commit("ana@work.example"),
                            commit("ana@work.example")], self.identity)
        self.assertEqual(len(kept), 1)

    def test_the_same_sha_in_two_repos_is_two_commits(self):
        # Distinct repositories are distinct work, even if a file was copied over.
        kept = filter_mine([commit("ana@work.example", repo="api"),
                            commit("ana@work.example", repo="web")], self.identity)
        self.assertEqual(len(kept), 2)

    def test_original_order_is_preserved(self):
        kept = filter_mine([commit("ana@work.example", hash="a1"),
                            commit("beto@x.com", hash="b1"),
                            commit("ana@work.example", hash="a2")], self.identity)
        self.assertEqual([c.hash for c in kept], ["a1", "a2"])


class TestAmbiguousIdentities(unittest.TestCase):
    def setUp(self):
        self.identity = {"emails": ["ana@work.example"], "name": "Ana Perez"}

    def test_flags_a_same_named_author_on_another_address(self):
        rows = ambiguous_identities([
            commit("ana@work.example"),
            commit("ana@personal.com", hash="b1"),
            commit("ana@personal.com", hash="b2"),
        ], self.identity)
        self.assertEqual(rows, [{"email": "ana@personal.com", "name": "Ana Perez",
                                 "commits": 2}])

    def test_does_not_flag_a_different_person(self):
        rows = ambiguous_identities([commit("beto@work.example", name="Beto Diaz")],
                                    self.identity)
        self.assertEqual(rows, [])

    def test_name_matching_ignores_case_and_padding(self):
        rows = ambiguous_identities([commit("ana@personal.com", name=" ana perez ")],
                                    self.identity)
        self.assertEqual(len(rows), 1)

    def test_already_known_emails_are_not_flagged(self):
        rows = ambiguous_identities([commit("ANA@work.example")], self.identity)
        self.assertEqual(rows, [])

    def test_ordered_by_commit_count_descending(self):
        rows = ambiguous_identities([
            commit("ana@one.com", hash="a"),
            commit("ana@two.com", hash="b"),
            commit("ana@two.com", hash="c"),
        ], self.identity)
        self.assertEqual([r["email"] for r in rows], ["ana@two.com", "ana@one.com"])

    def test_no_name_means_nothing_can_be_matched(self):
        self.assertEqual(
            ambiguous_identities([commit("ana@personal.com")],
                                 {"emails": ["ana@work.example"], "name": ""}), [])
