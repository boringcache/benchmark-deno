#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--mtime-before", required=True)
    parser.add_argument("--mtime-after", required=True)
    parser.add_argument("--mtime-log", required=True)
    parser.add_argument("--cargo-messages", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def load_mtime_cache(path: Path) -> dict[str, float]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict) or not payload:
        raise ValueError(f"mtime cache is empty or invalid: {path}")
    return {str(key): float(value) for key, value in payload.items()}


def parse_mtime_stats(path: Path) -> dict[str, int]:
    stats: dict[str, int] = {}
    for line in path.read_text().splitlines():
        match = re.fullmatch(r"\* (restored|added|stale|invalid): (\d+)", line)
        if match:
            stats[match.group(1)] = int(match.group(2))
    if set(stats) != {"restored", "added", "stale", "invalid"}:
        raise ValueError(f"Deno mtime statistics are incomplete: {path}")
    return stats


def verify_restored_mtimes(
    source_root: Path,
    before: dict[str, float],
    after: dict[str, float],
) -> dict[str, Any]:
    restored_keys = sorted(before.keys() & after.keys())
    if not restored_keys:
        raise ValueError("Deno mtime cache restored zero unchanged source entries")

    mismatches: list[str] = []
    source_root = source_root.resolve()
    for key in restored_keys:
        parts = key.split("\0", 3)
        if len(parts) != 4:
            mismatches.append(f"invalid cache key: {key!r}")
            continue
        relative_path = parts[3]
        source_path = (source_root / relative_path).resolve()
        if not source_path.is_relative_to(source_root) or not source_path.is_file():
            mismatches.append(f"missing restored source path: {relative_path}")
            continue
        expected = before[key]
        if after[key] != expected:
            mismatches.append(f"cache value changed: {relative_path}")
            continue
        if not math.isclose(source_path.stat().st_mtime, expected, abs_tol=0.001):
            mismatches.append(f"filesystem mtime differs: {relative_path}")

    if mismatches:
        preview = "; ".join(mismatches[:10])
        raise ValueError(f"restored mtime verification failed: {preview}")

    return {
        "source_entries_before": len(before),
        "source_entries_after": len(after),
        "exact_restored_entries": len(restored_keys),
        "changed_or_added_entries": len(after) - len(restored_keys),
        "mismatched_entries": 0,
    }


def parse_cargo_messages(path: Path) -> dict[str, Any]:
    fresh_targets: set[str] = set()
    rebuilt_targets: set[str] = set()
    build_finished = False
    for line in path.read_text().splitlines():
        if not line.startswith("{"):
            continue
        message = json.loads(line)
        reason = message.get("reason")
        if reason == "compiler-artifact":
            target = message.get("target", {}).get("name")
            package = message.get("package_id")
            label = f"{package}:{target}"
            if message.get("fresh") is True:
                fresh_targets.add(label)
            else:
                rebuilt_targets.add(label)
        elif reason == "build-finished":
            build_finished = build_finished or message.get("success") is True

    if not build_finished:
        raise ValueError("Cargo JSON evidence has no successful build-finished message")
    if not fresh_targets:
        raise ValueError("Cargo accepted zero restored targets as fresh")
    if not rebuilt_targets:
        raise ValueError("Cargo rebuilt zero targets for the pinned rolling change")
    return {
        "fresh_targets": len(fresh_targets),
        "rebuilt_targets": len(rebuilt_targets),
        "build_finished": True,
    }


def build_evidence(
    source_root: Path,
    mtime_before: Path,
    mtime_after: Path,
    mtime_log: Path,
    cargo_messages: Path,
) -> dict[str, Any]:
    before = load_mtime_cache(mtime_before)
    after = load_mtime_cache(mtime_after)
    mtime_stats = parse_mtime_stats(mtime_log)
    mtimes = verify_restored_mtimes(source_root, before, after)
    if mtime_stats["restored"] != mtimes["exact_restored_entries"]:
        raise ValueError(
            "Deno mtime restored counter does not match exact filesystem verification"
        )
    if mtime_stats["invalid"] != 0:
        raise ValueError("Deno mtime cache reported invalid restored timestamps")

    return {
        "schema_version": "deno_target_freshness.v1",
        "mtime": {**mtime_stats, **mtimes},
        "cargo": parse_cargo_messages(cargo_messages),
    }


def main() -> int:
    args = parse_args()
    evidence = build_evidence(
        Path(args.source_root),
        Path(args.mtime_before),
        Path(args.mtime_after),
        Path(args.mtime_log),
        Path(args.cargo_messages),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
