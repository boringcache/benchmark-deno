from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


write_phase_result = load_script("write_phase_result.py")
render_comparison = load_script("render_comparison.py")
compare_rolling_controls = load_script("compare_rolling_controls.py")
verify_restored_freshness = load_script("verify_restored_freshness.py")


class SccacheTargetCohortWorkflowTest(unittest.TestCase):
    def test_establishes_deno_mtimes_before_building_the_shared_seed(self):
        workflow = (
            ROOT / ".github/workflows/deno-release-sccache-target-cohort.yml"
        ).read_text()

        mtime_step = workflow.index("Establish the base source mtime identity")
        build_step = workflow.index("Build the shared base seed")
        self.assertLess(mtime_step, build_step)
        self.assertIn(
            "node ./scripts/run-deno-mtime-cache.js ./upstream", workflow
        )
        self.assertIn("test -s upstream/target/.mtime-cache-db.json", workflow)

    def test_prunes_deno_exclusions_before_either_product_saves(self):
        workflow = (
            ROOT / ".github/workflows/deno-release-sccache-target-cohort.yml"
        ).read_text()

        build_step = workflow.index("Build the shared base seed")
        prune_step = workflow.index(
            "Apply Deno's target archive exclusions to the shared state"
        )
        actions_save = workflow.index("Save the Actions target and local sccache archive")
        self.assertLess(build_step, prune_step)
        self.assertLess(prune_step, actions_save)
        for pattern in ("gn_out", "gn_root", "'*.zip'", "'*.tar.gz'"):
            self.assertIn(pattern, workflow)

    def test_actions_archive_matches_the_explicit_cargo_profile(self):
        workflow = (
            ROOT / ".github/workflows/deno-release-sccache-target-cohort.yml"
        ).read_text()

        self.assertEqual(workflow.count("~/.cargo/registry"), 2)
        self.assertEqual(workflow.count("~/.cargo/bin"), 2)
        self.assertNotIn("~/.cargo/registry/index", workflow)
        self.assertNotIn("~/.cargo/registry/cache", workflow)
        self.assertNotIn("~/.cargo/git/db", workflow)
        self.assertNotIn("~/.cargo/.crates.toml", workflow)
        self.assertNotIn("~/.cargo/.crates2.json", workflow)

    def test_action_post_owns_the_seed_sccache_shutdown(self):
        workflow = (
            ROOT / ".github/workflows/deno-release-sccache-target-cohort.yml"
        ).read_text()

        self.assertNotIn("sccache --stop-server", workflow)
        self.assertNotIn("sccache --start-server", workflow)

    def test_reuses_the_action_installed_sccache_binary(self):
        workflow = (
            ROOT / ".github/workflows/deno-release-sccache-target-cohort.yml"
        ).read_text()

        self.assertIn('test -x "$HOME/.local/bin/sccache"', workflow)
        self.assertNotIn('cp "$(command -v sccache)"', workflow)


class SccacheStatsTest(unittest.TestCase):
    def test_parses_hit_rate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stats.txt"
            path.write_text(
                "Compile requests                    12\n"
                "Compile requests executed           10\n"
                "Cache hits                           8\n"
                "Cache misses                         2\n"
                "Non-cacheable compilations           2\n"
            )

            self.assertEqual(
                write_phase_result.parse_sccache_stats(path),
                {
                    "compile_requests": 12,
                    "compile_requests_executed": 10,
                    "cache_hits": 8,
                    "cache_misses": 2,
                    "non_cacheable_compilations": 2,
                    "cache_hit_percent": 80,
                },
            )

    def test_parses_native_error_and_duration_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stats.txt"
            path.write_text(
                "Compile requests                    20\n"
                "Cache hits                          18\n"
                "Cache hits (Rust)                   17\n"
                "Cache misses                         2\n"
                "Cache misses (C/C++)                 2\n"
                "Cache errors                         3\n"
                "Cache read errors                    0\n"
                "Cache write errors                   3\n"
                "Cache timeouts                       0\n"
                "Average cache read hit           0.004 s\n"
                "Non-cacheable reasons:\n"
                "crate-type                         12\n"
                "missing input                       2\n"
                "\n"
            )

            stats = write_phase_result.parse_sccache_stats(path)

            self.assertEqual(stats["cache_hit_percent"], 90)
            self.assertEqual(stats["cache_hits_rust"], 17)
            self.assertEqual(stats["cache_misses_c_cpp"], 2)
            self.assertEqual(stats["cache_write_errors"], 3)
            self.assertEqual(stats["average_cache_read_hit_seconds"], 0.004)
            self.assertEqual(
                stats["non_cacheable_reasons"], {"crate-type": 12, "missing input": 2}
            )


class RestoredFreshnessTest(unittest.TestCase):
    def test_proves_exact_mtimes_and_cargo_freshness(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            tracked = source / "src.rs"
            tracked.write_text("fn main() {}\n")
            restored_mtime = 1_700_000_000.25
            tracked.touch()
            os.utime(tracked, (restored_mtime, restored_mtime))
            key = "100644\0abc\0i/lf w/lf\0src.rs"
            before = root / "before.json"
            after = root / "after.json"
            log = root / "mtime.log"
            cargo = root / "cargo.jsonl"
            before.write_text(json.dumps({key: restored_mtime}))
            after.write_text(json.dumps({key: restored_mtime}))
            log.write_text(
                "mtime cache statistics\n"
                "* restored: 1\n* added: 0\n* stale: 0\n* invalid: 0\n"
            )
            cargo.write_text(
                json.dumps(
                    {
                        "reason": "compiler-artifact",
                        "package_id": "fresh@1",
                        "target": {"name": "fresh"},
                        "fresh": True,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "reason": "compiler-artifact",
                        "package_id": "rebuilt@1",
                        "target": {"name": "rebuilt"},
                        "fresh": False,
                    }
                )
                + "\n"
                + json.dumps({"reason": "build-finished", "success": True})
                + "\n"
            )

            evidence = verify_restored_freshness.build_evidence(
                source, before, after, log, cargo
            )

            self.assertEqual(evidence["mtime"]["exact_restored_entries"], 1)
            self.assertEqual(evidence["cargo"]["fresh_targets"], 1)
            self.assertEqual(evidence["cargo"]["rebuilt_targets"], 1)

    def test_rejects_a_filesystem_mtime_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "src.rs").write_text("fn main() {}\n")
            key = "100644\0abc\0i/lf w/lf\0src.rs"

            with self.assertRaisesRegex(ValueError, "filesystem mtime differs"):
                verify_restored_freshness.verify_restored_mtimes(
                    source, {key: 1_700_000_000.0}, {key: 1_700_000_000.0}
                )


class ComparisonReportTest(unittest.TestCase):
    def test_reports_rolling_improvement_without_overselling(self):
        results = {}
        for strategy, base, rolling in (
            ("actions-cache", 1200, 900),
            ("boringcache", 1210, 600),
        ):
            for phase, seconds in (("base", base), ("rolling", rolling)):
                results[(strategy, phase)] = {
                    "strategy": strategy,
                    "phase": phase,
                    "timing": {
                        "restore_seconds": 10,
                        "build_seconds": seconds,
                        "end_to_end_seconds": seconds + 10,
                    },
                    "cache": {"storage_bytes": 1024**3},
                    "sccache": None,
                }

        payload = render_comparison.comparison_payload(results)
        markdown = render_comparison.render_markdown(payload)

        self.assertEqual(payload["rolling_comparison"]["end_to_end_seconds_saved"], 300)
        self.assertEqual(payload["rolling_comparison"]["percent_saved"], 33.0)
        self.assertEqual(payload["rolling_comparison"]["build_seconds_saved"], 300)
        self.assertIn("saved **300s (33.0%)**", markdown)

    def test_requires_all_four_results(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "one.json"
            path.write_text(json.dumps({"strategy": "actions-cache", "phase": "base"}))

            with self.assertRaisesRegex(ValueError, "Missing benchmark results"):
                render_comparison.load_results(Path(directory))

    def test_supports_explicit_hybrid_candidate(self):
        results = {}
        for strategy in ("actions-cache", "boringcache-hybrid"):
            for phase in ("base", "rolling"):
                results[(strategy, phase)] = {
                    "strategy": strategy,
                    "phase": phase,
                    "timing": {
                        "restore_seconds": 5,
                        "build_seconds": 100,
                        "end_to_end_seconds": 105,
                    },
                    "cache": {"storage_bytes": 1024},
                    "sccache": None,
                }

        payload = render_comparison.comparison_payload(
            results,
            candidate_strategy="boringcache-hybrid",
            title="Deno release hybrid cache proof",
        )

        self.assertEqual(payload["candidate_strategy"], "boringcache-hybrid")
        self.assertIn("Deno release hybrid", render_comparison.render_markdown(payload))


class RollingControlComparisonTest(unittest.TestCase):
    def test_compares_matching_rolling_cohorts_and_renders_freshness(self):
        baseline = {
            "benchmark": "deno-release-rust-cache",
            "strategy": "actions-cache",
            "phase": "rolling",
            "project": {"repository": "denoland/deno", "source_sha": "head"},
            "workload": {
                "build_profile": "release",
                "command": "./scripts/run-deno-release-build.sh",
            },
            "product": {"cli_version": "v1.15.0", "action_sha": "release-sha"},
            "runner": {
                "provider": "github-actions",
                "image": "ubuntu24",
                "image_version": "20260720.247.2",
                "architecture": "X64",
                "os": "Linux",
                "hardware": {
                    "cpu_model": "AMD EPYC 7763",
                    "logical_cores": 4,
                    "memory_class_gib": 16,
                },
            },
            "compiler_environment": {"sha256": "compiler-env"},
            "timing": {
                "restore_seconds": 108,
                "build_seconds": 1379,
                "end_to_end_seconds": 1487,
            },
        }
        candidate = {
            **baseline,
            "strategy": "boringcache-target-only",
            "timing": {
                "restore_seconds": 80,
                "build_seconds": 1380,
                "end_to_end_seconds": 1460,
            },
            "target_freshness": {
                "mtime": {
                    "exact_restored_entries": 14660,
                    "mismatched_entries": 0,
                },
                "cargo": {"fresh_targets": 990, "rebuilt_targets": 4},
            },
        }

        payload = compare_rolling_controls.compare(baseline, candidate, "Control")
        markdown = compare_rolling_controls.render_markdown(payload)

        self.assertEqual(payload["comparison"]["build_seconds_saved"], -1)
        self.assertEqual(payload["comparison"]["end_to_end_seconds_saved"], 27)
        self.assertIn("Exact restored mtimes: 14660", markdown)
        self.assertIn("Candidate saved **27s (1.8%)**", markdown)

    def test_rejects_a_different_source_cohort(self):
        baseline = {
            "benchmark": "deno-release-rust-cache",
            "phase": "rolling",
            "project": {"repository": "denoland/deno", "source_sha": "a"},
            "workload": {"build_profile": "release"},
            "product": {"cli_version": "v1.15.0", "action_sha": "release-sha"},
            "runner": {
                "provider": "github-actions",
                "image": "ubuntu24",
                "image_version": "20260720.247.2",
                "architecture": "X64",
                "os": "Linux",
                "hardware": {
                    "cpu_model": "AMD EPYC 7763",
                    "logical_cores": 4,
                    "memory_class_gib": 16,
                },
            },
            "compiler_environment": {"sha256": "compiler-env"},
            "timing": {"restore_seconds": 1, "build_seconds": 2, "end_to_end_seconds": 3},
        }
        candidate = {
            **baseline,
            "project": {"repository": "denoland/deno", "source_sha": "b"},
        }

        with self.assertRaisesRegex(ValueError, "Mismatched project cohort"):
            compare_rolling_controls.compare(baseline, candidate, "Control")

    def test_rejects_a_different_product_release(self):
        baseline = {
            "benchmark": "deno-release-rust-cache",
            "phase": "rolling",
            "project": {"repository": "denoland/deno", "source_sha": "head"},
            "workload": {"build_profile": "release"},
            "product": {"cli_version": "v1.15.0", "action_sha": "release-sha"},
            "runner": {
                "provider": "github-actions",
                "image": "ubuntu24",
                "image_version": "20260720.247.2",
                "architecture": "X64",
                "os": "Linux",
                "hardware": {
                    "cpu_model": "AMD EPYC 7763",
                    "logical_cores": 4,
                    "memory_class_gib": 16,
                },
            },
            "compiler_environment": {"sha256": "compiler-env"},
            "timing": {"restore_seconds": 1, "build_seconds": 2, "end_to_end_seconds": 3},
        }
        candidate = {
            **baseline,
            "product": {"cli_version": "v1.15.1", "action_sha": "release-sha"},
        }

        with self.assertRaisesRegex(ValueError, "Mismatched product cli_version"):
            compare_rolling_controls.compare(baseline, candidate, "Control")

    def test_rejects_a_different_runner_image_release(self):
        baseline = {
            "benchmark": "deno-release-rust-cache",
            "phase": "rolling",
            "project": {"repository": "denoland/deno", "source_sha": "head"},
            "workload": {"build_profile": "release"},
            "product": {"cli_version": "v1.15.0", "action_sha": "release-sha"},
            "runner": {
                "provider": "github-actions",
                "image": "ubuntu24",
                "image_version": "20260720.247.2",
                "architecture": "X64",
                "os": "Linux",
                "hardware": {
                    "cpu_model": "AMD EPYC 7763",
                    "logical_cores": 4,
                    "memory_class_gib": 16,
                },
            },
            "compiler_environment": {"sha256": "compiler-env"},
            "timing": {"restore_seconds": 1, "build_seconds": 2, "end_to_end_seconds": 3},
        }
        candidate = {
            **baseline,
            "runner": {**baseline["runner"], "image_version": "20260726.254.1"},
        }

        with self.assertRaisesRegex(ValueError, "Mismatched runner image_version"):
            compare_rolling_controls.compare(baseline, candidate, "Control")

    def test_rejects_a_different_compiler_environment(self):
        baseline = {
            "benchmark": "deno-release-rust-cache",
            "phase": "rolling",
            "project": {"repository": "denoland/deno", "source_sha": "head"},
            "workload": {"build_profile": "release"},
            "product": {"cli_version": "v1.15.0", "action_sha": "release-sha"},
            "runner": {
                "provider": "github-actions",
                "image": "ubuntu24",
                "image_version": "20260720.247.2",
                "architecture": "X64",
                "os": "Linux",
                "hardware": {
                    "cpu_model": "AMD EPYC 7763",
                    "logical_cores": 4,
                    "memory_class_gib": 16,
                },
            },
            "compiler_environment": {"sha256": "baseline-env"},
            "timing": {"restore_seconds": 1, "build_seconds": 2, "end_to_end_seconds": 3},
        }
        candidate = {
            **baseline,
            "compiler_environment": {"sha256": "candidate-env"},
        }

        with self.assertRaisesRegex(ValueError, "Mismatched compiler environment identity"):
            compare_rolling_controls.compare(baseline, candidate, "Control")

    def test_rejects_a_different_runner_cpu(self):
        baseline = {
            "benchmark": "deno-release-rust-cache",
            "phase": "rolling",
            "project": {"repository": "denoland/deno", "source_sha": "head"},
            "workload": {"build_profile": "release"},
            "product": {"cli_version": "v1.15.0", "action_sha": "release-sha"},
            "runner": {
                "provider": "github-actions",
                "image": "ubuntu24",
                "image_version": "20260720.247.2",
                "architecture": "X64",
                "os": "Linux",
                "hardware": {
                    "cpu_model": "AMD EPYC 7763",
                    "logical_cores": 4,
                    "memory_class_gib": 16,
                },
            },
            "compiler_environment": {"sha256": "compiler-env"},
            "timing": {"restore_seconds": 1, "build_seconds": 2, "end_to_end_seconds": 3},
        }
        candidate = {
            **baseline,
            "runner": {
                **baseline["runner"],
                "hardware": {
                    **baseline["runner"]["hardware"],
                    "cpu_model": "Intel Xeon Platinum 8370C",
                },
            },
        }

        with self.assertRaisesRegex(ValueError, "Mismatched runner hardware cpu_model"):
            compare_rolling_controls.compare(baseline, candidate, "Control")


if __name__ == "__main__":
    unittest.main()
