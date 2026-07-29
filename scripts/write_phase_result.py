#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


STRATEGIES = (
    "actions-cache",
    "actions-target-boringcache-sccache",
    "boringcache",
    "boringcache-hybrid",
    "boringcache-full-target",
    "boringcache-target-boringcache-sccache",
    "boringcache-target-only",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--strategy",
        required=True,
        choices=STRATEGIES,
    )
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--build-profile", required=True, choices=("release", "debug"))
    parser.add_argument("--phase", required=True, choices=("base", "rolling"))
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--restore-seconds", type=int, required=True)
    parser.add_argument("--build-seconds", type=int, required=True)
    parser.add_argument("--end-to-end-seconds", type=int, required=True)
    parser.add_argument("--cache-storage-bytes", type=int)
    parser.add_argument("--cache-key", default="")
    parser.add_argument("--cache-mode", required=True)
    parser.add_argument("--cache-components", default="")
    parser.add_argument("--cache-import-status", default="")
    parser.add_argument("--sccache-stats-file")
    parser.add_argument("--require-sccache-evidence", action="store_true")
    parser.add_argument("--freshness-evidence-file")
    parser.add_argument("--require-freshness-evidence", action="store_true")
    parser.add_argument("--cli-version", required=True)
    parser.add_argument("--action-sha", required=True)
    parser.add_argument("--output-dir", default="benchmark-results")
    return parser.parse_args()


def parse_sccache_stats(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None

    wanted = {
        "compile_requests": "Compile requests",
        "compile_requests_executed": "Compile requests executed",
        "cache_hits": "Cache hits",
        "cache_hits_assembler": "Cache hits (Assembler)",
        "cache_hits_c_cpp": "Cache hits (C/C++)",
        "cache_hits_rust": "Cache hits (Rust)",
        "cache_misses": "Cache misses",
        "cache_misses_c_cpp": "Cache misses (C/C++)",
        "cache_misses_rust": "Cache misses (Rust)",
        "non_cacheable_compilations": "Non-cacheable compilations",
        "non_cacheable_calls": "Non-cacheable calls",
        "cache_errors": "Cache errors",
        "cache_errors_c_cpp": "Cache errors (C/C++)",
        "cache_read_errors": "Cache read errors",
        "cache_write_errors": "Cache write errors",
        "cache_timeouts": "Cache timeouts",
        "forced_recaches": "Forced recaches",
        "compilations": "Compilations",
        "compilation_failures": "Compilation failures",
        "non_compilation_calls": "Non-compilation calls",
        "unsupported_compiler_calls": "Unsupported compiler calls",
        "failed_distributed_compilations": "Failed distributed compilations",
    }
    durations = {
        "average_cache_read_hit_seconds": "Average cache read hit",
        "average_cache_write_seconds": "Average cache write",
        "average_compiler_seconds": "Average compiler",
    }
    parsed: dict[str, Any] = {}
    non_cacheable_reasons: dict[str, int] = {}
    parsing_reasons = False
    for line in path.read_text().splitlines():
        normalized = line.strip()
        if normalized == "Non-cacheable reasons:":
            parsing_reasons = True
            continue
        if parsing_reasons:
            if not normalized:
                parsing_reasons = False
                continue
            reason_match = re.fullmatch(r"(.+?)\s+(\d+)", normalized)
            if reason_match:
                non_cacheable_reasons[reason_match.group(1).strip()] = int(
                    reason_match.group(2)
                )
                continue
            parsing_reasons = False
        for key, label in wanted.items():
            match = re.fullmatch(rf"{re.escape(label)}\s+(\d+)", normalized)
            if match:
                parsed[key] = int(match.group(1))
        for key, label in durations.items():
            match = re.fullmatch(rf"{re.escape(label)}\s+([0-9.]+)\s+s", normalized)
            if match:
                parsed[key] = float(match.group(1))

    hits = parsed.get("cache_hits")
    misses = parsed.get("cache_misses")
    if hits is not None and misses is not None and hits + misses:
        parsed["cache_hit_percent"] = round(hits * 100 / (hits + misses), 2)
    if non_cacheable_reasons:
        parsed["non_cacheable_reasons"] = non_cacheable_reasons
    return parsed


def runner_hardware() -> dict[str, Any]:
    cpu_model = None
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for line in cpuinfo.read_text().splitlines():
            if line.startswith("model name") and ":" in line:
                cpu_model = line.split(":", 1)[1].strip()
                break

    memory_class_gib = None
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        for line in meminfo.read_text().splitlines():
            match = re.fullmatch(r"MemTotal:\s+(\d+)\s+kB", line)
            if match:
                total_gib = int(match.group(1)) * 1024 / (1024**3)
                memory_class_gib = round(total_gib)
                break

    return {
        "cpu_model": cpu_model,
        "logical_cores": os.cpu_count(),
        "memory_class_gib": memory_class_gib,
    }


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stats_path = Path(args.sccache_stats_file) if args.sccache_stats_file else None
    if stats_path is not None and not stats_path.is_file():
        raise FileNotFoundError(stats_path)
    sccache = parse_sccache_stats(stats_path)
    if args.require_sccache_evidence:
        if not sccache or not sccache.get("compile_requests"):
            raise ValueError("Required sccache compile evidence is missing")
        if "cache_hits" not in sccache or "cache_misses" not in sccache:
            raise ValueError("Required sccache hit/miss evidence is missing")

    freshness_path = (
        Path(args.freshness_evidence_file) if args.freshness_evidence_file else None
    )
    if freshness_path is not None and not freshness_path.is_file():
        raise FileNotFoundError(freshness_path)
    freshness = json.loads(freshness_path.read_text()) if freshness_path else None
    if args.require_freshness_evidence:
        if not freshness or freshness.get("schema_version") != "deno_target_freshness.v1":
            raise ValueError("Required Deno target freshness evidence is missing")
        if not freshness.get("mtime", {}).get("exact_restored_entries"):
            raise ValueError("Required exact restored mtime evidence is missing")
        if not freshness.get("cargo", {}).get("fresh_targets"):
            raise ValueError("Required Cargo fresh-target evidence is missing")

    cache_components = [
        component.strip()
        for component in args.cache_components.split(",")
        if component.strip()
    ]
    compiler_environment = {
        name: os.environ.get(name)
        for name in (
            "RUSTC_WRAPPER",
            "CC",
            "CXX",
            "CFLAGS",
            "CXXFLAGS",
            "RUSTFLAGS",
            "RUSTDOCFLAGS",
            "CARGO_INCREMENTAL",
            "CARGO_PROFILE_RELEASE_INCREMENTAL",
        )
    }
    compiler_environment_json = json.dumps(
        compiler_environment, sort_keys=True, separators=(",", ":")
    )

    payload = {
        "schema_version": 2,
        "benchmark": args.benchmark,
        "strategy": args.strategy,
        "phase": args.phase,
        "workload": {
            "build_profile": args.build_profile,
            "command": f"./scripts/run-deno-{args.build_profile}-build.sh",
        },
        "project": {
            "repository": "denoland/deno",
            "source_sha": args.source_sha,
        },
        "product": {
            "cli_version": args.cli_version,
            "action_ref": f"boringcache/one@{args.action_sha}",
            "action_sha": args.action_sha,
            "benchmark_sha": os.environ.get("GITHUB_SHA"),
        },
        "timing": {
            "restore_seconds": args.restore_seconds,
            "build_seconds": args.build_seconds,
            "end_to_end_seconds": args.end_to_end_seconds,
        },
        "cache": {
            "storage_bytes": args.cache_storage_bytes,
            "key": args.cache_key or None,
            "mode": args.cache_mode,
            "components": cache_components,
            "import_status": args.cache_import_status or None,
        },
        "classification": {
            "sample_valid": True,
            "reporting_mode": "rolling" if args.phase == "rolling" else "seed",
            "cache_import_status": args.cache_import_status or None,
        },
        "sccache": sccache,
        "native_tool": (
            {
                "tool": "sccache",
                "schema_version": "native_tool_evidence.v1",
                "stats_source": "sccache --show-stats",
                **sccache,
            }
            if sccache is not None
            else None
        ),
        "target_freshness": freshness,
        "compiler_environment": {
            "values": compiler_environment,
            "sha256": hashlib.sha256(compiler_environment_json.encode()).hexdigest(),
        },
        "runner": {
            "provider": "github-actions",
            "image": os.environ.get("ImageOS"),
            "image_version": os.environ.get("ImageVersion"),
            "architecture": os.environ.get("RUNNER_ARCH"),
            "os": os.environ.get("RUNNER_OS"),
            "filesystem_persisted_from_seed": False,
            "hardware": runner_hardware(),
        },
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
