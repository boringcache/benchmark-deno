from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


write_phase_result = load_script("write_phase_result.py")
render_comparison = load_script("render_comparison.py")


class SccacheStatsTest(unittest.TestCase):
    def test_parses_hit_rate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stats.txt"
            path.write_text(
                "Compile requests                    12\n"
                "Compile requests executed           10\n"
                "Cache hits                           8\n"
                "Cache misses                         2\n"
                "Non-cacheable compilations           2\n"
            )

            self.assertEqual(
                write_phase_result.parse_sccache_stats(path),
                {
                    "compile_requests": 12,
                    "compile_requests_executed": 10,
                    "cache_hits": 8,
                    "cache_misses": 2,
                    "non_cacheable_compilations": 2,
                    "cache_hit_percent": 80,
                },
            )


class ComparisonReportTest(unittest.TestCase):
    def test_reports_rolling_improvement_without_overselling(self):
        results = {}
        for strategy, base, rolling in (
            ("actions-cache", 1200, 900),
            ("boringcache", 1210, 600),
        ):
            for phase, seconds in (("base", base), ("rolling", rolling)):
                results[(strategy, phase)] = {
                    "strategy": strategy,
                    "phase": phase,
                    "timing": {
                        "restore_seconds": 10,
                        "build_seconds": seconds,
                        "end_to_end_seconds": seconds + 10,
                    },
                    "cache": {"storage_bytes": 1024**3},
                    "sccache": None,
                }

        payload = render_comparison.comparison_payload(results)
        markdown = render_comparison.render_markdown(payload)

        self.assertEqual(payload["rolling_comparison"]["end_to_end_seconds_saved"], 300)
        self.assertEqual(payload["rolling_comparison"]["percent_saved"], 33.0)
        self.assertEqual(payload["rolling_comparison"]["build_seconds_saved"], 300)
        self.assertIn("saved **300s (33.0%)**", markdown)

    def test_requires_all_four_results(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "one.json"
            path.write_text(json.dumps({"strategy": "actions-cache", "phase": "base"}))

            with self.assertRaisesRegex(ValueError, "Missing benchmark results"):
                render_comparison.load_results(Path(directory))


if __name__ == "__main__":
    unittest.main()
