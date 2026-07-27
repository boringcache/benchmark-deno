#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


EXPECTED_RESULTS = {
    ("actions-cache", "base"),
    ("actions-cache", "rolling"),
    ("boringcache", "base"),
    ("boringcache", "rolling"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def load_results(input_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    results: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted(input_dir.glob("*.json")):
        payload = json.loads(path.read_text())
        key = (payload["strategy"], payload["phase"])
        if key in results:
            raise ValueError(f"Duplicate benchmark result for {key}: {path}")
        results[key] = payload

    missing = EXPECTED_RESULTS - results.keys()
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


def comparison_payload(results: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    gha_timing = results[("actions-cache", "rolling")]["timing"]
    boringcache_timing = results[("boringcache", "rolling")]["timing"]
    gha_total = gha_timing["end_to_end_seconds"]
    boringcache_total = boringcache_timing["end_to_end_seconds"]
    total_saved = gha_total - boringcache_total
    percent = round(total_saved * 100 / gha_total, 1) if gha_total else None
    return {
        "schema_version": 1,
        "benchmark": "deno-release-rust-cache",
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
        "# Deno release Rust cache proof",
        "",
        "Pinned rolling pair: `0c965f5` → `c3ea533f` (one Rust file and one TypeScript file changed).",
        "",
        "| Strategy | Phase | Restore/setup | Build | End-to-end | Seed cache size | sccache hit rate |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for strategy in ("actions-cache", "boringcache"):
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
            f"BoringCache saved **{saved}s ({comparison['percent_saved']}%)** on rolling restore plus build."
        )
    elif saved < 0:
        conclusion = (
            f"BoringCache was **{-saved}s slower** on rolling restore plus build; this proof does not support migration yet."
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
            "The release command matches Deno's CI compile surface, including its sysroot and ThinLTO flags. "
            "Startup-order tracing and the second relink are excluded so this proof does not attribute non-cacheable linker work to compiler caching.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    results = load_results(Path(args.input_dir))
    payload = comparison_payload(results)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "comparison.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    (output_dir / "comparison.md").write_text(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
