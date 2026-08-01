#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actions", required=True)
    parser.add_argument("--boringcache", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--require-content-match",
        action="store_true",
        help="Require identical paths, types, bytes, modes, links, hardlinks, and xattrs while reporting mtime-only drift separately.",
    )
    return parser.parse_args()


def load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if payload.get("schema_version") != "deno_target_snapshot.v1":
        raise ValueError(f"Unexpected target snapshot: {path}")
    return payload


def content_entries_sha256(snapshot: dict[str, Any]) -> str:
    recorded = snapshot.get("content_entries_sha256")
    if isinstance(recorded, str) and recorded:
        return recorded
    entries = [
        {key: value for key, value in entry.items() if key != "mtime_ns"}
        for entry in snapshot["entries"]
    ]
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


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

    content_differences = [
        difference
        for difference in differences
        if set(difference["fields"]) != {"mtime_ns"}
    ]
    mtime_only_differences = [
        difference
        for difference in differences
        if set(difference["fields"]) == {"mtime_ns"}
    ]
    exact = not only_actions and not only_boringcache and not differences
    content_exact = (
        not only_actions and not only_boringcache and not content_differences
    )
    return {
        "schema_version": "deno_target_comparison.v1",
        "exact_match": exact,
        "content_exact_match": content_exact,
        "actions_entries_sha256": actions["entries_sha256"],
        "boringcache_entries_sha256": boringcache["entries_sha256"],
        "actions_content_entries_sha256": content_entries_sha256(actions),
        "boringcache_content_entries_sha256": content_entries_sha256(boringcache),
        "only_actions_count": len(only_actions),
        "only_boringcache_count": len(only_boringcache),
        "different_entries_count": len(differences),
        "content_different_entries_count": len(content_differences),
        "mtime_only_differences_count": len(mtime_only_differences),
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
    required_field = (
        "content_exact_match" if args.require_content_match else "exact_match"
    )
    if not payload[required_field]:
        boundary = "content" if args.require_content_match else "metadata"
        raise ValueError(f"Target {boundary} differs; see {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
