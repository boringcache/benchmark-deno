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

    def test_parses_native_error_and_duration_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stats.txt"
            path.write_text(
                "Compile requests                    20\n"
                "Cache hits                          18\n"
                "Cache hits (Rust)                   17\n"
                "Cache misses                         2\n"
                "Cache misses (C/C++)                 2\n"
                "Cache errors                         3\n"
                "Cache read errors                    0\n"
                "Cache write errors                   3\n"
                "Cache timeouts                       0\n"
                "Average cache read hit           0.004 s\n"
                "Non-cacheable reasons:\n"
                "crate-type                         12\n"
                "missing input                       2\n"
                "\n"
            )

            stats = write_phase_result.parse_sccache_stats(path)

            self.assertEqual(stats["cache_hit_percent"], 90)
            self.assertEqual(stats["cache_hits_rust"], 17)
            self.assertEqual(stats["cache_misses_c_cpp"], 2)
            self.assertEqual(stats["cache_write_errors"], 3)
            self.assertEqual(stats["average_cache_read_hit_seconds"], 0.004)
            self.assertEqual(
                stats["non_cacheable_reasons"], {"crate-type": 12, "missing input": 2}
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

    def test_supports_explicit_hybrid_candidate(self):
        results = {}
        for strategy in ("actions-cache", "boringcache-hybrid"):
            for phase in ("base", "rolling"):
                results[(strategy, phase)] = {
                    "strategy": strategy,
                    "phase": phase,
                    "timing": {
                        "restore_seconds": 5,
                        "build_seconds": 100,
                        "end_to_end_seconds": 105,
                    },
                    "cache": {"storage_bytes": 1024},
                    "sccache": None,
                }

        payload = render_comparison.comparison_payload(
            results,
            candidate_strategy="boringcache-hybrid",
            title="Deno release hybrid cache proof",
        )

        self.assertEqual(payload["candidate_strategy"], "boringcache-hybrid")
        self.assertIn("Deno release hybrid", render_comparison.render_markdown(payload))


if __name__ == "__main__":
    unittest.main()
