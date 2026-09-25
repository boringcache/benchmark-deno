#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def objects_in(bucket: str, prefix: str) -> list[dict]:
    result = subprocess.run(
        ["aws", "s3api", "list-objects-v2", "--bucket", bucket, "--prefix", prefix, "--output", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout).get("Contents", [])


def size_of(objects: list[dict]) -> int:
    return sum(item["Size"] for item in objects)


def metrics_shape(bucket: str, key: str) -> dict:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "metrics.jsonl"
        subprocess.run(
            ["aws", "s3api", "get-object", "--bucket", bucket, "--key", key, str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
        fields: set[str] = set()
        nested_fields: dict[str, set[str]] = {}
        kinds: set[str] = set()
        metric_shapes: dict[str, list[str]] = {}
        network_samples: list[dict] = []
        sampled = 0
        with path.open() as source:
            for line in source:
                if sampled == 500:
                    break
                record = json.loads(line)
                if not isinstance(record, dict):
                    continue
                sampled += 1
                fields.update(record)
                for name, value in record.items():
                    if isinstance(value, dict):
                        nested_fields.setdefault(name, set()).update(value)
                    elif name in ("name", "metric", "type") and isinstance(value, str):
                        kinds.add(value)
                for resource in record.get("resourceMetrics", []):
                    for scope in resource.get("scopeMetrics", []):
                        for metric in scope.get("metrics", []):
                            metric_shapes[metric["name"]] = sorted(metric)
                            if metric["name"] == "system.network.io" and not network_samples:
                                network_sum = metric.get("sum", {})
                                for point in network_sum.get("dataPoints", [])[:4]:
                                    network_samples.append(
                                        {
                                            "unit": metric.get("unit"),
                                            "temporality": network_sum.get("aggregationTemporality"),
                                            "monotonic": network_sum.get("isMonotonic"),
                                            "value": point.get("asInt", point.get("asDouble")),
                                            "time_unix_nano": point.get("timeUnixNano"),
                                            "attributes": {
                                                attribute["key"]: attribute.get("value")
                                                for attribute in point.get("attributes", [])
                                            },
                                        }
                                    )
        return {
            "sampled_records": sampled,
            "fields": sorted(fields),
            "nested_fields": {name: sorted(values) for name, values in nested_fields.items()},
            "kinds": sorted(kinds)[:50],
            "metric_shapes": metric_shapes,
            "network_samples": network_samples,
        }


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in ("before", "after"):
        print("Usage: report-runs-on-s3.py before|after OUTPUT.json", file=sys.stderr)
        return 2

    run_id = os.environ.get("INSPECT_RUN_ID") or os.environ["GITHUB_RUN_ID"]
    bucket = os.environ.get("RUNS_ON_S3_BUCKET_CACHE", "")
    repo_prefix = os.environ.get("RUNS_ON_S3_CACHE_REPO_PREFIX", "")
    prefix = repo_prefix.rstrip("/") + "/" if repo_prefix else ""
    report = {
        "snapshot": sys.argv[1],
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "observation_run_id": os.environ["GITHUB_RUN_ID"],
        "bucket": bucket,
        "cache_prefix": prefix,
    }

    if not bucket or not prefix:
        report["cache_status"] = "unavailable"
        report["cache_reason"] = "RunsOn did not provide the cache bucket and repository prefix"
        report["metrics_status"] = "unavailable"
        Path(sys.argv[2]).write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
        return 0

    try:
        cache_objects = objects_in(bucket, prefix)
    except (OSError, subprocess.CalledProcessError, ValueError):
        report["cache_status"] = "unavailable"
        report["cache_reason"] = "S3 ListObjectsV2 did not return a cache inventory"
    else:
        run_objects = [item for item in cache_objects if re.search(rf"r{re.escape(run_id)}-a\d+", item["Key"])]
        report.update(
            cache_status="available",
            cache_objects=len(cache_objects),
            cache_bytes=size_of(cache_objects),
            run_key_objects=len(run_objects),
            run_key_bytes=size_of(run_objects),
        )

    metrics_prefix = f"cache/metrics/v1/boringcache/benchmark-deno/{run_id}/"
    try:
        metric_objects = objects_in(bucket, metrics_prefix)
    except (OSError, subprocess.CalledProcessError, ValueError):
        report["metrics_status"] = "unavailable"
    else:
        report.update(
            metrics_status="available",
            metrics_objects=len(metric_objects),
            metrics_bytes=size_of(metric_objects),
        )
        if metric_objects:
            try:
                report["metrics_shape"] = metrics_shape(bucket, metric_objects[0]["Key"])
            except (OSError, subprocess.CalledProcessError, ValueError):
                report["metrics_shape_status"] = "unavailable"

    try:
        cache_tree = objects_in(bucket, "cache/")
    except (OSError, subprocess.CalledProcessError, ValueError):
        report["cache_tree_status"] = "unavailable"
    else:
        groups: dict[str, dict[str, int]] = {}
        for item in cache_tree:
            group = "/".join(item["Key"].split("/")[:4])
            totals = groups.setdefault(group, {"objects": 0, "bytes": 0})
            totals["objects"] += 1
            totals["bytes"] += item["Size"]
        report.update(
            cache_tree_status="available",
            cache_tree_objects=len(cache_tree),
            cache_tree_bytes=size_of(cache_tree),
            cache_tree_largest_prefixes=[
                {"prefix": group, **totals}
                for group, totals in sorted(groups.items(), key=lambda pair: pair[1]["bytes"], reverse=True)[:25]
            ],
        )

    try:
        bucket_objects = objects_in(bucket, "")
    except (OSError, subprocess.CalledProcessError, ValueError):
        report["bucket_status"] = "unavailable"
    else:
        groups: dict[str, dict[str, int]] = {}
        for item in bucket_objects:
            group = "/".join(item["Key"].split("/")[:4])
            totals = groups.setdefault(group, {"objects": 0, "bytes": 0})
            totals["objects"] += 1
            totals["bytes"] += item["Size"]
        report.update(
            bucket_status="available",
            bucket_objects=len(bucket_objects),
            bucket_bytes=size_of(bucket_objects),
            largest_prefixes=[
                {"prefix": group, **totals}
                for group, totals in sorted(groups.items(), key=lambda pair: pair[1]["bytes"], reverse=True)[:25]
            ],
        )

    Path(sys.argv[2]).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
