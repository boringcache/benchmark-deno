#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# The benchmark source pins are repository data loaded from a fixed path.
# shellcheck disable=SC1091
source "${repo_root}/benchmark-source.env"

scenario="${1:-}"
case "$scenario" in
  base)
    source_sha="$DENO_BASE_SHA"
    ;;
  head)
    source_sha="$DENO_HEAD_SHA"
    ;;
  *)
    echo "Usage: prepare-source.sh base|head" >&2
    exit 1
    ;;
esac

upstream_dir="${repo_root}/upstream"
if [[ ! -d "${upstream_dir}/.git" ]]; then
  echo "Missing Deno checkout at ${upstream_dir}" >&2
  exit 1
fi

if ! git -C "$upstream_dir" cat-file -e "${DENO_HEAD_SHA}^{commit}" 2>/dev/null; then
  git -C "$upstream_dir" fetch --no-tags --depth 2 origin "$DENO_HEAD_SHA"
fi
if ! git -C "$upstream_dir" cat-file -e "${DENO_BASE_SHA}^{commit}" 2>/dev/null; then
  git -C "$upstream_dir" fetch --no-tags --depth 1 origin "$DENO_BASE_SHA"
fi

actual_parent="$(git -C "$upstream_dir" rev-parse "${DENO_HEAD_SHA}^")"
if [[ "$actual_parent" != "$DENO_BASE_SHA" ]]; then
  echo "Pinned Deno commits are not adjacent: ${DENO_HEAD_SHA}^ is ${actual_parent}" >&2
  exit 1
fi

git -C "$upstream_dir" reset --hard "$source_sha"
git -C "$upstream_dir" clean -fdx

echo "Prepared Deno ${scenario} source at ${source_sha}"
git -C "$upstream_dir" status --short
