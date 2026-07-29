#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DENO_CARGO_EVIDENCE_FILE:-}" ]]; then
  exec cargo build "$@"
fi

mkdir -p "$(dirname "$DENO_CARGO_EVIDENCE_FILE")"
cargo build --message-format=json-render-diagnostics "$@" |
  tee -a "$DENO_CARGO_EVIDENCE_FILE"
