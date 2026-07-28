#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
scope="${1:-}"
sccache_scope="${2:-$scope}"

if [[ ! "$scope" =~ ^r[0-9]+-a[0-9]+$ ]]; then
  echo "Expected a run scope such as r123-a1, got: ${scope:-<empty>}" >&2
  exit 1
fi
if [[ ! "$sccache_scope" =~ ^r[0-9]+-a[0-9]+$ ]]; then
  echo "Expected an sccache scope such as r123-a1, got: ${sccache_scope:-<empty>}" >&2
  exit 1
fi

config_path="${repo_root}/.boringcache.toml"
for base_tag in \
  deno-cargo-registry \
  deno-release-lto-cache \
  deno-actions-cargo-registry \
  deno-actions-cargo-git \
  deno-actions-cargo-bin \
  deno-actions-target; do
  old_tag="${base_tag}-local"
  new_tag="${base_tag}-${scope}"
  if ! grep -Fq "tag = \"${old_tag}\"" "$config_path"; then
    echo "Missing expected local tag in ${config_path}: ${old_tag}" >&2
    exit 1
  fi
  sed -i "s/tag = \"${old_tag}\"/tag = \"${new_tag}\"/" "$config_path"
done

sccache_old_tag="deno-rust-cache-local"
sccache_new_tag="deno-rust-cache-${sccache_scope}"
if ! grep -Fq "tag = \"${sccache_old_tag}\"" "$config_path"; then
  echo "Missing expected local tag in ${config_path}: ${sccache_old_tag}" >&2
  exit 1
fi
sed -i "s/tag = \"${sccache_old_tag}\"/tag = \"${sccache_new_tag}\"/" "$config_path"

echo "Scoped archive tags to ${scope} and sccache to ${sccache_scope}."
