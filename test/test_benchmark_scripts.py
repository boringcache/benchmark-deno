from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
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
snapshot_target_state = load_script("snapshot_target_state.py")
compare_target_snapshots = load_script("compare_target_snapshots.py")
verify_boringcache_cargo = load_script("verify_boringcache_cargo.py")
render_cargo_transport_comparison = load_script(
    "render_cargo_transport_comparison.py"
)


class CargoArchiveChunksWorkflowTest(unittest.TestCase):
    def test_compares_only_the_generic_archive_transport(self):
        workflow = (
            ROOT / ".github/workflows/deno-cargo-archive-chunks.yml"
        ).read_text()

        self.assertIn("transport: chunks", workflow)
        self.assertIn("transport: monolith", workflow)
        self.assertIn("DENO_USE_BORINGCACHE_CARGO: \"1\"", workflow)
        self.assertIn("DENO_BORINGCACHE_CARGO_ACCESS: publish", workflow)
        self.assertIn("DENO_BORINGCACHE_CARGO_ACCESS: consume", workflow)
        self.assertIn("BORINGCACHE_ARCHIVE_GRAPH_WRITES", workflow)
        self.assertIn("Require a clean product starting point", workflow)
        self.assertIn(
            "Build and publish the monolith through boringcache cargo", workflow
        )
        self.assertIn(
            "Reuse and publish the same target as chunks through boringcache cargo",
            workflow,
        )
        self.assertIn('storage_mode == "archive"', workflow)
        self.assertNotIn("run-deno-mtime-cache.js", workflow)
        self.assertNotIn("seed_target_tag", workflow)
        self.assertNotIn("seed_registry_tag", workflow)
        self.assertNotIn("boringcache restore", workflow)
        self.assertNotIn("uses: actions/cache/restore@", workflow)
        self.assertEqual(workflow.count("--exclude-prefix .boringcache"), 2)
        self.assertIn("cmp -s", workflow)
        self.assertNotIn(
            '[[ "${{ steps.target-monolith.outputs.target_size_bytes }}" ==',
            workflow,
        )
        self.assertIn(
            "uses: boringcache/one@8294be671cd5a2b73638df1b8e1e240df888297e",
            workflow,
        )
        self.assertEqual(workflow.count("uses: boringcache/one@"), 2)
        self.assertIn("cache-profiles: rust-toolchain", workflow)
        self.assertIn("setup: mise", workflow)
        self.assertNotIn("uses: dtolnay/rust-toolchain@", workflow)
        dispatcher = (ROOT / ".github/workflows/deno-rust-cache-proof.yml").read_text()
        self.assertIn("- cargo-archive-chunks", dispatcher)
        self.assertNotIn("cargo_seed_sccache_run_id:", dispatcher)
        self.assertNotIn("cargo_seed_target_tag:", dispatcher)
        self.assertNotIn("cargo_seed_registry_tag:", dispatcher)
        self.assertNotIn("source_run_id:", workflow)
        self.assertNotIn("SOURCE_RUN_ID", workflow)
        self.assertIn(
            "uses: ./.github/workflows/deno-cargo-archive-chunks.yml", dispatcher
        )

    def test_uses_an_exact_canary_and_native_product_evidence(self):
        workflow = (
            ROOT / ".github/workflows/deno-cargo-archive-chunks.yml"
        ).read_text()

        self.assertIn("cli-version: ${{ inputs.cli_version }}", workflow)
        self.assertIn("install-sccache.sh 0.16.0", workflow)
        self.assertIn("verify_boringcache_cargo.py", workflow)
        self.assertIn("Require the current base sccache seed", workflow)
        self.assertIn(
            'sccache_tag="deno-rust-cache-r${GITHUB_RUN_ID}-a${GITHUB_RUN_ATTEMPT}"',
            workflow,
        )
        self.assertIn('.kv_entry_count > 0', workflow)
        self.assertIn('test ! -e upstream/target', workflow)
        self.assertIn('test -x upstream/target/release/deno', workflow)

    def test_rust_toolchain_archive_matches_the_pinned_source_version(self):
        source = dict(
            line.split("=", 1)
            for line in (ROOT / "benchmark-source.env").read_text().splitlines()
            if line
        )
        config = (ROOT / ".boringcache.toml").read_text()
        version = source["DENO_RUST_VERSION"]

        self.assertIn(
            f'tag = "deno-rust-toolchain-{version.replace(".", "-")}"', config
        )
        self.assertIn(
            f'path = "~/.local/share/mise/installs/rust/{version}"', config
        )
        self.assertIn('[profiles.rust-toolchain]\nentries = ["rust-toolchain"]', config)

    def test_release_build_uses_one_restore_and_saves_only_after_the_final_phase(self):
        release_build = (ROOT / "scripts/run-deno-release-build.sh").read_text()

        self.assertIn('DENO_BORINGCACHE_SKIP_SAVE=1', release_build)
        self.assertIn('DENO_BORINGCACHE_SKIP_RESTORE=1', release_build)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            args_log = root / "args.log"
            boringcache = bin_dir / "boringcache"
            boringcache.write_text(
                '#!/usr/bin/env bash\nprintf \'%s\\n\' "$@" > "$BORINGCACHE_ARGS_LOG"\n'
            )
            boringcache.chmod(0o755)

            def wrapped_args(access: str, **overrides: str) -> list[str]:
                env = {
                    **os.environ,
                    "PATH": f"{bin_dir}:{os.environ['PATH']}",
                    "BORINGCACHE_ARGS_LOG": str(args_log),
                    "DENO_USE_BORINGCACHE_CARGO": "1",
                    "DENO_BORINGCACHE_CARGO_ACCESS": access,
                    **overrides,
                }
                subprocess.run(
                    [str(ROOT / "scripts/run-cargo-build.sh"), "--release"],
                    check=True,
                    env=env,
                )
                return args_log.read_text().splitlines()

            primary_publish = wrapped_args(
                "publish", DENO_BORINGCACHE_SKIP_SAVE="1"
            )
            final_publish = wrapped_args(
                "publish", DENO_BORINGCACHE_SKIP_RESTORE="1"
            )
            primary_consume = wrapped_args("consume")
            final_consume = wrapped_args(
                "consume", DENO_BORINGCACHE_SKIP_RESTORE="1"
            )

        self.assertIn("--skip-save", primary_publish)
        self.assertNotIn("--skip-save", final_publish)
        self.assertNotIn("--skip-restore", primary_publish)
        self.assertIn("--skip-restore", final_publish)
        self.assertNotIn("--skip-restore", primary_consume)
        self.assertIn("--skip-restore", final_consume)
        self.assertIn("--read-only", primary_consume)
        self.assertEqual(final_consume[-2:], ["build", "--release"])


class BoringCacheCargoEvidenceTest(unittest.TestCase):
    def test_verifies_transported_source_mtimes_against_git_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            (target / ".boringcache").mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            unchanged = source / "unchanged.rs"
            changed = source / "changed.rs"
            symlink_target = source / "symlink-target.rs"
            symlink = source / "symlink.rs"
            unchanged.write_text("unchanged\n")
            changed.write_text("before\n")
            symlink_target.write_text("target\n")
            symlink.symlink_to(symlink_target.name)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(source),
                    "add",
                    "unchanged.rs",
                    "changed.rs",
                    "symlink.rs",
                ],
                check=True,
            )
            base_index = verify_boringcache_cargo.git_index(source)
            unchanged_ns = 1_700_000_000_123_456_789
            changed_ns = 1_800_000_000_123_456_789
            os.utime(unchanged, ns=(unchanged_ns, unchanged_ns))
            os.utime(
                symlink,
                ns=(unchanged_ns, unchanged_ns),
                follow_symlinks=False,
            )
            os.utime(
                symlink_target,
                ns=(changed_ns, changed_ns),
            )
            changed.write_text("after\n")
            subprocess.run(
                ["git", "-C", str(source), "add", "changed.rs"], check=True
            )
            os.utime(changed, ns=(changed_ns, changed_ns))

            entries = []
            for path_hex, identity in base_index.items():
                entries.append(
                    {
                        "path_bytes_hex": path_hex,
                        "content_identity": identity,
                        "mtime": {
                            "seconds": unchanged_ns // 1_000_000_000,
                            "nanoseconds": unchanged_ns % 1_000_000_000,
                        },
                    }
                )
            manifest = {
                "format_version": 2,
                "source_identity": "git-index-v2",
                "artifact_mtime_ceiling": {
                    "seconds": 1_750_000_000,
                    "nanoseconds": 0,
                },
                "entries": entries,
                "directories": [],
            }
            (target / ".boringcache/cargo-freshness-v2.json").write_text(
                json.dumps(manifest)
            )
            log = root / "cli.log"
            log.write_text(
                "[boringcache] Cargo source freshness restored: 2 unchanged, "
                "1 changed/new; directories: 1 unchanged, 1 changed/new\n"
            )

            evidence = verify_boringcache_cargo.verify_source_freshness(
                source, target, log
            )

            self.assertEqual(evidence["reused"], 2)
            self.assertEqual(evidence["changed"], 1)

    def test_verifies_signed_chunk_layout_and_native_sccache_hits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inspection = root / "inspect.json"
            inspection.write_text(
                json.dumps(
                    {
                        "entry": {
                            "status": "ready",
                            "storage_mode": "cas",
                            "cas_layout": "archive-chunks-v1",
                            "server_signed": True,
                            "storage_verified": True,
                            "blob_count": 4,
                            "stored_size_bytes": 1024,
                            "manifest_root_digest": "sha256:root",
                        }
                    }
                )
            )
            native = root / "native"
            native.mkdir()
            for phase in ("primary", "desktop"):
                (native / f"{phase}.json").write_text(
                    json.dumps(
                        {
                            "schema_version": "native_tool_evidence.v1",
                            "tool": "sccache",
                            "compile_requests": 5,
                            "cache_hits": 4,
                            "cache_misses": 1,
                            "cache_read_errors": 0,
                            "cache_write_errors": 1,
                            "cache_timeouts": 0,
                        }
                    )
                )

            archive = verify_boringcache_cargo.verify_archive(inspection, "chunks")
            sccache = verify_boringcache_cargo.verify_sccache(native)

            self.assertEqual(archive["cas_layout"], "archive-chunks-v1")
            self.assertEqual(sccache["cache_hits"], 8)
            self.assertEqual(sccache["hit_rate"], 80.0)

    def test_accepts_novel_rolling_sccache_misses_without_synthetic_prewarming(self):
        with tempfile.TemporaryDirectory() as directory:
            native = Path(directory)
            for phase in ("primary", "desktop"):
                (native / f"{phase}.json").write_text(
                    json.dumps(
                        {
                            "schema_version": "native_tool_evidence.v1",
                            "tool": "sccache",
                            "compile_requests": 6,
                            "cache_hits": 0,
                            "cache_misses": 3,
                            "cache_read_errors": 0,
                            "cache_write_errors": 0,
                            "cache_timeouts": 0,
                        }
                    )
                )

            sccache = verify_boringcache_cargo.verify_sccache(native)

            self.assertEqual(sccache["cache_hits"], 0)
            self.assertEqual(sccache["cache_misses"], 6)
            self.assertEqual(sccache["hit_rate"], 0.0)

    def test_comparison_formats_gibibytes_without_claiming_attribution(self):
        self.assertEqual(
            render_cargo_transport_comparison.gib(5 * 1024**3), "5.00 GiB"
        )


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

    def test_restores_the_same_actions_cache_version_and_prepares_cargo_bin(self):
        workflow = (
            ROOT / ".github/workflows/deno-release-sccache-target-cohort.yml"
        ).read_text()

        for pattern in (
            "!upstream/target/*/gn_out",
            "!upstream/target/*/gn_root",
            "!upstream/target/*/*.zip",
            "!upstream/target/*/*.tar.gz",
        ):
            self.assertEqual(workflow.count(pattern), 2)
        self.assertIn("Prepare exact Cargo bin restore destination", workflow)
        self.assertIn('find "${HOME}/.cargo/bin"', workflow)

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


class TargetTransportWorkflowTest(unittest.TestCase):
    def test_changes_only_the_target_transport(self):
        workflow = (
            ROOT / ".github/workflows/deno-release-target-transport-control.yml"
        ).read_text()

        self.assertIn("Actions target plus BoringCache sccache", workflow)
        self.assertIn("BoringCache target plus BoringCache sccache", workflow)
        self.assertEqual(workflow.count("run: ./scripts/configure-sccache-cohort.sh webdav"), 1)
        self.assertIn("cache_profile: sccache-only", workflow)
        self.assertIn("cache_profile: target-only", workflow)
        self.assertIn("Restore the same Cargo state through Actions/cache", workflow)
        self.assertIn("Save the shared Cargo Actions control archive", workflow)
        self.assertNotIn("configure-sccache-cohort.sh disk\n", workflow)
        self.assertNotIn("~/.cache/sccache\n          fail-on-cache-miss", workflow)

    def test_reuses_the_canonical_seed_without_another_cold_build(self):
        workflow = (
            ROOT / ".github/workflows/deno-release-target-transport-control.yml"
        ).read_text()

        self.assertIn("inputs.seed_run_id", workflow)
        self.assertIn("Derive the target-only Actions archive", workflow)
        self.assertEqual(workflow.count("./scripts/run-deno-build.sh"), 1)
        self.assertIn("snapshot_target_state.py", workflow)
        self.assertIn("compare_target_snapshots.py", workflow)
        self.assertIn("run_build:", workflow)
        self.assertIn("default: false", workflow)
        self.assertIn("if: inputs.run_build", workflow)

    def test_phase_writer_accepts_both_target_transport_strategies(self):
        self.assertTrue(
            {
                "actions-target-boringcache-sccache",
                "boringcache-target-boringcache-sccache",
            }.issubset(write_phase_result.STRATEGIES)
        )

    def test_uploads_expensive_raw_evidence_before_rendering(self):
        workflow = (
            ROOT / ".github/workflows/deno-release-target-transport-control.yml"
        ).read_text()

        raw_upload = workflow.index("Upload raw rolling-build evidence")
        result_writer = workflow.index("Write target transport result")
        self.assertLess(raw_upload, result_writer)


class TargetSnapshotTest(unittest.TestCase):
    def test_proves_target_contents_and_metadata_are_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            actions = root / "actions"
            boringcache = root / "boringcache"
            actions.mkdir()
            boringcache.mkdir()
            for target in (actions, boringcache):
                artifact = target / "release" / "artifact.rlib"
                artifact.parent.mkdir()
                artifact.write_bytes(b"same artifact")
                os.chmod(artifact, 0o640)
                os.utime(
                    artifact,
                    ns=(1_700_000_000_125_000_000, 1_700_000_000_125_000_000),
                )
                (target / "link").symlink_to("release/artifact.rlib")
                for path in (target / "release", target / "link"):
                    os.utime(
                        path,
                        ns=(
                            1_700_000_000_125_000_000,
                            1_700_000_000_125_000_000,
                        ),
                        follow_symlinks=False,
                    )

            left = snapshot_target_state.snapshot(actions)
            right = snapshot_target_state.snapshot(boringcache)
            comparison = compare_target_snapshots.compare(left, right)

            self.assertTrue(comparison["exact_match"])
            self.assertEqual(left["entries_sha256"], right["entries_sha256"])

    def test_can_exclude_transport_metadata_from_the_target_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            artifact = target / "release" / "artifact.rlib"
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes(b"compiled payload")
            metadata = target / ".boringcache" / "cargo-freshness-v2.json"
            metadata.parent.mkdir()
            metadata.write_text('{"generation":1}')

            unfiltered_before = snapshot_target_state.snapshot(target)
            before = snapshot_target_state.snapshot(
                target, (Path(".boringcache"),)
            )
            metadata.write_text('{"generation":22}')
            unfiltered_after = snapshot_target_state.snapshot(target)
            after = snapshot_target_state.snapshot(
                target, (Path(".boringcache"),)
            )

            self.assertEqual(before, after)
            self.assertEqual(before["excluded_prefixes"], [".boringcache"])
            self.assertNotEqual(
                unfiltered_before["entries_sha256"],
                unfiltered_after["entries_sha256"],
            )

    def test_rejects_unsafe_exclude_prefixes(self):
        for value in ("", ".", "..", "../target", "/tmp/target"):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    snapshot_target_state.relative_prefix(value)

    def test_names_the_target_entry_that_differs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            actions = root / "actions"
            boringcache = root / "boringcache"
            actions.mkdir()
            boringcache.mkdir()
            (actions / "artifact").write_text("actions")
            (boringcache / "artifact").write_text("boringcache")

            comparison = compare_target_snapshots.compare(
                snapshot_target_state.snapshot(actions),
                snapshot_target_state.snapshot(boringcache),
            )

            self.assertFalse(comparison["exact_match"])
            self.assertEqual(comparison["different_entries_count"], 1)
            self.assertEqual(comparison["differences"][0]["path"], "artifact")
            self.assertIn("sha256", comparison["differences"][0]["fields"])


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

    def test_reports_a_different_hosted_runner_cpu_without_claiming_attribution(self):
        baseline = {
            "benchmark": "deno-release-rust-cache",
            "strategy": "actions-cache",
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
            "strategy": "boringcache-target-only",
            "runner": {
                **baseline["runner"],
                "hardware": {
                    **baseline["runner"]["hardware"],
                    "cpu_model": "Intel Xeon Platinum 8370C",
                },
            },
        }

        payload = compare_rolling_controls.compare(baseline, candidate, "Control")
        markdown = compare_rolling_controls.render_markdown(payload)

        self.assertFalse(payload["comparability"]["cpu_model_matched"])
        self.assertIn("different CPU models", markdown)
        self.assertNotIn("Candidate saved", markdown)


if __name__ == "__main__":
    unittest.main()
