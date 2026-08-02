from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_verifier():
    path = ROOT / "scripts/verify_boringcache_cargo.py"
    spec = importlib.util.spec_from_file_location("verify_boringcache_cargo", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify_boringcache_cargo = load_verifier()


class CargoProductWorkflowTest(unittest.TestCase):
    def test_uses_one_released_cli_owned_lifecycle(self):
        workflow = (ROOT / ".github/workflows/deno-cargo-product.yml").read_text()
        dispatcher = (ROOT / ".github/workflows/deno-rust-cache-proof.yml").read_text()

        self.assertIn('DENO_USE_BORINGCACHE_CARGO: "1"', workflow)
        self.assertEqual(workflow.count("DENO_BORINGCACHE_CARGO_ACCESS: publish"), 1)
        self.assertEqual(workflow.count("DENO_BORINGCACHE_CARGO_ACCESS: consume"), 1)
        self.assertIn("Build and publish through boringcache cargo", workflow)
        self.assertIn("Restore and build through boringcache cargo", workflow)
        self.assertIn("default: v1.16.3", workflow)
        self.assertIn("verify_boringcache_cargo.py", workflow)
        self.assertIn("native_tool_evidence.v1", workflow)
        self.assertNotIn("BORINGCACHE_ARCHIVE_GRAPH_WRITES", workflow)
        self.assertNotIn("DENO_BORINGCACHE_SKIP_", workflow)
        self.assertNotIn("run-deno-mtime-cache.js", workflow)
        self.assertNotIn("uses: boringcache/one@", workflow)
        self.assertNotIn("boringcache save", workflow)
        self.assertNotIn("boringcache restore", workflow)
        self.assertIn("- cargo-product", dispatcher)
        self.assertIn("uses: ./.github/workflows/deno-cargo-product.yml", dispatcher)

    def test_each_cargo_invocation_uses_the_normal_product_lifecycle(self):
        release_build = (ROOT / "scripts/run-deno-release-build.sh").read_text()
        self.assertNotIn("DENO_BORINGCACHE_SKIP_SAVE", release_build)
        self.assertNotIn("DENO_BORINGCACHE_SKIP_RESTORE", release_build)

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

            def wrapped_args(access: str) -> list[str]:
                env = {
                    **os.environ,
                    "PATH": f"{bin_dir}:{os.environ['PATH']}",
                    "BORINGCACHE_ARGS_LOG": str(args_log),
                    "DENO_USE_BORINGCACHE_CARGO": "1",
                    "DENO_BORINGCACHE_CARGO_ACCESS": access,
                }
                subprocess.run(
                    [str(ROOT / "scripts/run-cargo-build.sh"), "--release"],
                    check=True,
                    env=env,
                )
                return args_log.read_text().splitlines()

            publish = wrapped_args("publish")
            consume = wrapped_args("consume")

        self.assertIn("--write", publish)
        self.assertIn("--read-only", consume)
        for arguments in (publish, consume):
            self.assertNotIn("--skip-save", arguments)
            self.assertNotIn("--skip-restore", arguments)

    def test_rolling_chain_preserves_the_published_archive_tag_identity(self):
        workflow = (ROOT / ".github/workflows/deno-cargo-rolling-chain.yml").read_text()
        dispatcher = (ROOT / ".github/workflows/deno-rust-cache-proof.yml").read_text()

        self.assertIn("archive_tag_suffix:", workflow)
        self.assertIn('"${{ inputs.archive_tag_suffix }}"', workflow)
        self.assertEqual(
            workflow.count(
                "deno-cargo-target-${{ inputs.cache_scope }}${{ inputs.archive_tag_suffix }}"
            ),
            2,
        )
        self.assertIn("archive_tag_suffix: ${{ inputs.archive_tag_suffix }}", dispatcher)


class CargoProductEvidenceTest(unittest.TestCase):
    def test_rejects_non_json_text_on_cargo_stdout(self):
        with tempfile.TemporaryDirectory() as directory:
            messages = Path(directory) / "cargo.jsonl"
            messages.write_text(
                "[boringcache] restoring target\n"
                '{"reason":"build-finished","success":true}\n'
            )
            with self.assertRaisesRegex(ValueError, "Cargo stdout line 1 is not JSON"):
                verify_boringcache_cargo.parse_cargo_messages(messages)

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
            unchanged.write_text("unchanged\n")
            changed.write_text("before\n")
            subprocess.run(
                ["git", "-C", str(source), "add", "unchanged.rs", "changed.rs"],
                check=True,
            )
            base_index = verify_boringcache_cargo.git_index(source)
            unchanged_ns = 1_700_000_000_123_456_789
            changed_ns = 1_800_000_000_123_456_789
            os.utime(unchanged, ns=(unchanged_ns, unchanged_ns))
            changed.write_text("after\n")
            subprocess.run(["git", "-C", str(source), "add", "changed.rs"], check=True)
            os.utime(changed, ns=(changed_ns, changed_ns))

            entries = [
                {
                    "path_bytes_hex": path_hex,
                    "content_identity": identity,
                    "mtime": {
                        "seconds": unchanged_ns // 1_000_000_000,
                        "nanoseconds": unchanged_ns % 1_000_000_000,
                    },
                }
                for path_hex, identity in base_index.items()
            ]
            manifest = {
                "format_version": 2,
                "source_identity": "git-index-v2",
                "artifact_mtime_ceiling": {"seconds": 1_750_000_000, "nanoseconds": 0},
                "entries": entries,
                "directories": [],
            }
            (target / ".boringcache/cargo-freshness-v2.json").write_text(
                json.dumps(manifest)
            )
            log = root / "cli.log"
            log.write_text(
                "[boringcache] Cargo source freshness restored: 1 unchanged, "
                "1 changed/new; directories: 1 unchanged, 1 changed/new\n"
            )

            evidence = verify_boringcache_cargo.verify_source_freshness(
                source, target, log
            )
            self.assertEqual(evidence["reused"], 1)
            self.assertEqual(evidence["changed"], 1)

    def test_verifies_product_selected_archive_and_sccache_health(self):
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
                            "cache_errors": 0,
                            "cache_read_errors": 0,
                            "cache_write_errors": 0,
                            "cache_timeouts": 0,
                        }
                    )
                )

            archive = verify_boringcache_cargo.verify_archive(inspection)
            sccache = verify_boringcache_cargo.verify_sccache(native)
            self.assertEqual(archive["cas_layout"], "archive-chunks-v1")
            self.assertEqual(sccache["cache_hits"], 8)
            self.assertEqual(sccache["hit_rate"], 80.0)


if __name__ == "__main__":
    unittest.main()
