"""Tests for load_config — the surface a new project actually touches.

Every failure mode here is one an operator will hit while wiring up a project:
a typo'd path, a missing name, two repos labelled the same, a bad regex.
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from audit import ConfigError, _slug, load_config
from src.extract_commits import DEFAULT_EXCLUDED_PATH_PATTERNS


def make_repo(parent, name):
    """Create a real (empty) git repo, so the `.git` check is exercised for real."""
    path = Path(parent) / name
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True,
                   capture_output=True)
    return path


def write_config(parent, **overrides):
    body = {"project": "Acme", "repos": [{"path": "../api", "label": "api"}]}
    body.update(overrides)
    path = Path(parent) / "audit" / "audit.config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body))
    return path


class TestSlug(unittest.TestCase):
    def test_collapses_separators_and_capitalises(self):
        self.assertEqual(_slug("Acme"), "Acme")
        self.assertEqual(_slug("my project"), "MyProject")
        self.assertEqual(_slug("my-cool_project"), "MyCoolProject")

    def test_leaves_inner_capitals_alone(self):
        # `myWebApp` must not become `Mywebapp`.
        self.assertEqual(_slug("myWebApp"), "MyWebApp")


class TestLoadConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        make_repo(self.root, "api")
        self.addCleanup(self.tmp.cleanup)

    def test_loads_and_validates_timezone_changes(self):
        changes = [{"from": "2026-09-13", "timezone": "America/Los_Angeles"}]
        self.assertEqual(load_config(write_config(self.root, timezone_changes=changes))["timezone_changes"], changes)
        for changes in ([{"from": "bad", "timezone": "UTC"}],
                        [{"from": "2026-09-13", "timezone": "Invalid/Zone"}],
                        [{"from": "2026-09-13", "timezone": "UTC"}] * 2):
            with self.subTest(changes=changes), self.assertRaises(ConfigError):
                load_config(write_config(self.root, timezone_changes=changes))

    def test_resolves_repo_paths_against_the_config_file_not_the_cwd(self):
        # `--config some/where/audit.config.json` has to work from any cwd, so
        # relative repo paths are anchored to the config's own directory.
        config = load_config(write_config(self.root))
        self.assertEqual(config["repos"][0]["path"],
                         Path(self.root).resolve() / "api")

    def test_defaults_the_label_to_the_directory_name(self):
        config = load_config(write_config(self.root, repos=[{"path": "../api"}]))
        self.assertEqual(config["repos"][0]["label"], "api")

    def test_defaults_the_report_name_from_the_project(self):
        config = load_config(write_config(self.root, project="my project"))
        self.assertEqual(config["report_name"], "reportMyProject.html")

    def test_an_explicit_report_name_wins(self):
        config = load_config(write_config(self.root, report_name="x.html"))
        self.assertEqual(config["report_name"], "x.html")

    def test_defaults_the_output_dir_next_to_the_config(self):
        config = load_config(write_config(self.root))
        self.assertEqual(config["output_dir"],
                         Path(self.root).resolve() / "audit" / "output")

    def test_bucket_knobs_default_to_empty(self):
        config = load_config(write_config(self.root))
        self.assertEqual(config["deep_roots"], frozenset())
        self.assertEqual(config["nested_segments"], frozenset())

    def test_bucket_knobs_are_read_as_sets(self):
        config = load_config(write_config(
            self.root, hotspots={"deep_roots": ["src"], "nested_segments": ["modules"]}))
        self.assertEqual(config["deep_roots"], frozenset({"src"}))
        self.assertEqual(config["nested_segments"], frozenset({"modules"}))

    def test_me_defaults_to_empty_so_identity_falls_back_to_git_config(self):
        config = load_config(write_config(self.root))
        self.assertEqual(config["me"], {})

    def test_me_is_carried_through_verbatim(self):
        config = load_config(write_config(
            self.root, me={"name": "Ana", "emails": ["ana@work.example"]}))
        self.assertEqual(config["me"]["name"], "Ana")
        self.assertEqual(config["me"]["emails"], ["ana@work.example"])

    def test_timezone_defaults_and_can_be_overridden(self):
        self.assertEqual(load_config(write_config(self.root))["timezone"],
                         "America/Montevideo")
        self.assertEqual(
            load_config(write_config(self.root, timezone="UTC"))["timezone"], "UTC")

    def test_codex_sessions_dir_defaults_to_the_codex_home(self):
        config = load_config(write_config(self.root))
        self.assertEqual(config["codex_sessions_dir"], "~/.codex/sessions")

    def test_codex_sessions_dir_can_be_pointed_elsewhere(self):
        config = load_config(write_config(
            self.root, codex={"sessions_dir": "/srv/codex"}))
        self.assertEqual(config["codex_sessions_dir"], "/srv/codex")

    def test_codex_project_paths_default_to_the_audited_repos(self):
        # A Codex session belongs to this project when it ran inside one of the
        # clones being audited, so no extra configuration is needed for the
        # ordinary case.
        config = load_config(write_config(self.root))
        self.assertEqual(config["codex_project_paths"],
                         [str(r["path"]) for r in config["repos"]])

    def test_codex_project_paths_resolve_against_the_config_directory(self):
        config = load_config(write_config(
            self.root, codex={"project_paths": ["../api"]}))
        self.assertEqual(config["codex_project_paths"],
                         [str((Path(self.root) / "api").resolve())])

    def test_duplicate_scan_is_on_by_default_and_can_be_switched_off(self):
        self.assertTrue(load_config(write_config(self.root))["duplicate_scan"])
        self.assertFalse(
            load_config(write_config(self.root, duplicate_scan=False))["duplicate_scan"])

    def test_exclude_paths_are_appended_to_the_defaults_not_replaced(self):
        # A project adds its vendored trees; it must not lose the lockfile rules.
        config = load_config(write_config(self.root, exclude_paths=[r"(^|/)vendor/"]))
        self.assertEqual(len(config["excluded_paths"]),
                         len(DEFAULT_EXCLUDED_PATH_PATTERNS) + 1)
        self.assertTrue(any(p.search("a/vendor/x.js") for p in config["excluded_paths"]))
        self.assertTrue(any(p.search("yarn.lock") for p in config["excluded_paths"]))


class TestLoadConfigErrors(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        make_repo(self.root, "api")
        self.addCleanup(self.tmp.cleanup)

    def assert_raises_mentioning(self, needle, path):
        with self.assertRaises(ConfigError) as ctx:
            load_config(path)
        self.assertIn(needle, str(ctx.exception))

    def test_a_missing_config_names_the_path_it_looked_for(self):
        self.assert_raises_mentioning(
            "config not found", Path(self.root) / "nope.json")

    def test_invalid_json_is_reported_as_such(self):
        path = Path(self.root) / "bad.json"
        path.write_text("{not json")
        self.assert_raises_mentioning("invalid JSON", path)

    def test_a_missing_project_is_rejected(self):
        path = Path(self.root) / "audit" / "audit.config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"repos": [{"path": "../api"}]}))
        self.assert_raises_mentioning("'project' is required", path)

    def test_no_repos_is_rejected(self):
        self.assert_raises_mentioning(
            "at least one repo", write_config(self.root, repos=[]))

    def test_a_repo_without_a_path_is_rejected(self):
        self.assert_raises_mentioning(
            "needs a 'path'", write_config(self.root, repos=[{"label": "api"}]))

    def test_a_path_that_is_not_a_git_repo_names_the_label_and_the_path(self):
        # The most common wiring mistake: a typo, or a directory that was never
        # cloned. Failing here beats a report that silently reads zero commits.
        Path(self.root, "notarepo").mkdir()
        with self.assertRaises(ConfigError) as ctx:
            load_config(write_config(self.root, repos=[{"path": "../notarepo"}]))
        self.assertIn("notarepo", str(ctx.exception))
        self.assertIn("not a git repo", str(ctx.exception))

    def test_duplicate_labels_are_rejected(self):
        # Two repos sharing a label would merge into one column everywhere.
        make_repo(self.root, "other")
        self.assert_raises_mentioning("duplicate repo labels", write_config(
            self.root,
            repos=[{"path": "../api", "label": "same"},
                   {"path": "../other", "label": "same"}]))

    def test_an_invalid_exclude_regex_names_the_pattern(self):
        self.assert_raises_mentioning(
            "not a valid regex", write_config(self.root, exclude_paths=["[unclosed"]))


if __name__ == "__main__":
    unittest.main()


class TestPersonalConfigErrors(unittest.TestCase):
    """Failure modes specific to the personal audit's own config keys."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        make_repo(self.root, "api")
        self.addCleanup(self.tmp.cleanup)

    def test_a_bad_codex_evidence_regex_fails_early_with_the_pattern(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(write_config(self.root,
                                     codex={"commit_evidence": ["co-authored(-by"]}))
        self.assertIn("commit_evidence", str(ctx.exception))
        self.assertIn("co-authored(-by", str(ctx.exception))

    def test_me_must_be_an_object(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(write_config(self.root, me=["me@work.example"]))
        self.assertIn("'me' must be an object", str(ctx.exception))

    def test_evidence_patterns_default_to_none_so_the_engine_defaults_apply(self):
        self.assertIsNone(load_config(write_config(self.root))["codex_evidence_patterns"])
