#!/usr/bin/env python3
"""Keep target restore and compiler cache observations separate for each phase."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_json(path: str) -> dict[str, Any] | None:
    if not path or not Path(path).is_file():
        return None
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise TypeError(f"Expected a JSON object in {path}")
    return value


def total(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        counts = value.get("counts")
        if isinstance(counts, dict) and all(isinstance(item, int) for item in counts.values()):
            return sum(counts.values())
    return None


def compiler_observation(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    stats = current.get("stats") or {}
    prior = (previous or {}).get("stats") or {}
    names = {
        "compile_requests": "compile_requests",
        "compile_requests_executed": "requests_executed",
        "cache_hits": "cache_hits",
        "cache_misses": "cache_misses",
        "non_cacheable_calls": "requests_not_cacheable",
        "cache_errors": "cache_errors",
        "cache_read_errors": "cache_read_errors",
        "cache_write_errors": "cache_write_errors",
        "cache_timeouts": "cache_timeouts",
    }
    observation: dict[str, Any] = {"tool": "sccache", "status": "measured"}
    for name, field in names.items():
        count = total(stats.get(field))
        before = total(prior.get(field)) if previous else 0
        observation[name] = count - before if count is not None and before is not None else None
    observation["cacheable_requests"] = (
        observation["cache_hits"] + observation["cache_misses"]
        if observation["cache_hits"] is not None and observation["cache_misses"] is not None
        else None
    )
    return observation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True, choices=("runs-on-cache", "boringcache"))
    parser.add_argument("--cache-variant", required=True)
    parser.add_argument("--primary-evidence", default="")
    parser.add_argument("--magic-hit", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    sessions = []
    location = None
    if args.cache_variant != "target":
        first = read_json("benchmark-results/sccache-primary.json")
        final = read_json("benchmark-results/sccache-final.json")
        if first is None or final is None:
            raise ValueError("Missing sccache statistics")
        location = final.get("cache_location")
        if args.provider == "runs-on-cache" and (not isinstance(location, str) or location.split(",", 1)[0].strip().lower() != "s3"):
            raise ValueError(f"RunsOn sccache did not select S3: {location}")
        sessions = [
            {"session": "primary", "compiler": compiler_observation(first, None)},
            {"session": "desktop", "compiler": compiler_observation(final, first)},
        ]

    evidence = None
    target_hit = args.magic_hit == "true" if args.magic_hit else None
    if args.provider == "boringcache":
        evidence = read_json(args.primary_evidence)
        if evidence is None:
            raise ValueError(f"Missing BoringCache action evidence: {args.primary_evidence}")
        restore = (evidence.get("phases") or {}).get("restore") or {}
        target_hit = (restore.get("mode_evidence") or {}).get("target_cache_hit")
    payload = {
        "schema_version": 1,
        "provider": args.provider,
        "cache_variant": args.cache_variant,
        "timestamp_preparation": "none",
        "target_restore_hit": target_hit if args.cache_variant != "sccache-only" else None,
        "dependency_archive_hit": None,
        "compiler_backend": location,
        "compiler_sessions": sessions,
        "action_evidence": evidence,
        "publication_timing": "GitHub completed-job steps",
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(output)


if __name__ == "__main__":
    main()
