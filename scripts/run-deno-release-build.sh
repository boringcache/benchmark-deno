#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}/upstream"

export CARGO_INCREMENTAL=0
export DENO_CANARY=true
export DENO_SNAPSHOT_MINIFY_SOURCES=1

"${repo_root}/scripts/run-cargo-build.sh" --release --locked \
  -p deno \
  -p denort \
  -p test_server \
  --bin deno \
  --bin denort \
  --bin test_server \
  --features=deno/panic-trace

"${repo_root}/scripts/run-cargo-build.sh" --release --locked -p denort_desktop

target/release/deno --version
