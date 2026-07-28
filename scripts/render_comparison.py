#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--benchmark", default="deno-release-rust-cache")
    parser.add_argument("--candidate-strategy", default="boringcache")
    parser.add_argument("--title", default="Deno release Rust cache proof")
    return parser.parse_args()


def load_results(
    input_dir: Path, candidate_strategy: str = "boringcache"
) -> dict[tuple[str, str], dict[str, Any]]:
    results: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted(input_dir.glob("*.json")):
        payload = json.loads(path.read_text())
        key = (payload["strategy"], payload["phase"])
        if key in results:
            raise ValueError(f"Duplicate benchmark result for {key}: {path}")
        results[key] = payload

    expected_results = {
        ("actions-cache", "base"),
        ("actions-cache", "rolling"),
        (candidate_strategy, "base"),
        (candidate_strategy, "rolling"),
    }
    missing = expected_results - results.keys()
    if missing:
        labels = ", ".join(f"{strategy}/{phase}" for strategy, phase in sorted(missing))
        raise ValueError(f"Missing benchmark results: {labels}")
    return results


def format_seconds(value: int | None) -> str:
    return "n/a" if value is None else f"{value}s"


def format_bytes(value: int | None) -> str:
    if value is None:
        return "n/a"
    return f"{value / (1024 ** 3):.2f} GiB"


def comparison_payload(
    results: dict[tuple[str, str], dict[str, Any]],
    candidate_strategy: str = "boringcache",
    benchmark: str = "deno-release-rust-cache",
    title: str = "Deno release Rust cache proof",
) -> dict[str, Any]:
    gha_timing = results[("actions-cache", "rolling")]["timing"]
    boringcache_timing = results[(candidate_strategy, "rolling")]["timing"]
    gha_total = gha_timing["end_to_end_seconds"]
    boringcache_total = boringcache_timing["end_to_end_seconds"]
    total_saved = gha_total - boringcache_total
    percent = round(total_saved * 100 / gha_total, 1) if gha_total else None
    return {
        "schema_version": 1,
        "benchmark": benchmark,
        "title": title,
        "candidate_strategy": candidate_strategy,
        "results": list(results.values()),
        "rolling_comparison": {
            "actions_cache_end_to_end_seconds": gha_total,
            "boringcache_end_to_end_seconds": boringcache_total,
            "end_to_end_seconds_saved": total_saved,
            "percent_saved": percent,
            "actions_cache_build_seconds": gha_timing["build_seconds"],
            "boringcache_build_seconds": boringcache_timing["build_seconds"],
            "build_seconds_saved": gha_timing["build_seconds"] - boringcache_timing["build_seconds"],
        },
    }


def render_markdown(payload: dict[str, Any]) -> str:
    indexed = {(row["strategy"], row["phase"]): row for row in payload["results"]}
    lines = [
        f"# {payload['title']}",
        "",
        "Pinned rolling pair: `0c965f5` → `c3ea533f` (one Rust file and one TypeScript file changed).",
        "",
        "| Strategy | Phase | Restore/setup | Build | End-to-end | Seed cache size | sccache hit rate |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    candidate_strategy = payload["candidate_strategy"]
    for strategy in ("actions-cache", candidate_strategy):
        for phase in ("base", "rolling"):
            row = indexed[(strategy, phase)]
            timing = row["timing"]
            cache = row["cache"]
            stats = row.get("sccache") or {}
            hit_rate = stats.get("cache_hit_percent")
            lines.append(
                "| {strategy} | {phase} | {restore} | {build} | {total} | {storage} | {hit_rate} |".format(
                    strategy=strategy,
                    phase=phase,
                    restore=format_seconds(timing.get("restore_seconds")),
                    build=format_seconds(timing.get("build_seconds")),
                    total=format_seconds(timing.get("end_to_end_seconds")),
                    storage=format_bytes(cache.get("storage_bytes")),
                    hit_rate="n/a" if hit_rate is None else f"{hit_rate}%",
                )
            )

    comparison = payload["rolling_comparison"]
    saved = comparison["end_to_end_seconds_saved"]
    if saved > 0:
        conclusion = (
            f"{candidate_strategy} saved **{saved}s ({comparison['percent_saved']}%)** "
            "on rolling restore plus build."
        )
    elif saved < 0:
        conclusion = (
            f"{candidate_strategy} was **{-saved}s slower** on rolling restore plus build; "
            "this proof does not support migration yet."
        )
    else:
        conclusion = "The rolling restore-plus-build times were equal."

    lines.extend(
        [
            "",
            "## Result",
            "",
            conclusion,
            "",
            "The command matches Deno's pinned Linux CI compile surface, including its sysroot and ThinLTO flags. "
            "Release startup-order tracing and the second relink remain excluded from the release proof.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    results = load_results(Path(args.input_dir), args.candidate_strategy)
    payload = comparison_payload(
        results,
        candidate_strategy=args.candidate_strategy,
        benchmark=args.benchmark,
        title=args.title,
    )
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "comparison.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    (output_dir / "comparison.md").write_text(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
