#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${DENO_BENCHMARK_PROFILE:-release}" != "release" ]]; then
  echo "Expected DENO_BENCHMARK_PROFILE=release, got: ${DENO_BENCHMARK_PROFILE}" >&2
  exit 1
fi

exec "${repo_root}/scripts/run-deno-release-build.sh"
