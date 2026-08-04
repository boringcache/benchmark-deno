#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "${repo_root}/scripts/deno-release-recipe.env"

echo "RUSTC_BOOTSTRAP=1" >> "$GITHUB_ENV"
{
  echo "RUSTFLAGS<<__DENO_RUSTFLAGS"
  echo "$RUSTFLAGS ${DENO_FRAME_POINTER_RUSTFLAGS}"
  echo "__DENO_RUSTFLAGS"
} >> "$GITHUB_ENV"
