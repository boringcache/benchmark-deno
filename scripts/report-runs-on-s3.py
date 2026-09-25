#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
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


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in ("before", "after"):
        print("Usage: report-runs-on-s3.py before|after OUTPUT.json", file=sys.stderr)
        return 2

    run_id = os.environ["GITHUB_RUN_ID"]
    bucket = os.environ.get("RUNS_ON_S3_BUCKET_CACHE", "")
    repo_prefix = os.environ.get("RUNS_ON_S3_CACHE_REPO_PREFIX", "")
    prefix = repo_prefix.rstrip("/") + "/" if repo_prefix else ""
    report = {
        "snapshot": sys.argv[1],
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
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

    Path(sys.argv[2]).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
