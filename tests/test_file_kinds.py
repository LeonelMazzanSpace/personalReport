"""Tests for the file classifier that splits source from docs, config and noise."""
import unittest

from src.file_kinds import KIND_LABELS, KIND_ORDER, classify_lines, file_kind


def commit(files=(), excluded=()):
    return {"files": list(files), "excluded_files": list(excluded)}


class TestFileKind(unittest.TestCase):
    def test_source_extensions(self):
        for path in ["src/app.ts", "web/Page.tsx", "api/main.py", "a.go",
                     "styles/main.scss", "index.html", "schema.prisma"]:
            self.assertEqual(file_kind(path), "code", path)

    def test_test_directories_and_suffixes(self):
        for path in ["tests/test_x.py", "src/__tests__/a.ts", "a.test.tsx",
                     "b_test.go", "e2e/login.spec.ts", "spec/models/user.rb"]:
            self.assertEqual(file_kind(path), "tests", path)

    def test_tests_win_over_source_because_a_test_is_not_product_code(self):
        self.assertEqual(file_kind("src/__tests__/app.ts"), "tests")

    def test_documentation(self):
        for path in ["README.md", "docs/guide.mdx", "CHANGELOG", "notes.txt",
                     "LICENSE"]:
            self.assertEqual(file_kind(path), "docs", path)

    def test_configuration(self):
        for path in ["package.json", "tsconfig.json", ".eslintrc",
                     "docker-compose.yml", "Dockerfile", ".github/workflows/ci.yml",
                     "vite.config.ts", ".env.example"]:
            self.assertEqual(file_kind(path), "config", path)

    def test_generated_and_vendored(self):
        for path in ["yarn.lock", "pnpm-lock.yaml", "dist/main.js",
                     "node_modules/x/index.js", "a.min.js", "b.js.map",
                     "__snapshots__/a.snap", "src/migrations/001_init.sql"]:
            self.assertEqual(file_kind(path), "generated", path)

    def test_generated_wins_over_config_for_build_output(self):
        # dist/app.config.js is build output, not configuration someone wrote.
        self.assertEqual(file_kind("dist/app.config.js"), "generated")

    def test_an_unknown_extension_is_unclassified_not_source(self):
        # Inflating the source-code figure with whatever is left over would make
        # the one number a client cares about the least trustworthy one.
        self.assertEqual(file_kind("assets/logo.svg"), "unclassified")
        self.assertEqual(file_kind("data/sample.bin"), "unclassified")

    def test_a_file_with_no_extension_at_all(self):
        self.assertEqual(file_kind("scripts/deploy"), "unclassified")

    def test_every_kind_has_a_label(self):
        self.assertEqual(set(KIND_LABELS), set(KIND_ORDER))


class TestClassifyLines(unittest.TestCase):
    def test_sums_added_removed_and_files_per_bucket(self):
        result = classify_lines([commit(files=[(10, 2, "src/a.ts"),
                                               (3, 0, "src/b.ts"),
                                               (5, 1, "README.md")])])
        self.assertEqual(result["counted"]["code"],
                         {"added": 13, "removed": 2, "files": 2, "commits": 1})
        self.assertEqual(result["counted"]["docs"]["added"], 5)

    def test_a_commit_counts_once_per_bucket_however_many_files_it_touched(self):
        result = classify_lines([commit(files=[(1, 0, f"src/f{i}.ts")
                                               for i in range(20)])])
        self.assertEqual(result["counted"]["code"]["commits"], 1)
        self.assertEqual(result["counted"]["code"]["files"], 20)

    def test_empty_buckets_are_omitted_rather_than_shown_as_zero(self):
        result = classify_lines([commit(files=[(1, 0, "src/a.ts")])])
        self.assertEqual(set(result["counted"]), {"code"})

    def test_excluded_paths_are_reported_separately_not_merged_in(self):
        result = classify_lines([commit(files=[(1, 0, "src/a.ts")],
                                        excluded=[(900, 40, "yarn.lock")])])
        self.assertNotIn("generated", result["counted"])
        self.assertEqual(result["excluded"]["generated"],
                         {"added": 900, "removed": 40})

    def test_a_commit_without_the_excluded_key_still_classifies(self):
        # build_data callers that predate excluded_files must not crash.
        result = classify_lines([{"files": [(1, 0, "src/a.ts")]}])
        self.assertEqual(result["counted"]["code"]["added"], 1)

    def test_no_commits_yields_two_empty_sides(self):
        self.assertEqual(classify_lines([]), {"counted": {}, "excluded": {}})
