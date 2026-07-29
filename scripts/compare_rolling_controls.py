#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--title", required=True)
    return parser.parse_args()


def load_result(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if payload.get("phase") != "rolling":
        raise ValueError(f"Expected a rolling result: {path}")
    return payload


def compare(
    baseline: dict[str, Any], candidate: dict[str, Any], title: str
) -> dict[str, Any]:
    if baseline.get("benchmark") != candidate.get("benchmark"):
        raise ValueError("Mismatched benchmark")
    if baseline.get("project") != candidate.get("project"):
        raise ValueError("Mismatched project cohort")
    if baseline.get("workload") != candidate.get("workload"):
        raise ValueError("Mismatched workload cohort")

    for field in ("cli_version", "action_sha"):
        if baseline.get("product", {}).get(field) != candidate.get("product", {}).get(
            field
        ):
            raise ValueError(f"Mismatched product {field}")
    for field in ("provider", "image", "image_version", "architecture", "os"):
        baseline_value = baseline.get("runner", {}).get(field)
        candidate_value = candidate.get("runner", {}).get(field)
        if field == "image_version" and (not baseline_value or not candidate_value):
            raise ValueError("Missing runner image_version")
        if baseline_value != candidate_value:
            raise ValueError(f"Mismatched runner {field}")

    for field in ("cpu_model", "logical_cores", "memory_class_gib"):
        baseline_value = baseline.get("runner", {}).get("hardware", {}).get(field)
        candidate_value = candidate.get("runner", {}).get("hardware", {}).get(field)
        if baseline_value is None or candidate_value is None:
            raise ValueError(f"Missing runner hardware {field}")
        if baseline_value != candidate_value:
            raise ValueError(f"Mismatched runner hardware {field}")

    baseline_compiler = baseline.get("compiler_environment", {}).get("sha256")
    candidate_compiler = candidate.get("compiler_environment", {}).get("sha256")
    if not baseline_compiler or not candidate_compiler:
        raise ValueError("Missing compiler environment identity")
    if baseline_compiler != candidate_compiler:
        raise ValueError("Mismatched compiler environment identity")

    baseline_timing = baseline["timing"]
    candidate_timing = candidate["timing"]
    baseline_total = baseline_timing["end_to_end_seconds"]
    candidate_total = candidate_timing["end_to_end_seconds"]
    saved = baseline_total - candidate_total
    return {
        "schema_version": 1,
        "title": title,
        "benchmark": baseline["benchmark"],
        "baseline": baseline,
        "candidate": candidate,
        "comparison": {
            "baseline_restore_seconds": baseline_timing["restore_seconds"],
            "candidate_restore_seconds": candidate_timing["restore_seconds"],
            "restore_seconds_saved": baseline_timing["restore_seconds"]
            - candidate_timing["restore_seconds"],
            "baseline_build_seconds": baseline_timing["build_seconds"],
            "candidate_build_seconds": candidate_timing["build_seconds"],
            "build_seconds_saved": baseline_timing["build_seconds"]
            - candidate_timing["build_seconds"],
            "baseline_end_to_end_seconds": baseline_total,
            "candidate_end_to_end_seconds": candidate_total,
            "end_to_end_seconds_saved": saved,
            "percent_saved": round(saved * 100 / baseline_total, 1)
            if baseline_total
            else None,
        },
    }


def render_markdown(payload: dict[str, Any]) -> str:
    baseline = payload["baseline"]
    candidate = payload["candidate"]
    comparison = payload["comparison"]
    baseline_freshness = baseline.get("target_freshness") or {}
    freshness = candidate.get("target_freshness") or {}
    baseline_cargo = baseline_freshness.get("cargo") or {}
    cargo = freshness.get("cargo") or {}
    mtime = freshness.get("mtime") or {}
    baseline_sccache = baseline.get("sccache") or {}
    candidate_sccache = candidate.get("sccache") or {}
    saved = comparison["end_to_end_seconds_saved"]
    verdict = (
        f"Candidate saved **{saved}s ({comparison['percent_saved']}%)**."
        if saved >= 0
        else f"Candidate was **{-saved}s slower ({-comparison['percent_saved']}%)**."
    )
    return "\n".join(
        [
            f"# {payload['title']}",
            "",
            "| Strategy | Restore/setup | Build | End-to-end |",
            "|---|---:|---:|---:|",
            f"| {baseline['strategy']} | {baseline['timing']['restore_seconds']}s | {baseline['timing']['build_seconds']}s | {baseline['timing']['end_to_end_seconds']}s |",
            f"| {candidate['strategy']} | {candidate['timing']['restore_seconds']}s | {candidate['timing']['build_seconds']}s | {candidate['timing']['end_to_end_seconds']}s |",
            "",
            verdict,
            "",
            "## Native and target work",
            "",
            "| Strategy | sccache hits | sccache misses | Cargo-fresh | Rebuilt |",
            "|---|---:|---:|---:|---:|",
            f"| {baseline['strategy']} | {baseline_sccache.get('cache_hits', 'n/a')} | {baseline_sccache.get('cache_misses', 'n/a')} | {baseline_cargo.get('fresh_targets', 'n/a')} | {baseline_cargo.get('rebuilt_targets', 'n/a')} |",
            f"| {candidate['strategy']} | {candidate_sccache.get('cache_hits', 'n/a')} | {candidate_sccache.get('cache_misses', 'n/a')} | {cargo.get('fresh_targets', 'n/a')} | {cargo.get('rebuilt_targets', 'n/a')} |",
            "",
            "## Candidate freshness",
            "",
            f"- Exact restored mtimes: {mtime.get('exact_restored_entries', 'n/a')}",
            f"- Mtime mismatches: {mtime.get('mismatched_entries', 'n/a')}",
            f"- Cargo-fresh targets: {cargo.get('fresh_targets', 'n/a')}",
            f"- Rebuilt targets: {cargo.get('rebuilt_targets', 'n/a')}",
            "",
        ]
    )


def main() -> int:
    args = parse_args()
    payload = compare(
        load_result(Path(args.baseline)),
        load_result(Path(args.candidate)),
        args.title,
    )
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "comparison.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )
    (output_dir / "comparison.md").write_text(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
