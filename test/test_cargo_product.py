from __future__ import annotations

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
                "case \"$*\" in\n"
                "  'api repos/denoland/deno --jq .default_branch') echo main ;;\n"
                f"  'api repos/denoland/deno/compare/{current}...main') "
                f"echo '{{\"status\":\"ahead\",\"commits\":[{{\"sha\":\"{following}\"}}]}}' ;;\n"
                f"  'api repos/denoland/deno/commits/{following} --jq .parents[0].sha // empty') echo {current} ;;\n"
                "  *) echo \"Unexpected gh call: $*\" >&2; exit 1 ;;\n"
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
            settings = dict(line.split("=", 1) for line in source.read_text().splitlines())

        self.assertEqual(settings["DENO_BASE_SHA"], current)
        self.assertEqual(settings["DENO_HEAD_SHA"], following)
        self.assertEqual(settings["DENO_RUST_VERSION"], "1.95.0")


class CargoProductWorkflowTest(unittest.TestCase):
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

        self.assertIn('"-p",', desktop)
        self.assertIn('"denort_desktop",', desktop)
        self.assertNotIn('"--bin"', desktop)
        self.assertIn('tag = "deno-cargo-target-local"', desktop)
        self.assertIn('tag = "deno-rust-cache-local"', desktop)
        self.assertIn('"--bin", "deno"', config)
        self.assertNotIn('"-p", "denort_desktop"', config)

    def test_linux_release_recipe_matches_upstream_contract(self):
        contract = (ROOT / "scripts/deno-release-recipe.env").read_text()
        linux_setup = (ROOT / "scripts/setup-deno-linux.sh").read_text()
        frame_setup = (
            ROOT / "scripts/configure-deno-frame-pointers.sh"
        ).read_text()
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
        self.assertIn("DENO_FRAME_POINTER_RUSTFLAGS=", contract)
        config = (ROOT / ".boringcache.toml").read_text()
        self.assertIn('"-Zbuild-std=core,alloc,std,proc_macro,panic_abort"', config)
        self.assertIn('"--features=deno/panic-trace-frame-pointer"', config)
        self.assertEqual(config.count('"--bin"'), 3)
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

    def test_cargo_is_the_only_live_boringcache_rust_lifecycle(self):
        workflows = ROOT / ".github" / "workflows"
        workflow_text = "\n".join(
            path.read_text() for path in sorted(workflows.glob("*.yml"))
        )
        config = (ROOT / ".boringcache.toml").read_text()

        self.assertIn("[adapters.cargo]", config)
        self.assertIn('command = [', config)
        self.assertIn('"cargo", "build"', config)
        self.assertNotIn("[adapters.sccache]", config)
        self.assertNotIn("mode: sccache", workflow_text)
        self.assertEqual(workflow_text.count("uses: boringcache/one@"), 7)
        self.assertEqual(workflow_text.count("mode: cargo"), 7)
        self.assertEqual(
            {path.name for path in workflows.glob("*.yml")},
            {
                "deno-cargo-product.yml",
                "deno-cargo-rolling-chain.yml",
                "deno-rust-cache-proof.yml",
                "sync.yml",
            },
        )

    def test_product_uses_the_released_action_owned_lifecycle(self):
        workflow = (ROOT / ".github/workflows/deno-cargo-product.yml").read_text()
        dispatcher = (ROOT / ".github/workflows/deno-rust-cache-proof.yml").read_text()

        action = (
            "uses: boringcache/one@"
            "09e053620cda4d3472f26a3ddd181144a108e2c2 # v1.16.8"
        )
        self.assertEqual(workflow.count(action), 4)
        self.assertEqual(workflow.count("mode: cargo"), 4)
        self.assertEqual(workflow.count("trust-policy: publish"), 2)
        self.assertEqual(workflow.count("trust-policy: restore"), 2)
        self.assertEqual(workflow.count("target_cache_hit == false"), 1)
        self.assertEqual(workflow.count("target_cache_hit == true"), 2)
        self.assertEqual(workflow.count("cache_read_errors // 0) == 0"), 2)
        self.assertEqual(workflow.count("cache_write_errors // 0) == 0"), 1)
        self.assertEqual(workflow.count("cache_timeouts // 0) == 0"), 2)
        self.assertIn("In sccache READ_ONLY mode", workflow)
        self.assertIn("Build Deno release binaries through boringcache cargo", workflow)
        self.assertIn(
            "Restore and build Deno release binaries through boringcache cargo",
            workflow,
        )
        self.assertIn("boringcache_one_evidence.v1", workflow)
        self.assertNotIn("BORINGCACHE_ARCHIVE_GRAPH_WRITES", workflow)
        self.assertNotIn("DENO_BORINGCACHE_SKIP_", workflow)
        self.assertNotIn("run-deno-mtime-cache.js", workflow)
        self.assertNotIn("install-boringcache-cli.sh", workflow)
        self.assertEqual(workflow.count("install-sccache.sh 0.16.0"), 2)
        self.assertNotIn("inputs.cli_version", workflow)
        self.assertNotIn("fail-on-cache-miss", workflow)
        self.assertNotIn("boringcache save", workflow)
        self.assertNotIn("boringcache restore", workflow)
        self.assertIn("default: cargo-product", dispatcher)
        self.assertIn("- cargo-product", dispatcher)
        self.assertIn("uses: ./.github/workflows/deno-cargo-product.yml", dispatcher)
        self.assertNotIn("actions-cache", dispatcher)
        self.assertNotIn("full-target", dispatcher)
        self.assertNotIn("release-hybrid", dispatcher)

    def test_rolling_chain_preserves_the_published_archive_tag_identity(self):
        workflow = (ROOT / ".github/workflows/deno-cargo-rolling-chain.yml").read_text()
        dispatcher = (ROOT / ".github/workflows/deno-rust-cache-proof.yml").read_text()

        self.assertIn("archive_tag_suffix:", workflow)
        self.assertIn('"${{ inputs.archive_tag_suffix }}"', workflow)
        self.assertIn('BORINGCACHE_ARCHIVE_GRAPH_WRITES: "1"', workflow)
        self.assertIn('.entry.cas_layout == "archive-chunks-v1"', workflow)
        self.assertIn('.entry.blob_count > 1', workflow)
        self.assertEqual(workflow.count("mode: cargo"), 3)
        self.assertEqual(workflow.count("uses: boringcache/one@"), 3)
        self.assertNotIn("inputs.cli_version", workflow)
        self.assertNotIn("install-boringcache-cli.sh", workflow)
        self.assertEqual(workflow.count("install-sccache.sh 0.16.0"), 1)
        self.assertNotIn("fresh_compiler_artifacts", workflow)
        self.assertNotIn("restored_unchanged_sources", workflow)
        self.assertEqual(
            workflow.count(
                "deno-cargo-target-${{ inputs.cache_scope }}${{ inputs.archive_tag_suffix }}"
            ),
            2,
        )
        self.assertIn("inputs.archive_tag_suffix", dispatcher)

    def test_source_updates_run_a_fresh_product_cohort(self):
        dispatcher = (ROOT / ".github/workflows/deno-rust-cache-proof.yml").read_text()
        sync = (ROOT / ".github/workflows/sync.yml").read_text()
        source = (ROOT / "benchmark-source.env").read_text()

        self.assertIn('- "benchmark-source.env"', dispatcher)
        self.assertIn(
            "github.event_name == 'push' || inputs.experiment == 'cargo-product'",
            dispatcher,
        )
        self.assertIn(
            "github.event_name == 'workflow_dispatch' && inputs.experiment == 'cargo-rolling-chain'",
            dispatcher,
        )
        self.assertIn("DENO_ROLLING_CACHE_SCOPE=", source)
        self.assertIn("DENO_ROLLING_ARCHIVE_TAG_SUFFIX=", source)
        self.assertIn('cron: "*/30 * * * *"', sync)
        self.assertIn("advance-source-pair.sh benchmark-source.env DENO", sync)
        self.assertIn("Require the previous fresh product cohort to be green", sync)
        self.assertIn("steps.previous.outputs.ready == 'true'", sync)
        self.assertIn(
            "group: benchmark-deno-cargo-rolling-chain",
            (ROOT / ".github/workflows/deno-cargo-rolling-chain.yml").read_text(),
        )


if __name__ == "__main__":
    unittest.main()
