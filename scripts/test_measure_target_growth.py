#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from measure_target_growth import compare, snapshot


class MeasureTargetGrowthTest(unittest.TestCase):
    def test_reports_small_parent_to_successor_change_as_stable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "target"
            root.mkdir()
            artifact = root / "release" / "artifact"
            artifact.parent.mkdir()
            artifact.write_bytes(b"seed")
            before = snapshot(root, "parent")

            artifact.write_bytes(b"rolling")
            after = snapshot(root, "successor")
            growth = compare(before, after)

        self.assertEqual(growth["classification"], "stable")
        self.assertEqual(growth["logical_bytes_delta"], 3)
        self.assertEqual(growth["files_delta"], 0)
        self.assertEqual(growth["before"]["source_sha"], "parent")
        self.assertEqual(growth["after"]["source_sha"], "successor")


if __name__ == "__main__":
    unittest.main()
