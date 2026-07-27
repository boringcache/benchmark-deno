#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", required=True, choices=("actions-cache", "boringcache"))
    parser.add_argument("--phase", required=True, choices=("base", "rolling"))
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--restore-seconds", type=int, required=True)
    parser.add_argument("--build-seconds", type=int, required=True)
    parser.add_argument("--end-to-end-seconds", type=int, required=True)
    parser.add_argument("--cache-storage-bytes", type=int)
    parser.add_argument("--cache-key", default="")
    parser.add_argument("--cache-import-status", default="")
    parser.add_argument("--sccache-stats-file")
    parser.add_argument("--output-dir", default="benchmark-results")
    return parser.parse_args()


def parse_sccache_stats(path: Path | None) -> dict[str, int] | None:
    if path is None or not path.is_file():
        return None

    wanted = {
        "compile_requests": "Compile requests",
        "compile_requests_executed": "Compile requests executed",
        "cache_hits": "Cache hits",
        "cache_misses": "Cache misses",
        "non_cacheable_compilations": "Non-cacheable compilations",
    }
    parsed: dict[str, int] = {}
    for line in path.read_text().splitlines():
        normalized = line.strip()
        for key, label in wanted.items():
            match = re.fullmatch(rf"{re.escape(label)}\s+(\d+)", normalized)
            if match:
                parsed[key] = int(match.group(1))

    hits = parsed.get("cache_hits")
    misses = parsed.get("cache_misses")
    if hits is not None and misses is not None and hits + misses:
        parsed["cache_hit_percent"] = round(hits * 100 / (hits + misses))
    return parsed


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stats_path = Path(args.sccache_stats_file) if args.sccache_stats_file else None

    payload = {
        "schema_version": 1,
        "benchmark": "deno-release-rust-cache",
        "strategy": args.strategy,
        "phase": args.phase,
        "project": {
            "repository": "denoland/deno",
            "source_sha": args.source_sha,
        },
        "timing": {
            "restore_seconds": args.restore_seconds,
            "build_seconds": args.build_seconds,
            "end_to_end_seconds": args.end_to_end_seconds,
        },
        "cache": {
            "storage_bytes": args.cache_storage_bytes,
            "key": args.cache_key or None,
            "import_status": args.cache_import_status or None,
        },
        "sccache": parse_sccache_stats(stats_path),
        "github": {
            "repository": os.environ.get("GITHUB_REPOSITORY"),
            "run_id": os.environ.get("GITHUB_RUN_ID"),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "job": os.environ.get("GITHUB_JOB"),
        },
    }

    output_path = output_dir / f"{args.strategy}-{args.phase}.json"
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

