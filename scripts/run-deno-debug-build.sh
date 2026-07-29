#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}/upstream"

export CARGO_PROFILE_DEV_DEBUG=0

"${repo_root}/scripts/run-cargo-build.sh" --locked \
  -p deno \
  -p denort \
  -p test_server \
  --bin deno \
  --bin denort \
  --bin test_server \
  --features=deno/panic-trace

NO_COLOR=1 target/debug/deno eval "console.log(1+2)" | grep 3
