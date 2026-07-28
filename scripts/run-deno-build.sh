#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

case "${DENO_BENCHMARK_PROFILE:-release}" in
  release)
    exec "${repo_root}/scripts/run-deno-release-build.sh"
    ;;
  debug)
    exec "${repo_root}/scripts/run-deno-debug-build.sh"
    ;;
  *)
    echo "Expected DENO_BENCHMARK_PROFILE=release or debug, got: ${DENO_BENCHMARK_PROFILE}" >&2
    exit 1
    ;;
esac
