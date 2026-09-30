#!/usr/bin/env python3
from __future__ import annotations

import runpy
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SELECTOR = runpy.run_path(str(ROOT / "scripts/select-deno-cargo-phase.py"))


class CargoCommandsTest(unittest.TestCase):
    def test_job_lifecycle_removes_only_the_embedded_command(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".boringcache.toml"
            path.write_text((ROOT / ".boringcache.toml").read_text())
            expected = tomllib.loads(path.read_text())
            del expected["adapters"]["cargo"]["command"]
            SELECTOR["select_job_lifecycle"](path)
            self.assertEqual(tomllib.loads(path.read_text()), expected)

    def test_both_commands_use_the_release_recipe_and_return_build_failure(self):
        settings = SELECTOR["read_settings"](ROOT / "scripts/deno-release-recipe.env")
        for phase in ("primary", "desktop"):
            with self.subTest(phase=phase), patch("sys.argv", ["select-deno-cargo-phase.py", "run", phase]), patch("subprocess.run") as build:
                build.return_value.returncode = 7
                self.assertEqual(SELECTOR["main"](), 7)
                build.assert_called_once_with(
                    SELECTOR["cargo_command"](settings, phase),
                    cwd=ROOT / "upstream",
                    check=False,
                )


if __name__ == "__main__":
    unittest.main()
