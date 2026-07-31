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
    return parser.parse_args()


def load(path: Path, schema: str) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if payload.get("schema_version") != schema:
        raise ValueError(f"Unexpected schema in {path}")
    return payload


def gib(value: int | None) -> str:
    if value is None:
        return "-"
    return f"{value / 1024**3:.2f} GiB"


def main() -> int:
    args = parse_args()
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, dict[str, Any]] = {}
    for transport in ("chunks", "monolith"):
        base = load(
            input_dir / f"base-{transport}.json",
            "deno_boringcache_cargo_base.v1",
        )
        rolling = load(
            input_dir / f"proof-{transport}.json", "deno_boringcache_cargo.v1"
        )
        if base["cli_version"] != rolling["cli_version"]:
            raise ValueError(f"CLI identity drifted in the {transport} lane")
        results[transport] = {"base": base, "rolling": rolling}

    comparison = {
        "schema_version": "deno_cargo_transport_comparison.v1",
        "cli_version": results["chunks"]["rolling"]["cli_version"],
        "results": results,
    }
    (output_dir / "cargo-transport-comparison.json").write_text(
        json.dumps(comparison, indent=2, sort_keys=True) + "\n"
    )

    rows = []
    for transport in ("chunks", "monolith"):
        base = results[transport]["base"]
        rolling = results[transport]["rolling"]
        archive = rolling["archive"]
        rows.append(
            "| {transport} | {publish}s | {rolling_time}s | {target} | {stored} | {layout} | {fresh}/{rebuilt} | {hits}/{misses} |".format(
                transport=transport,
                publish=base["elapsed_seconds"],
                rolling_time=rolling["elapsed_seconds"],
                target=gib(rolling["target_size_bytes"]),
                stored=gib(archive.get("stored_size_bytes")),
                layout=archive.get("cas_layout") or archive["storage_mode"],
                fresh=rolling["cargo"]["fresh_targets"],
                rebuilt=rolling["cargo"]["rebuilt_targets"],
                hits=rolling["sccache"]["cache_hits"],
                misses=rolling["sccache"]["cache_misses"],
            )
        )

    markdown = "\n".join(
        [
            "# Deno Cargo transport comparison",
            "",
            f"Exact CLI: `{comparison['cli_version']}`",
            "",
            "| Transport | Base publish | Rolling end to end | Target | Stored | Layout | Cargo fresh/rebuilt | sccache hits/misses |",
            "|---|---:|---:|---:|---:|---|---:|---:|",
            *rows,
            "",
            "Both lanes use the same CLI-owned Cargo plan. Only the generic archive transport changes.",
            "",
        ]
    )
    (output_dir / "cargo-transport-comparison.md").write_text(markdown)
    print(output_dir / "cargo-transport-comparison.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
