#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import runpy
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SELECTOR = runpy.run_path(str(ROOT / "scripts/select-deno-cargo-phase.py"))
REPORT = runpy.run_path(str(ROOT / "scripts/benchmark-report.py"))


class CargoCommandsTest(unittest.TestCase):
    def test_job_lifecycle_removes_only_the_embedded_command(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".boringcache.toml"
            path.write_text((ROOT / ".boringcache.toml").read_text())
            expected = tomllib.loads(path.read_text())
            del expected["adapters"]["cargo"]["command"]
            SELECTOR["select_job_lifecycle"](path)
            self.assertEqual(tomllib.loads(path.read_text()), expected)

    def test_both_commands_use_the_release_recipe_and_return_build_failure(self):
        settings = SELECTOR["read_settings"](ROOT / "scripts/deno-release-recipe.env")
        for phase in ("primary", "desktop"):
            with self.subTest(phase=phase), patch("sys.argv", ["select-deno-cargo-phase.py", "run", phase]), patch("subprocess.run") as build:
                build.return_value.returncode = 7
                self.assertEqual(SELECTOR["main"](), 7)
                build.assert_called_once_with(
                    SELECTOR["cargo_command"](settings, phase),
                    cwd=ROOT / "upstream",
                    check=False,
                )


class CompletedTimingsTest(unittest.TestCase):
    def setUp(self):
        def stamp(seconds):
            return f"2026-09-25T00:{seconds // 60:02d}:{seconds % 60:02d}+00:00"

        def step(name, start, end):
            return {"name": name, "started_at": stamp(start), "completed_at": stamp(end), "conclusion": "success"}

        self.phase = {"strategy": "boringcache", "phase": "source_change", "lane": "fresh", "variant": None, "cache": {"cache_variant": "target"}}
        self.job = {
            "name": "boringcache-source-change / boringcache source_change",
            "started_at": stamp(0),
            "completed_at": stamp(150),
            "conclusion": "success",
            "steps": [
                step("Start the cache and build timer", 10, 10),
                step("Build Deno release binaries", 20, 80),
                step("Build denort_desktop", 80, 110),
                step("Post Restore BoringCache for both Cargo commands", 120, 140),
            ],
        }

    def apply(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.json"
            path.write_text(json.dumps([{"jobs": [self.job]}]))
            REPORT["apply_completed_job_timings"]([self.phase], str(path))

    def test_post_save_is_included_once_in_total_and_workflow_duration(self):
        self.apply()
        self.assertEqual(self.phase["timing"]["restore_or_setup_seconds"], 10)
        self.assertEqual(self.phase["timing"]["build_seconds"], 90)
        self.assertEqual(self.phase["timing"]["save_seconds"], 20)
        self.assertEqual(self.phase["timing"]["total_seconds"], 120)
        self.assertEqual(self.phase["timing"]["workflow_seconds"], 150)

    def test_missing_post_step_cannot_produce_a_complete_comparison(self):
        self.job["steps"].pop()
        with self.assertRaisesRegex(ValueError, "Missing completed publication"):
            self.apply()

    def test_rolling_compiler_only_runs_need_no_magic_archive_save(self):
        self.phase.update(strategy="runs-on-cache", phase="commit", lane="rolling", variant="step05-warm", cache={"cache_variant": "sccache-only"})
        self.job["name"] = "step05 (runs-on-cache) / runs-on-cache warm"
        self.job["steps"].pop()
        self.apply()
        self.assertEqual(self.phase["timing"]["save_seconds"], 0)

    def test_failed_job_cannot_be_reported_as_completed_success(self):
        self.job["conclusion"] = "failure"
        with self.assertRaisesRegex(ValueError, "Expected one successful completed job"):
            self.apply()

    def test_duplicate_job_names_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.json"
            path.write_text(json.dumps([{"jobs": [self.job, copy.deepcopy(self.job)]}]))
            with self.assertRaisesRegex(ValueError, "Expected one successful completed job"):
                REPORT["apply_completed_job_timings"]([self.phase], str(path))


if __name__ == "__main__":
    unittest.main()
