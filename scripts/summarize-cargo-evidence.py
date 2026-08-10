#!/usr/bin/env python3
"""Render target reuse and native sccache evidence from Cargo action receipts."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def summarize(label: str, evidence_path: Path) -> str:
    evidence = json.loads(evidence_path.read_text())
    phase = evidence.get("phases", {}).get("restore", {})
    mode = phase.get("mode_evidence", {})
    native = mode.get("native_tool", {})

    requests = native.get("compile_requests")
    executed = native.get("compile_requests_executed")
    hits = native.get("cache_hits")
    misses = native.get("cache_misses")
    rate = native.get("hit_rate")
    errors = native.get("cache_errors")
    read_errors = native.get("cache_read_errors")
    write_errors = native.get("cache_write_errors")
    timeouts = native.get("cache_timeouts")
    elapsed = mode.get("elapsed_seconds")
    target_hit = mode.get("target_cache_hit")

    lines = [f"- `{label}`:"]
    if elapsed is not None:
        lines.append(f"  - elapsed: {elapsed:.0f}s")
    if target_hit is not None:
        lines.append(f"  - target snapshot restored: `{target_hit}`")
    if requests is not None:
        lines.append(
            f"  - compiler requests: {requests}; executed: "
            f"{executed if executed is not None else 'unknown'}"
        )
    if hits is not None:
        lines.append(
            f"  - sccache: {hits} hits / {misses} misses ({(rate or 0):.1f}% hit rate)"
        )
    if any(value for value in (errors, read_errors, write_errors, timeouts)):
        lines.append(
            "  - sccache errors: "
            f"total={errors or 0}, read={read_errors or 0}, "
            f"write={write_errors or 0}, timeouts={timeouts or 0}"
        )
    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) < 2 or len(sys.argv) % 2 != 1:
        print(
            "Usage: summarize-cargo-evidence.py LABEL EVIDENCE_PATH "
            "[LABEL EVIDENCE_PATH ...]",
            file=sys.stderr,
        )
        return 2

    blocks = ["## Cargo target and compiler-cache evidence", ""]
    for index in range(1, len(sys.argv), 2):
        label = sys.argv[index]
        path = Path(sys.argv[index + 1])
        if not path.is_file():
            blocks.append(f"- `{label}`: evidence missing at {path}")
            continue
        try:
            blocks.append(summarize(label, path))
        except (json.JSONDecodeError, OSError) as error:
            blocks.append(f"- `{label}`: unreadable evidence ({error})")

    report = "\n".join(blocks)
    print(report)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(report + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
