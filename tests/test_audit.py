"""End-to-end tests for the pipeline, against real (tiny) git repositories.

Everything below builds an actual repo and runs the actual audit over it. The
point is the wiring: identity filtering, period clipping, the Codex join, and the
three files the run must leave behind.
"""
import json
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path

import audit
from audit import ENRICHED_KEYS, build_data, build_duplicates_section, enrich, run
from src.extract_commits import Commit
from src.me import resolve_identity

ME = "ana@work.example"
OTHER = "beto@work.example"


def git(repo, *args, env=None):
    base = {"GIT_AUTHOR_NAME": "Ana Perez", "GIT_AUTHOR_EMAIL": ME,
            "GIT_COMMITTER_NAME": "Ana Perez", "GIT_COMMITTER_EMAIL": ME,
            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
            "PATH": "/usr/bin:/bin"}
    base.update(env or {})
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env=base)


def make_repo(root, name="api"):
    path = Path(root) / name
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True,
                   capture_output=True)
    git(path, "config", "user.email", ME)
    git(path, "config", "user.name", "Ana Perez")
    return path


def commit_file(repo, name, body, subject, when, email=ME, author="Ana Perez",
                message_body=""):
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(body)
    git(repo, "add", name)
    message = subject + (f"\n\n{message_body}" if message_body else "")
    git(repo, "commit", "-q", "-m", message,
        env={"GIT_AUTHOR_EMAIL": email, "GIT_AUTHOR_NAME": author,
             "GIT_COMMITTER_EMAIL": email, "GIT_COMMITTER_NAME": author,
             "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when})


def write_config(root, **overrides):
    body = {"project": "Catalyst", "repos": [{"path": "../api", "label": "api"}],
            "duplicate_scan": False}
    body.update(overrides)
    path = Path(root) / "audit" / "audit.config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body))
    return path


def fake_commit(email=ME, hash="a1", date="2026-09-02", subject="feat: x",
                files=(("src/a.ts", 10, 2),)):
    c = Commit(hash=hash, repo="api", email=email, name="Ana Perez", date=date,
               time="10:00", iso_week="2026-W36", month=date[:7], dow=2, hour=10,
               subject=subject)
    for path, added, removed in files:
        c.files.append((added, removed, path))
    return c


class TestEnrich(unittest.TestCase):
    def test_produces_exactly_the_documented_keys(self):
        # ENRICHED_KEYS is the contract every downstream module reads against.
        self.assertEqual(set(enrich([fake_commit()])[0]), set(ENRICHED_KEYS))

    def test_classification_is_folded_in(self):
        row = enrich([fake_commit(subject="fix(auth): guard")])[0]
        self.assertEqual((row["type"], row["scope"], row["category"]),
                         ("fix", "auth", "fix"))

    def test_line_counts_come_from_the_included_files(self):
        row = enrich([fake_commit(files=(("src/a.ts", 10, 2), ("src/b.ts", 5, 1)))])[0]
        self.assertEqual((row["lines_added"], row["lines_removed"]), (15, 3))
        self.assertEqual(row["files_changed"], 2)

    def test_no_commits_yields_no_rows(self):
        self.assertEqual(enrich([]), [])


class TestBuildDuplicatesSection(unittest.TestCase):
    def test_absent_input_yields_an_empty_dict_not_a_zeroed_one(self):
        # The disclosure note keys off falsiness to stay silent.
        self.assertEqual(build_duplicates_section(None), {})
        self.assertEqual(build_duplicates_section([]), {})

    def test_folds_per_repo_results_into_a_total(self):
        section = build_duplicates_section([
            {"repo": "api", "commits": 100, "redundant": 20, "groups": 5,
             "unique": 80, "no_patch": 0},
            {"repo": "web", "commits": 50, "redundant": 5, "groups": 2,
             "unique": 45, "no_patch": 1},
        ])
        self.assertEqual(section["total"]["commits"], 150)
        self.assertEqual(section["total"]["redundant"], 25)
        self.assertEqual(section["by_repo"]["api"]["redundant"], 20)


class TestBuildData(unittest.TestCase):
    def setUp(self):
        self.identity = {"name": "Ana Perez", "emails": [ME], "source": "config",
                         "detected_emails": []}

    def build(self, commits=None, **kw):
        enriched = enrich(commits if commits is not None else [fake_commit()])
        for row in enriched:
            row.setdefault("codex_attributed", False)
            row.setdefault("codex_concurrent", False)
        return build_data(enriched, self.identity, ["api"], {}, {}, [],
                          project="Catalyst", timezone_name="America/Montevideo", **kw)

    def test_meta_names_the_person_and_their_identities(self):
        meta = self.build()["meta"]
        self.assertEqual(meta["person"], "Ana Perez")
        self.assertEqual(meta["emails"], [ME])
        self.assertEqual(meta["project"], "Catalyst")

    def test_meta_repos_reflect_what_the_data_actually_contains(self):
        self.assertEqual(self.build()["meta"]["repos"], ["api"])

    def test_meta_repos_fall_back_to_the_configured_labels_when_empty(self):
        # An empty report must still name every repository that was read.
        self.assertEqual(self.build(commits=[])["meta"]["repos"], ["api"])

    def test_every_section_the_report_reads_is_present(self):
        data = self.build()
        for key in ["totals", "daily", "daily_totals", "day_items", "monthly",
                    "codex", "codex_evidence", "line_kinds", "rhythm", "hotspots",
                    "branches", "duplicates", "attribution", "meta"]:
            self.assertIn(key, data, key)

    def test_the_attribution_block_carries_the_identity_source(self):
        self.assertEqual(self.build()["attribution"]["source"], "config")


class TestRunEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.repo = make_repo(self.root)
        self.out = Path(self.root) / "out"

    def audit_run(self, config_path=None, month=None, today=None):
        config = audit.load_config(config_path or write_config(self.root))
        return run(config, self.out, fetch=False, month=month, today=today)

    def test_counts_only_my_commits(self):
        commit_file(self.repo, "src/a.ts", "a\n", "feat: mine",
                    "2026-09-02T10:00:00-03:00")
        commit_file(self.repo, "src/b.ts", "b\n", "feat: theirs",
                    "2026-09-03T10:00:00-03:00", email=OTHER, author="Beto Diaz")
        data, _ = self.audit_run()
        self.assertEqual(data["totals"]["commits"], 1)
        self.assertEqual(data["day_items"]["2026-09-02"][0]["subject"], "feat: mine")

    def test_a_second_identity_of_mine_is_flagged_not_silently_counted(self):
        commit_file(self.repo, "src/a.ts", "a\n", "feat: work",
                    "2026-09-02T10:00:00-03:00")
        commit_file(self.repo, "src/b.ts", "b\n", "feat: laptop",
                    "2026-09-03T10:00:00-03:00", email="ana@personal.com")
        data, _ = self.audit_run()
        self.assertEqual(data["totals"]["commits"], 1)
        self.assertEqual(data["attribution"]["ambiguous"],
                         [{"email": "ana@personal.com", "name": "Ana Perez",
                           "commits": 1}])

    def test_config_emails_can_claim_both_identities(self):
        commit_file(self.repo, "src/a.ts", "a\n", "feat: work",
                    "2026-09-02T10:00:00-03:00")
        commit_file(self.repo, "src/b.ts", "b\n", "feat: laptop",
                    "2026-09-03T10:00:00-03:00", email="ana@personal.com")
        config = write_config(self.root,
                              me={"name": "Ana Perez",
                                  "emails": [ME, "ana@personal.com"]})
        data, _ = self.audit_run(config)
        self.assertEqual(data["totals"]["commits"], 2)
        self.assertEqual(data["attribution"]["ambiguous"], [])

    def test_the_month_filter_clips_every_figure(self):
        commit_file(self.repo, "src/a.ts", "a\n", "feat: august",
                    "2026-08-20T10:00:00-03:00")
        commit_file(self.repo, "src/b.ts", "b\n", "feat: september",
                    "2026-09-02T10:00:00-03:00")
        data, _ = self.audit_run(month="2026-09", today=date(2026, 9, 30))
        self.assertEqual(data["totals"]["commits"], 1)
        self.assertEqual(data["meta"]["period"]["label"], "September 2026")
        self.assertEqual(len(data["daily"]), 30)

    def test_a_running_month_is_clipped_and_flagged(self):
        commit_file(self.repo, "src/a.ts", "a\n", "feat: x",
                    "2026-09-02T10:00:00-03:00")
        data, _ = self.audit_run(month="2026-09", today=date(2026, 9, 10))
        self.assertTrue(data["meta"]["period"]["month_to_date"])
        self.assertEqual(len(data["daily"]), 10)

    def test_a_codex_trailer_marks_the_commit_as_attributed(self):
        commit_file(self.repo, "src/a.ts", "a\n", "feat: assisted",
                    "2026-09-02T10:00:00-03:00",
                    message_body="Co-authored-by: Codex <noreply@openai.com>")
        commit_file(self.repo, "src/b.ts", "b\n", "feat: solo",
                    "2026-09-03T10:00:00-03:00")
        data, _ = self.audit_run()
        self.assertEqual(data["codex_evidence"]["attributed"], 1)
        self.assertEqual(data["codex_evidence"]["no_evidence"], 1)

    def test_lockfile_churn_stays_out_of_the_totals_but_is_disclosed(self):
        commit_file(self.repo, "yarn.lock", "x\n" * 900, "chore: deps",
                    "2026-09-02T10:00:00-03:00")
        data, _ = self.audit_run()
        self.assertEqual(data["totals"]["lines_added"], 0)
        self.assertEqual(data["totals"]["raw_added"], 900)
        self.assertEqual(data["line_kinds"]["excluded"]["generated"]["added"], 900)

    def test_branches_are_narrowed_to_those_i_last_committed_to(self):
        commit_file(self.repo, "src/a.ts", "a\n", "feat: base",
                    "2026-09-02T10:00:00-03:00")
        git(self.repo, "checkout", "-q", "-b", "feature/theirs")
        commit_file(self.repo, "src/b.ts", "b\n", "feat: theirs",
                    "2026-09-03T10:00:00-03:00", email=OTHER, author="Beto Diaz")
        data, _ = self.audit_run()
        self.assertEqual([b["name"] for b in data["branches"]], ["main"])

    def test_codex_metrics_are_unavailable_when_there_is_no_history(self):
        commit_file(self.repo, "src/a.ts", "a\n", "feat: x",
                    "2026-09-02T10:00:00-03:00")
        config = write_config(self.root,
                              codex={"sessions_dir": "/nonexistent/codex"})
        data, _ = self.audit_run(config)
        self.assertFalse(data["codex"]["available"])
        self.assertEqual(data["codex"]["coverage"]["files_found"], 0)

    def test_the_raw_session_intervals_never_reach_the_dataset(self):
        commit_file(self.repo, "src/a.ts", "a\n", "feat: x",
                    "2026-09-02T10:00:00-03:00")
        data, _ = self.audit_run()
        self.assertNotIn("_intervals", data["codex"])

    def test_the_run_writes_the_report_and_both_json_files(self):
        commit_file(self.repo, "src/a.ts", "a\n", "feat: x",
                    "2026-09-02T10:00:00-03:00")
        self.audit_run()
        self.assertTrue((self.out / "reportCatalyst.html").is_file())
        self.assertTrue((self.out / "data.json").is_file())
        self.assertTrue((self.out / "metrics.json").is_file())

    def test_the_metrics_file_is_valid_json_with_the_expected_blocks(self):
        commit_file(self.repo, "src/a.ts", "a\n", "feat: x",
                    "2026-09-02T10:00:00-03:00")
        self.audit_run()
        metrics = json.loads((self.out / "metrics.json").read_text())
        for key in ["report", "activity", "commits", "lines", "days", "definitions",
                    "coverage"]:
            self.assertIn(key, metrics, key)

    def test_the_audited_repo_is_left_untouched(self):
        commit_file(self.repo, "src/a.ts", "a\n", "feat: x",
                    "2026-09-02T10:00:00-03:00")
        before = subprocess.run(["git", "-C", str(self.repo), "status", "--porcelain",
                                 "-b"], capture_output=True, text=True).stdout
        self.audit_run()
        after = subprocess.run(["git", "-C", str(self.repo), "status", "--porcelain",
                                "-b"], capture_output=True, text=True).stdout
        self.assertEqual(before, after)

    def test_an_empty_period_produces_a_complete_report_rather_than_failing(self):
        commit_file(self.repo, "src/a.ts", "a\n", "feat: x",
                    "2026-08-02T10:00:00-03:00")
        data, _ = self.audit_run(month="2026-09", today=date(2026, 9, 10))
        self.assertEqual(data["totals"]["commits"], 0)
        self.assertTrue((self.out / "reportCatalyst.html").is_file())


class TestResolveIdentityFromRealRepos(unittest.TestCase):
    def test_reads_user_email_out_of_the_audited_clone(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            identity = resolve_identity(None, [{"path": repo, "label": "api"}])
            self.assertEqual(identity["emails"], [ME])
            self.assertEqual(identity["name"], "Ana Perez")
            self.assertEqual(identity["source"], "git config")
