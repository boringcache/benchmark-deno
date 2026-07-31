#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, cast


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--exclude-prefix",
        action="append",
        default=[],
        type=relative_prefix,
        help="Relative target path to omit, including its descendants.",
    )
    return parser.parse_args()


def relative_prefix(value: str) -> Path:
    prefix = Path(value)
    if (
        not value.strip()
        or prefix.is_absolute()
        or not prefix.parts
        or any(part in {".", ".."} for part in prefix.parts)
    ):
        raise argparse.ArgumentTypeError(
            f"Exclude prefix must be a non-empty relative path: {value!r}"
        )
    return prefix


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def xattrs(path: Path) -> dict[str, str]:
    listxattr = getattr(os, "listxattr", None)
    getxattr = getattr(os, "getxattr", None)
    if not callable(listxattr) or not callable(getxattr):
        return {}
    listxattr_fn = cast(Callable[..., list[str]], listxattr)
    getxattr_fn = cast(Callable[..., bytes], getxattr)
    try:
        names = sorted(listxattr_fn(path, follow_symlinks=False))
    except OSError:
        return {}

    values: dict[str, str] = {}
    for name in names:
        try:
            value = getxattr_fn(path, name, follow_symlinks=False)
        except OSError:
            continue
        values[name] = hashlib.sha256(value).hexdigest()
    return values


def entry_type(mode: int) -> str:
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISLNK(mode):
        return "symlink"
    return "other"


def snapshot(
    root: Path, exclude_prefixes: Sequence[Path] = ()
) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"Target root is not a directory: {root}")

    excluded_parts = tuple(prefix.parts for prefix in exclude_prefixes)

    def included(path: Path) -> bool:
        relative_parts = path.relative_to(root).parts
        return not any(
            relative_parts[: len(prefix)] == prefix for prefix in excluded_parts
        )

    paths = sorted(
        (path for path in root.rglob("*") if included(path)),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    hardlinks: dict[tuple[int, int], list[str]] = {}
    for path in paths:
        metadata = path.lstat()
        if stat.S_ISREG(metadata.st_mode) and metadata.st_nlink > 1:
            hardlinks.setdefault((metadata.st_dev, metadata.st_ino), []).append(
                path.relative_to(root).as_posix()
            )
    hardlink_groups = {
        identity: sorted(members)[0]
        for identity, members in hardlinks.items()
        if len(members) > 1
    }

    entries: list[dict[str, Any]] = []
    counts = {"files": 0, "directories": 0, "symlinks": 0, "other": 0}
    total_file_bytes = 0
    allocated_bytes = 0
    for path in paths:
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        kind = entry_type(metadata.st_mode)
        count_key = {
            "file": "files",
            "directory": "directories",
            "symlink": "symlinks",
            "other": "other",
        }[kind]
        counts[count_key] += 1
        record: dict[str, Any] = {
            "path": relative,
            "type": kind,
            "mode": stat.S_IMODE(metadata.st_mode),
            "mtime_ns": metadata.st_mtime_ns,
            "xattrs": xattrs(path),
        }
        if kind == "file":
            total_file_bytes += metadata.st_size
            allocated_bytes += getattr(metadata, "st_blocks", 0) * 512
            record.update(
                {
                    "size": metadata.st_size,
                    "sha256": sha256_file(path),
                    "hardlink_group": hardlink_groups.get(
                        (metadata.st_dev, metadata.st_ino)
                    ),
                }
            )
        elif kind == "symlink":
            record["target"] = os.readlink(path)
        entries.append(record)

    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": "deno_target_snapshot.v1",
        "root_name": root.name,
        "excluded_prefixes": [prefix.as_posix() for prefix in exclude_prefixes],
        "entry_count": len(entries),
        **counts,
        "total_file_bytes": total_file_bytes,
        "allocated_bytes": allocated_bytes,
        "entries_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "entries": entries,
    }


def main() -> int:
    args = parse_args()
    payload = snapshot(Path(args.root), args.exclude_prefix)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(
        "Captured "
        f"{payload['entry_count']} target entries / "
        f"{payload['total_file_bytes']} bytes / "
        f"{payload['entries_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
