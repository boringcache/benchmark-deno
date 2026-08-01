#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


FRESHNESS_PATTERN = re.compile(
    r"Cargo source freshness restored: "
    r"(?P<reused>\d+) unchanged, (?P<changed>\d+) changed/new; "
    r"directories: (?P<reused_directories>\d+) unchanged, "
    r"(?P<changed_directories>\d+) changed/new"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--target-root", required=True)
    parser.add_argument("--cli-log", required=True)
    parser.add_argument("--cargo-messages", required=True)
    parser.add_argument("--native-evidence-dir", required=True)
    parser.add_argument("--inspect-json", required=True)
    parser.add_argument("--transport", choices=("chunks", "monolith"), required=True)
    parser.add_argument("--elapsed-seconds", type=int, required=True)
    parser.add_argument("--target-size-bytes", type=int, required=True)
    parser.add_argument("--cli-version", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def git_index(source_root: Path) -> dict[str, str]:
    result = subprocess.run(
        ["git", "-C", str(source_root), "ls-files", "--stage", "-z"],
        check=True,
        capture_output=True,
    )
    entries: dict[str, str] = {}
    for record in result.stdout.split(b"\0"):
        if not record:
            continue
        identity, raw_path = record.split(b"\t", 1)
        identity_text = identity.decode("utf-8")
        if identity_text.startswith("160000 "):
            continue
        entries[raw_path.hex()] = identity_text
    return entries


def mtime_ns(value: dict[str, Any]) -> int:
    return int(value["seconds"]) * 1_000_000_000 + int(value["nanoseconds"])


def verify_source_freshness(
    source_root: Path, target_root: Path, cli_log: Path
) -> dict[str, int]:
    manifest_path = target_root / ".boringcache" / "cargo-freshness-v2.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("format_version") != 2:
        raise ValueError("Cargo freshness descriptor is not version 2")
    if manifest.get("source_identity") != "git-index-v2":
        raise ValueError("Cargo freshness descriptor has an unexpected source identity")

    stored = {entry["path_bytes_hex"]: entry for entry in manifest["entries"]}
    current = git_index(source_root)
    ceiling = mtime_ns(manifest["artifact_mtime_ceiling"])
    reused = 0
    changed = 0
    mismatches: list[str] = []
    for path_hex, identity in current.items():
        raw_path = bytes.fromhex(path_hex)
        relative_path = os.fsdecode(raw_path)
        path = source_root / relative_path
        stored_entry = stored.get(path_hex)
        if stored_entry and stored_entry["content_identity"] == identity:
            reused += 1
            actual_mtime = path.lstat().st_mtime_ns
            expected_mtime = mtime_ns(stored_entry["mtime"])
            if actual_mtime != expected_mtime:
                mismatches.append(
                    "unchanged mtime differs: "
                    f"{relative_path} (actual={actual_mtime}, expected={expected_mtime})"
                )
        else:
            changed += 1
            if path.lstat().st_mtime_ns <= ceiling:
                mismatches.append(
                    f"changed source is not newer than target: {relative_path}"
                )

    if mismatches:
        raise ValueError("; ".join(mismatches[:10]))
    if reused == 0 or changed == 0:
        raise ValueError(
            f"Expected both reused and changed rolling sources, got {reused=} {changed=}"
        )

    reported = [
        {key: int(value) for key, value in match.groupdict().items()}
        for match in FRESHNESS_PATTERN.finditer(cli_log.read_text())
    ]
    matching_report = next(
        (
            item
            for item in reported
            if item["reused"] == reused and item["changed"] == changed
        ),
        None,
    )
    if matching_report is None:
        raise ValueError(
            f"CLI freshness report does not match filesystem proof: {reused=} {changed=}"
        )
    if matching_report["reused_directories"] == 0:
        raise ValueError("CLI restored zero unchanged source directories")
    return matching_report


def parse_cargo_messages(path: Path) -> dict[str, int | bool]:
    fresh: set[str] = set()
    rebuilt: set[str] = set()
    build_finished = False
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Cargo stdout line {line_number} is not JSON: {line!r}"
            ) from error
        if message.get("reason") == "compiler-artifact":
            label = (
                f"{message.get('package_id')}:{message.get('target', {}).get('name')}"
            )
            (fresh if message.get("fresh") is True else rebuilt).add(label)
        elif message.get("reason") == "build-finished":
            build_finished = build_finished or message.get("success") is True
    if not build_finished or not fresh or not rebuilt:
        raise ValueError(
            "Cargo evidence must contain a successful build with fresh and rebuilt targets"
        )
    return {
        "fresh_targets": len(fresh),
        "rebuilt_targets": len(rebuilt),
        "build_finished": True,
    }


def verify_sccache(directory: Path) -> dict[str, int | float]:
    evidence_paths = sorted(directory.glob("*.json"))
    if len(evidence_paths) < 2:
        raise ValueError("Expected native sccache evidence from both Cargo invocations")
    totals: dict[str, int] = {
        "compile_requests": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "cache_errors": 0,
        "cache_read_errors": 0,
        "cache_write_errors": 0,
        "cache_timeouts": 0,
    }
    for path in evidence_paths:
        evidence = json.loads(path.read_text())
        if evidence.get("schema_version") != "native_tool_evidence.v1":
            raise ValueError(f"Unexpected native evidence schema in {path}")
        if evidence.get("tool") != "sccache":
            raise ValueError(f"Unexpected native evidence tool in {path}")
        for key in totals:
            totals[key] += int(evidence.get(key) or 0)
    attempts = totals["cache_hits"] + totals["cache_misses"]
    if totals["compile_requests"] == 0 or attempts == 0:
        raise ValueError(
            "The rolling build produced no native sccache request evidence"
        )
    if totals["cache_errors"] or totals["cache_read_errors"] or totals["cache_timeouts"]:
        raise ValueError(
            "The rolling build reported sccache request errors, read errors, or timeouts"
        )
    return {
        **totals,
        "hit_rate": round(totals["cache_hits"] * 100 / attempts, 2)
        if attempts
        else 0.0,
    }


def verify_archive(path: Path, transport: str) -> dict[str, Any]:
    inspection = json.loads(path.read_text())
    entry = inspection["entry"]
    if entry.get("status") != "ready":
        raise ValueError("Target cache is not ready")
    if not entry.get("server_signed"):
        raise ValueError("Target cache root is not server signed")
    if transport == "chunks":
        if entry.get("storage_mode") != "cas":
            raise ValueError("Chunked target is not stored on CAS")
        if entry.get("cas_layout") != "archive-chunks-v1":
            raise ValueError("Chunked target has the wrong CAS layout")
        if not entry.get("storage_verified"):
            raise ValueError("Chunked target storage is not verified")
        if int(entry.get("blob_count") or 0) < 2:
            raise ValueError("Chunked target did not produce multiple blobs")
    else:
        if entry.get("storage_mode") != "archive":
            raise ValueError("Monolithic control did not use archive storage")
        if entry.get("cas_layout") is not None:
            raise ValueError("Monolithic control unexpectedly has a CAS layout")
    return {
        "storage_mode": entry.get("storage_mode"),
        "cas_layout": entry.get("cas_layout"),
        "manifest_root_digest": entry.get("manifest_root_digest"),
        "stored_size_bytes": entry.get("stored_size_bytes"),
        "blob_count": entry.get("blob_count"),
        "server_signed": entry.get("server_signed"),
        "storage_verified": entry.get("storage_verified"),
    }


def main() -> int:
    args = parse_args()
    source_root = Path(args.source_root).resolve()
    target_root = Path(args.target_root).resolve()
    payload = {
        "schema_version": "deno_boringcache_cargo.v1",
        "transport": args.transport,
        "cli_version": args.cli_version,
        "elapsed_seconds": args.elapsed_seconds,
        "target_size_bytes": args.target_size_bytes,
        "archive": verify_archive(Path(args.inspect_json), args.transport),
        "freshness": verify_source_freshness(
            source_root, target_root, Path(args.cli_log)
        ),
        "cargo": parse_cargo_messages(Path(args.cargo_messages)),
        "sccache": verify_sccache(Path(args.native_evidence_dir)),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
