#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
scope="${1:-}"

if [[ ! "$scope" =~ ^[a-z0-9][a-z0-9._-]+$ ]]; then
  echo "Expected a lowercase benchmark cache scope, got: ${scope:-<empty>}" >&2
  exit 1
fi

config_path="${repo_root}/.boringcache.toml"
for base_tag in \
  deno-cargo-registry-cache \
  deno-cargo-registry-index \
  deno-cargo-git-db \
  deno-cargo-target; do
  old_tag="${base_tag}-local"
  new_tag="${base_tag}-${scope}"
  if ! grep -Fq "tag = \"${old_tag}\"" "$config_path"; then
    echo "Missing expected local tag in ${config_path}: ${old_tag}" >&2
    exit 1
  fi
  sed -i "s/tag = \"${old_tag}\"/tag = \"${new_tag}\"/" "$config_path"
done

sccache_old_tag="deno-rust-cache-local"
sccache_new_tag="deno-rust-cache-${scope}"
if ! grep -Fq "tag = \"${sccache_old_tag}\"" "$config_path"; then
  echo "Missing expected local tag in ${config_path}: ${sccache_old_tag}" >&2
  exit 1
fi
sed -i "s/tag = \"${sccache_old_tag}\"/tag = \"${sccache_new_tag}\"/" "$config_path"

echo "Scoped narrow Cargo dependency, target, and sccache tags to ${scope}."
