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
            settings = dict(
                line.split("=", 1) for line in source.read_text().splitlines()
            )

        self.assertEqual(settings["DENO_BASE_SHA"], current)
        self.assertEqual(settings["DENO_HEAD_SHA"], following)
        self.assertEqual(settings["DENO_RUST_VERSION"], "1.95.0")


class DenoReleaseWorkloadTest(unittest.TestCase):
    def test_cargo_product_uses_reusable_dependency_archives(self):
        config = (ROOT / ".boringcache.toml").read_text()
        scope_script = (ROOT / "scripts/scope-boringcache-run.sh").read_text()

        for entry in (
            "cargo-registry-cache",
            "cargo-registry-index",
            "cargo-git-db",
            "cargo-target",
        ):
            self.assertIn(f'"{entry}"', config)
            self.assertIn(f"deno-{entry}", scope_script)

        self.assertNotIn("[entries.cargo-registry]", config)
        self.assertNotIn("[entries.cargo-git]", config)

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

    def test_linux_release_recipe_matches_the_pinned_workload(self):
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
        config = (ROOT / ".boringcache.toml").read_text()
        self.assertIn('"-Zbuild-std=core,alloc,std,proc_macro,panic_abort"', config)
        self.assertIn('"--features=deno/panic-trace-frame-pointer"', config)
        self.assertEqual(config.count('"--bin"'), 3)
        self.assertIn("select-deno-cargo-phase.py desktop", workflows)
        self.assertIn("/tmp/memfd_create_shim.o", linux_setup)
        self.assertIn("$(pwd)/target/release/lto-cache", linux_setup)
        self.assertIn("--retry-all-errors", linux_setup)
        self.assertIn("--proto-redir '=https'", linux_setup)
        self.assertIn('echo "RUSTC_BOOTSTRAP=1"', frame_setup)
        self.assertIn("${DENO_FRAME_POINTER_RUSTFLAGS}", frame_setup)
        self.assertEqual(
            workflows.count(
                "uses: dsherret/rust-toolchain-file@3551321aa44dd44a0393eb3b6bdfbc5d25ecf621"
            ),
            3,
        )
        self.assertEqual(workflows.count("verify-deno-release-recipe.py upstream"), 3)

    def test_source_updates_keep_advancing_the_rolling_workload(self):
        rolling = (ROOT / ".github/workflows/deno-cargo-rolling-chain.yml").read_text()
        sync = (ROOT / ".github/workflows/sync.yml").read_text()
        source = dict(
            line.split("=", 1)
            for line in (ROOT / "benchmark-source.env").read_text().splitlines()
        )

        self.assertNotIn("DENO_ROLLING_CACHE_SCOPE", source)
        self.assertIn('cron: "2,32 * * * *"', sync)
        self.assertIn("advance-source-pair.sh benchmark-source.env DENO", sync)
        self.assertIn('paths: ["benchmark-source.env"]', rolling)
        self.assertIn('echo "cache_scope=rolling-${ref_slug}"', rolling)
        self.assertIn("group: benchmark-deno-cargo-rolling-chain", rolling)


if __name__ == "__main__":
    unittest.main()
