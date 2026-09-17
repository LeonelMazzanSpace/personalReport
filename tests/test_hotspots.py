import unittest

from src.hotspots import build_hotspots, dir_key


def commit(repo="web", files=(), hash="abcdef1"):
    return {
        "repo": repo, "email": "a@x.com",
        "hash": hash, "date": "2026-08-04", "time": "10:00",
        "month": "2026-08", "dow": 1, "hour": 10,
        "subject": "feat: x", "lines_added": sum(a for a, _r, _p in files),
        "lines_removed": sum(r for _a, r, _p in files),
        "raw_added": 0, "raw_removed": 0, "files_changed": len(files),
        "files": list(files), "type": "feat", "scope": None,
        "is_conventional": True, "category": "feature", "is_refactor": False,
    }


# The two knobs a project sets in audit.config.json under `hotspots`. These stand
# in for a single-package repo (`src` is the only real root, `src/modules` the
# domain tree) — the shape AUDIT.md step 3 calibrates.
ROOTS = frozenset({"src"})
NESTED = frozenset({"modules"})


class TestDirKeyDefaults(unittest.TestCase):
    """With no config, every directory buckets at one segment."""

    def test_one_segment_by_default(self):
        self.assertEqual(dir_key("api", "src/modules/jobs/a.ts"), "api/src")
        self.assertEqual(dir_key("api", "lib/x.ts"), "api/lib")

    def test_a_repo_root_file_is_labelled(self):
        self.assertEqual(dir_key("api", "package.json"), "api/(root)")


class TestDirKey(unittest.TestCase):
    def test_prefixes_the_repo_so_two_repos_src_dirs_do_not_collide(self):
        self.assertEqual(dir_key("api", "src/config/env.ts", ROOTS, NESTED),
                         "api/src/config")
        self.assertEqual(dir_key("web", "src/config/api.ts", ROOTS, NESTED),
                         "web/src/config")

    def test_a_deep_root_keeps_a_second_segment(self):
        self.assertEqual(dir_key("web", "src/components/Button.tsx", ROOTS, NESTED),
                         "web/src/components")

    def test_a_nested_segment_keeps_a_third_segment(self):
        # One segment collapses a single-package repo to `src` alone; two collapse
        # it to `src/modules`. Three is where the signal is — one bucket per domain
        # module. See design decision D6.
        self.assertEqual(
            dir_key("api", "src/modules/subscription/subscription.service.ts",
                    ROOTS, NESTED),
            "api/src/modules/subscription")
        self.assertEqual(dir_key("mobile", "src/modules/workers/WorkerCard.tsx",
                                 ROOTS, NESTED),
                         "mobile/src/modules/workers")

    def test_a_file_directly_under_a_nested_segment_keeps_two_segments(self):
        self.assertEqual(dir_key("api", "src/modules/index.ts", ROOTS, NESTED),
                         "api/src/modules")

    def test_a_file_directly_under_a_deep_root_keeps_one_segment(self):
        self.assertEqual(dir_key("api", "src/main.ts", ROOTS, NESTED),
                         "api/src")

    def test_a_repo_root_file_is_labelled(self):
        self.assertEqual(dir_key("api", "package.json", ROOTS, NESTED),
                         "api/(root)")
        self.assertEqual(dir_key("web", "bitbucket-pipelines.yml", ROOTS, NESTED),
                         "web/(root)")

    def test_a_non_deep_root_directory_keeps_one_segment(self):
        self.assertEqual(dir_key("web", "docs/superpowers/plans/x.md", ROOTS, NESTED),
                         "web/docs")
        self.assertEqual(dir_key("api", "test/app.e2e-spec.ts", ROOTS, NESTED),
                         "api/test")

    def test_a_monorepo_shape_keeps_workspace_then_src(self):
        # The other calibration AUDIT.md step 3 can land on: workspaces as deep
        # roots and `src` as the nested segment.
        roots, nested = frozenset({"frontend", "backend"}), frozenset({"src"})
        self.assertEqual(
            dir_key("mono", "frontend/src/modules/coins/CoinList.tsx", roots, nested),
            "mono/frontend/src/modules")
        self.assertEqual(dir_key("mono", "backend/openapi.yaml", roots, nested),
                         "mono/backend")


class TestFiles(unittest.TestCase):
    def test_ranks_files_by_commit_count(self):
        rows = build_hotspots([
            commit(files=[(1, 0, "backend/src/app.ts")]),
            commit(files=[(1, 0, "backend/src/app.ts")]),
            commit(files=[(1, 0, "backend/src/other.ts")]),
        ])["files"]
        self.assertEqual(rows[0]["path"], "backend/src/app.ts")
        self.assertEqual(rows[0]["commits"], 2)

    def test_file_row_carries_the_repo_and_sums_every_touch(self):
        rows = build_hotspots([
            commit(repo="web", files=[(5, 1, "src/main.ts")]),
            commit(repo="web", hash="beef123", files=[(3, 2, "src/main.ts")]),
        ])["files"]
        self.assertEqual(rows[0]["repo"], "web")
        self.assertEqual(rows[0]["commits"], 2)
        self.assertEqual((rows[0]["added"], rows[0]["removed"]), (8, 3))

    def test_the_same_path_in_two_repos_is_two_rows(self):
        rows = build_hotspots([
            commit(repo="web", files=[(1, 0, "scripts/x.sh")]),
            commit(repo="api", files=[(1, 0, "scripts/x.sh")]),
        ])["files"]
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["repo"] for r in rows}, {"web", "api"})

    def test_honours_the_top_files_cap(self):
        rows = build_hotspots(
            [commit(files=[(1, 0, f"backend/src/f{i}.ts")]) for i in range(40)],
            top_files=5)["files"]
        self.assertEqual(len(rows), 5)

    def test_total_files_touched_counts_distinct_repo_path_pairs(self):
        result = build_hotspots([
            commit(files=[(1, 0, "a.ts"), (1, 0, "b.ts")]),
            commit(files=[(1, 0, "a.ts")]),
        ])
        self.assertEqual(result["total_files_touched"], 2)


class TestDirs(unittest.TestCase):
    def test_ranks_directories_by_file_touch_volume(self):
        rows = build_hotspots([
            commit(files=[(1, 0, "src/modules/jobs/a.tsx"),
                          (1, 0, "src/modules/jobs/b.tsx"),
                          (1, 0, "src/common/c.ts")]),
        ], deep_roots=ROOTS, nested_segments=NESTED)["dirs"]
        self.assertEqual(rows[0]["dir"], "web/src/modules/jobs")
        self.assertEqual(rows[0]["files"], 2)

    def test_a_commit_sweeping_a_directory_counts_as_one_commit_there(self):
        # Otherwise a 20-file sweep would credit its author 20 times.
        rows = build_hotspots([
            commit(files=[(1, 0, f"src/modules/jobs/f{i}.tsx")
                                        for i in range(20)]),
        ], deep_roots=ROOTS, nested_segments=NESTED)["dirs"]
        self.assertEqual(rows[0]["files"], 20)
        self.assertEqual(rows[0]["commits"], 1)


    def test_build_hotspots_forwards_the_bucket_config(self):
        # Same commit, two calibrations: the knobs must reach dir_key, not be
        # silently dropped somewhere in build_hotspots.
        files = [(1, 0, "src/modules/jobs/a.tsx")]
        flat = build_hotspots([commit(files=files)])["dirs"]
        deep = build_hotspots([commit(files=files)], deep_roots=ROOTS,
                              nested_segments=NESTED)["dirs"]
        self.assertEqual(flat[0]["dir"], "web/src")
        self.assertEqual(deep[0]["dir"], "web/src/modules/jobs")

    def test_honours_the_top_dirs_cap(self):
        rows = build_hotspots(
            [commit(files=[(1, 0, f"d{i}/f.ts")]) for i in range(40)],
            top_dirs=6)["dirs"]
        self.assertEqual(len(rows), 6)


class TestExtensions(unittest.TestCase):
    def test_ranks_extensions_by_total_lines(self):
        rows = build_hotspots([
            commit(files=[(100, 50, "frontend/src/a.tsx"), (5, 1, "docs/b.md")]),
        ])["extensions"]
        self.assertEqual(rows[0]["ext"], ".tsx")
        self.assertEqual(rows[0]["lines"], 150)

    def test_a_dotfile_without_an_extension_is_labelled(self):
        rows = build_hotspots([commit(files=[(1, 0, "Dockerfile")])])["extensions"]
        self.assertEqual(rows[0]["ext"], "(no extension)")

    def test_a_dotted_directory_does_not_leak_into_the_extension(self):
        rows = build_hotspots([commit(files=[(1, 0, ".azure-pipeline/build")])])["extensions"]
        self.assertEqual(rows[0]["ext"], "(no extension)")

    def test_a_commit_touching_many_files_of_one_extension_counts_one_commit(self):
        rows = build_hotspots([
            commit(files=[(1, 0, f"frontend/src/f{i}.tsx") for i in range(10)]),
        ])["extensions"]
        self.assertEqual(rows[0]["files"], 10)
        self.assertEqual(rows[0]["commits"], 1)


class TestEmpty(unittest.TestCase):
    def test_no_commits_yields_empty_rows(self):
        result = build_hotspots([])
        self.assertEqual(result, {"files": [], "dirs": [], "extensions": [],
                                  "total_files_touched": 0})

    def test_a_commit_whose_only_files_were_excluded_contributes_nothing(self):
        result = build_hotspots([commit(files=[])])
        self.assertEqual(result["total_files_touched"], 0)
        self.assertEqual(result["dirs"], [])
