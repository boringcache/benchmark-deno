#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "rust_target_state.v1"
STABLE_FLOOR_BYTES = 1024 * 1024
STABLE_FRACTION = 0.001


def snapshot(root: Path, source_sha: str = "") -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"Cargo target root is not a directory: {root}")

    files = 0
    directories = 0
    symlinks = 0
    logical_bytes = 0
    allocated_bytes = 0
    pending = [root]

    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                metadata = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(metadata.st_mode):
                    symlinks += 1
                elif stat.S_ISDIR(metadata.st_mode):
                    directories += 1
                    pending.append(Path(entry.path))
                elif stat.S_ISREG(metadata.st_mode):
                    files += 1
                    logical_bytes += metadata.st_size
                    allocated_bytes += getattr(metadata, "st_blocks", 0) * 512

    return {
        "schema_version": SCHEMA_VERSION,
        "source_sha": source_sha,
        "root_name": root.name,
        "files": files,
        "directories": directories,
        "symlinks": symlinks,
        "logical_bytes": logical_bytes,
        "allocated_bytes": allocated_bytes,
    }


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    for label, payload in (("before", before), ("after", after)):
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"Unexpected {label} target state schema")

    byte_delta = after["logical_bytes"] - before["logical_bytes"]
    allocated_delta = after["allocated_bytes"] - before["allocated_bytes"]
    file_delta = after["files"] - before["files"]
    stable_limit = max(
        STABLE_FLOOR_BYTES,
        round(before["logical_bytes"] * STABLE_FRACTION),
    )
    if abs(byte_delta) <= stable_limit:
        classification = "stable"
    elif byte_delta > 0:
        classification = "growing"
    else:
        classification = "shrinking"

    percent = None
    if before["logical_bytes"]:
        percent = round((byte_delta * 100) / before["logical_bytes"], 4)

    return {
        "schema_version": "rust_target_growth.v1",
        "classification": classification,
        "stable_limit_bytes": stable_limit,
        "logical_bytes_before": before["logical_bytes"],
        "logical_bytes_after": after["logical_bytes"],
        "logical_bytes_delta": byte_delta,
        "logical_bytes_delta_percent": percent,
        "allocated_bytes_before": before["allocated_bytes"],
        "allocated_bytes_after": after["allocated_bytes"],
        "allocated_bytes_delta": allocated_delta,
        "files_before": before["files"],
        "files_after": after["files"],
        "files_delta": file_delta,
        "before": before,
        "after": after,
    }


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure Cargo target size and parent-to-successor growth."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot_parser = subparsers.add_parser("snapshot")
    snapshot_parser.add_argument("--root", required=True, type=Path)
    snapshot_parser.add_argument("--output", required=True, type=Path)
    snapshot_parser.add_argument("--source-sha", default="")

    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("--before", required=True, type=Path)
    compare_parser.add_argument("--after", required=True, type=Path)
    compare_parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "snapshot":
        payload = snapshot(args.root, args.source_sha)
    else:
        payload = compare(read_json(args.before), read_json(args.after))
    write_json(args.output, payload)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
