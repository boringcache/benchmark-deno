#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actions", required=True)
    parser.add_argument("--boringcache", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if payload.get("schema_version") != "deno_target_snapshot.v1":
        raise ValueError(f"Unexpected target snapshot: {path}")
    return payload


def compare(actions: dict[str, Any], boringcache: dict[str, Any]) -> dict[str, Any]:
    actions_entries = {entry["path"]: entry for entry in actions["entries"]}
    boringcache_entries = {
        entry["path"]: entry for entry in boringcache["entries"]
    }
    actions_paths = set(actions_entries)
    boringcache_paths = set(boringcache_entries)
    only_actions = sorted(actions_paths - boringcache_paths)
    only_boringcache = sorted(boringcache_paths - actions_paths)
    differences: list[dict[str, Any]] = []
    for path in sorted(actions_paths & boringcache_paths):
        left = actions_entries[path]
        right = boringcache_entries[path]
        fields = sorted((set(left) | set(right)) - {"path"})
        changed = {
            field: {"actions": left.get(field), "boringcache": right.get(field)}
            for field in fields
            if left.get(field) != right.get(field)
        }
        if changed:
            differences.append({"path": path, "fields": changed})

    exact = not only_actions and not only_boringcache and not differences
    return {
        "schema_version": "deno_target_comparison.v1",
        "exact_match": exact,
        "actions_entries_sha256": actions["entries_sha256"],
        "boringcache_entries_sha256": boringcache["entries_sha256"],
        "only_actions_count": len(only_actions),
        "only_boringcache_count": len(only_boringcache),
        "different_entries_count": len(differences),
        "only_actions": only_actions[:100],
        "only_boringcache": only_boringcache[:100],
        "differences": differences[:100],
    }


def main() -> int:
    args = parse_args()
    payload = compare(load(Path(args.actions)), load(Path(args.boringcache)))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in payload.items() if key not in {"differences", "only_actions", "only_boringcache"}}, indent=2))
    if not payload["exact_match"]:
        raise ValueError(f"Restored target trees differ; see {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
