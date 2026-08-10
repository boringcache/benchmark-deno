from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SourceSyncTest(unittest.TestCase):
    def test_advances_exactly_one_upstream_commit(self):
        current = "a" * 40
        following = "b" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "benchmark-source.env"
            source.write_text(
                "DENO_SOURCE_REPOSITORY=denoland/deno\n"
                f"DENO_BASE_SHA={'0' * 40}\n"
                f"DENO_HEAD_SHA={current}\n"
                "DENO_RUST_VERSION=1.95.0\n"
            )
            bin_dir = root / "bin"
            bin_dir.mkdir()
            gh = bin_dir / "gh"
            gh.write_text(
                "#!/usr/bin/env bash\n"
                'case "$*" in\n'
                "  'api repos/denoland/deno --jq .default_branch') echo main ;;\n"
                f"  'api repos/denoland/deno/compare/{current}...main') "
                f'echo \'{{"status":"ahead","commits":[{{"sha":"{following}"}}]}}\' ;;\n'
                f"  'api repos/denoland/deno/commits/{following} --jq .parents[0].sha // empty') echo {current} ;;\n"
                '  *) echo "Unexpected gh call: $*" >&2; exit 1 ;;\n'
                "esac\n"
            )
            gh.chmod(0o755)

            subprocess.run(
                [
                    str(ROOT / "scripts/advance-source-pair.sh"),
                    str(source),
                    "DENO",
                ],
                check=True,
                env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
            )
            settings = dict(
                line.split("=", 1) for line in source.read_text().splitlines()
            )

        self.assertEqual(settings["DENO_BASE_SHA"], current)
        self.assertEqual(settings["DENO_HEAD_SHA"], following)
        self.assertEqual(settings["DENO_RUST_VERSION"], "1.95.0")


class DenoReleaseWorkloadTest(unittest.TestCase):
    def test_phase_selector_keeps_the_two_upstream_cargo_commands_distinct(self):
        config = (ROOT / ".boringcache.toml").read_text()
        with tempfile.TemporaryDirectory() as directory:
            temporary_config = Path(directory) / ".boringcache.toml"
            temporary_config.write_text(config)
            subprocess.run(
                [
                    str(ROOT / "scripts/select-deno-cargo-phase.py"),
                    "desktop",
                    str(temporary_config),
                ],
                check=True,
            )
            desktop = temporary_config.read_text()

        self.assertIn('"denort_desktop",', desktop)
        self.assertNotIn('"--bin"', desktop)
        self.assertIn('"--bin", "deno"', config)
        self.assertNotIn('"-p", "denort_desktop"', config)

    def test_linux_release_recipe_matches_every_committed_plan(self):
        contract = (ROOT / "scripts/deno-release-recipe.env").read_text()
        linux_setup = (ROOT / "scripts/setup-deno-linux.sh").read_text()
        frame_setup = (ROOT / "scripts/configure-deno-frame-pointers.sh").read_text()
        workflows = "\n".join(
            path.read_text()
            for path in (
                ROOT / ".github/workflows/deno-cargo-product.yml",
                ROOT / ".github/workflows/deno-cargo-rolling-chain.yml",
            )
        )

        self.assertIn(
            "DENO_BUILD_STD_ARG=-Zbuild-std=core,alloc,std,proc_macro,panic_abort",
            contract,
        )
        self.assertIn(
            "DENO_PANIC_TRACE_FEATURE=deno/panic-trace-frame-pointer", contract
        )
        primary_plans = [
            ROOT / ".boringcache.toml",
            *ROOT.glob("plans/*/primary/.boringcache.toml"),
        ]
        desktop_plans = list(ROOT.glob("plans/*/desktop/.boringcache.toml"))
        self.assertEqual(len(primary_plans), 4)
        self.assertEqual(len(desktop_plans), 3)
        for path in primary_plans:
            config = path.read_text()
            self.assertIn('"-Zbuild-std=core,alloc,std,proc_macro,panic_abort"', config)
            self.assertIn('"--features=deno/panic-trace-frame-pointer"', config)
            self.assertEqual(config.count('"--bin"'), 3)
        for path in desktop_plans:
            config = path.read_text()
            self.assertIn('"-Zbuild-std=core,alloc,std,proc_macro,panic_abort"', config)
            self.assertIn('"denort_desktop"', config)
            self.assertNotIn('"--bin"', config)
        self.assertIn("select-deno-cargo-phase.py desktop", workflows)
        self.assertIn("/tmp/memfd_create_shim.o", linux_setup)
        self.assertIn("$(pwd)/target/release/lto-cache", linux_setup)
        self.assertIn('echo "RUSTC_BOOTSTRAP=1"', frame_setup)
        self.assertIn("${DENO_FRAME_POINTER_RUSTFLAGS}", frame_setup)
        self.assertEqual(
            workflows.count(
                "uses: dsherret/rust-toolchain-file@3551321aa44dd44a0393eb3b6bdfbc5d25ecf621"
            ),
            3,
        )
        self.assertEqual(workflows.count("verify-deno-release-recipe.py upstream"), 3)

    def test_cli_plans_own_independent_layer_selection(self):
        root_plan = (ROOT / ".boringcache.toml").read_text()
        product_workflow = (
            ROOT / ".github/workflows/deno-cargo-product.yml"
        ).read_text()
        rolling_workflow = (
            ROOT / ".github/workflows/deno-cargo-rolling-chain.yml"
        ).read_text()

        self.assertIn("[adapters.sccache]", root_plan)
        self.assertIn('compiler-cache = "sccache"', root_plan)
        self.assertIn('tag = "deno-rust-cache-rolling-main"', root_plan)
        for phase in ("primary", "desktop"):
            sccache_only = (
                ROOT / f"plans/sccache-only/{phase}/.boringcache.toml"
            ).read_text()
            combined = (ROOT / f"plans/combined/{phase}/.boringcache.toml").read_text()
            self.assertIn('entries = ["cargo-registry"]', sccache_only)
            self.assertIn('entries = ["cargo-registry", "cargo-target"]', combined)
            self.assertIn('compiler-cache = "sccache"', sccache_only)
            self.assertIn('compiler-cache = "sccache"', combined)

        self.assertIn(
            'activate-cargo-plan.sh "${{ matrix.lane }}" primary', product_workflow
        )
        self.assertEqual(product_workflow.count("working-directory: upstream"), 4)
        self.assertNotIn("scope-boringcache-run.sh", product_workflow)
        self.assertNotIn("scope-boringcache-run.sh", rolling_workflow)
        self.assertNotIn("cache_scope", rolling_workflow)

    def test_source_updates_keep_advancing_the_rolling_workload(self):
        sync = (ROOT / ".github/workflows/sync.yml").read_text()
        rolling = (ROOT / ".github/workflows/deno-cargo-rolling-chain.yml").read_text()
        source = dict(
            line.split("=", 1)
            for line in (ROOT / "benchmark-source.env").read_text().splitlines()
        )

        self.assertEqual(source["DENO_SOURCE_REPOSITORY"], "denoland/deno")
        self.assertRegex(source["DENO_BASE_SHA"], r"^[0-9a-f]{40}$")
        self.assertRegex(source["DENO_HEAD_SHA"], r"^[0-9a-f]{40}$")
        self.assertIn('cron: "2,32 * * * *"', sync)
        self.assertIn("advance-source-pair.sh benchmark-source.env DENO", sync)
        self.assertIn('paths: ["benchmark-source.env"]', rolling)


class CargoEvidenceSummaryTest(unittest.TestCase):
    def test_native_hit_rate_is_already_a_percentage(self):
        evidence = {
            "phases": {
                "restore": {
                    "mode_evidence": {
                        "elapsed_seconds": 12.4,
                        "target_cache_hit": True,
                        "native_tool": {
                            "compile_requests": 101,
                            "compile_requests_executed": 100,
                            "cache_hits": 96,
                            "cache_misses": 4,
                            "hit_rate": 96.0,
                        },
                    }
                }
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(json.dumps(evidence))
            result = subprocess.run(
                [
                    str(ROOT / "scripts/summarize-cargo-evidence.py"),
                    "combined",
                    str(path),
                ],
                check=True,
                text=True,
                capture_output=True,
            )

        self.assertIn("96.0% hit rate", result.stdout)
        self.assertNotIn("9600", result.stdout)


if __name__ == "__main__":
    unittest.main()
