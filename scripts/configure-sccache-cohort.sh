#!/usr/bin/env bash
set -euo pipefail

mode="${1:-}"
github_env="${GITHUB_ENV:-}"
cache_dir="${HOME}/.cache/sccache"

case "$mode" in
  disk)
    chain="disk"
    ;;
  disk-webdav)
    chain="disk,webdav"
    ;;
  webdav)
    chain="webdav"
    ;;
  *)
    echo "Usage: $0 <disk|disk-webdav|webdav>" >&2
    exit 1
    ;;
esac

if [[ "$chain" == *webdav* ]]; then
    [[ -n "${SCCACHE_WEBDAV_ENDPOINT:-}" ]] || {
      echo "The WebDAV cohort requires the adapter-owned endpoint" >&2
      exit 1
    }
fi

[[ -n "$github_env" ]] || { echo "GITHUB_ENV is required" >&2; exit 1; }
command -v sccache >/dev/null || { echo "sccache is not installed" >&2; exit 1; }
[[ -n "${CC:-}" ]] || { echo "Deno's pinned CC must be configured first" >&2; exit 1; }

export RUSTC_WRAPPER=sccache
export CARGO_INCREMENTAL=0
export CXX="${CXX:-sccache c++}"
export SCCACHE_DIR="$cache_dir"
export SCCACHE_CACHE_SIZE="${SCCACHE_CACHE_SIZE:-5G}"
export SCCACHE_IDLE_TIMEOUT=0
export SCCACHE_MULTILEVEL_CHAIN="$chain"
# The seed is the authority for both later representations. sccache v0.16's
# strict policy makes the build fail unless every writable level accepts each
# compiler artifact, rather than silently proving only the local disk level.
export SCCACHE_MULTILEVEL_WRITE_ERROR_POLICY=all

mkdir -p "$cache_dir"
sccache --stop-server >/dev/null 2>&1 || true
sccache --start-server >/dev/null

{
  echo "RUSTC_WRAPPER=${RUSTC_WRAPPER}"
  echo "CARGO_INCREMENTAL=${CARGO_INCREMENTAL}"
  echo "CXX=${CXX}"
  echo "SCCACHE_DIR=${SCCACHE_DIR}"
  echo "SCCACHE_CACHE_SIZE=${SCCACHE_CACHE_SIZE}"
  echo "SCCACHE_IDLE_TIMEOUT=${SCCACHE_IDLE_TIMEOUT}"
  echo "SCCACHE_MULTILEVEL_CHAIN=${SCCACHE_MULTILEVEL_CHAIN}"
  echo "SCCACHE_MULTILEVEL_WRITE_ERROR_POLICY=${SCCACHE_MULTILEVEL_WRITE_ERROR_POLICY}"
} >> "$github_env"

echo "Configured the sccache cohort: CC=${CC}, CXX=${CXX}, chain=${chain}"
