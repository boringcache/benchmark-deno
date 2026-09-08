#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ("cargo-product", "compiler-only")


def select_profile(path: Path, profile: str) -> None:
    if profile not in PROFILES:
        raise ValueError(f"Unknown Deno Cargo cache profile: {profile}")
    original = path.read_text()
    current = 'profiles = ["cargo-product"]'
    if original.count(current) != 1:
        raise ValueError(f"Expected one default Cargo profile selection in {path}")
    selected = original.replace(current, f'profiles = ["{profile}"]')
    selected = selected.replace('"lane=cargo-product"', f'"lane={profile}"')
    path.write_text(selected)


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print(
            "Usage: select-deno-cargo-profile.py cargo-product|compiler-only [.boringcache.toml]",
            file=sys.stderr,
        )
        return 2
    path = Path(sys.argv[2]) if len(sys.argv) == 3 else ROOT / ".boringcache.toml"
    try:
        select_profile(path, sys.argv[1])
    except (OSError, ValueError) as error:
        print(f"Unable to select Deno Cargo cache profile: {error}", file=sys.stderr)
        return 1
    print(f"Selected Deno Cargo cache profile: {sys.argv[1]}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
