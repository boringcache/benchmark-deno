#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_settings(path: Path) -> dict[str, str]:
    settings: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, raw_value = line.split("=", 1)
        values = shlex.split(raw_value)
        if len(values) != 1:
            raise ValueError(f"Expected one value for {key} in {path}")
        settings[key] = values[0]
    return settings


def cargo_command(settings: dict[str, str], phase: str) -> list[str]:
    common = [
        "cargo",
        "build",
        settings["DENO_BUILD_STD_ARG"],
        "--release",
        "--locked",
    ]
    if phase == "primary":
        return common + [
            "-p",
            "deno",
            "-p",
            "denort",
            "-p",
            "test_server",
            "--bin",
            "deno",
            "--bin",
            "denort",
            "--bin",
            "test_server",
            f"--features={settings['DENO_PANIC_TRACE_FEATURE']}",
        ]
    if phase == "desktop":
        return common + ["-p", "denort_desktop"]
    raise ValueError(f"Unknown Deno Cargo phase: {phase}")


def render_command(command: list[str]) -> str:
    lines = ["command = ["]
    for value in command:
        lines.append(f"  {json.dumps(value)},")
    lines.append("]")
    return "\n".join(lines)


def replace_command(config_path: Path, command: list[str]) -> None:
    original = config_path.read_text()
    updated, replacements = re.subn(
        r"^command\s*=\s*\[.*?^\]$",
        render_command(command),
        original,
        count=1,
        flags=re.MULTILINE | re.DOTALL,
    )
    if replacements != 1:
        raise ValueError(f"Expected one Cargo command in {config_path}")
    config_path.write_text(updated)


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print(
            "Usage: select-deno-cargo-phase.py primary|desktop [.boringcache.toml]",
            file=sys.stderr,
        )
        return 2
    config_path = Path(sys.argv[2]) if len(sys.argv) == 3 else ROOT / ".boringcache.toml"
    try:
        settings = read_settings(ROOT / "scripts/deno-release-recipe.env")
        command = cargo_command(settings, sys.argv[1])
        replace_command(config_path, command)
    except (KeyError, OSError, ValueError) as error:
        print(f"Unable to select Deno Cargo phase: {error}", file=sys.stderr)
        return 1
    print(f"Selected Deno's {sys.argv[1]} Linux release Cargo command.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
