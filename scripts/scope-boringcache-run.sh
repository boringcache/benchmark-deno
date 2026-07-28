#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
scope="${1:-}"

if [[ ! "$scope" =~ ^r[0-9]+-a[0-9]+$ ]]; then
  echo "Expected a run scope such as r123-a1, got: ${scope:-<empty>}" >&2
  exit 1
fi

config_path="${repo_root}/.boringcache.toml"
for base_tag in \
  deno-cargo-registry \
  deno-release-lto-cache \
  deno-rust-cache; do
  old_tag="${base_tag}-local"
  new_tag="${base_tag}-${scope}"
  if ! grep -Fq "tag = \"${old_tag}\"" "$config_path"; then
    echo "Missing expected local tag in ${config_path}: ${old_tag}" >&2
    exit 1
  fi
  sed -i "s/tag = \"${old_tag}\"/tag = \"${new_tag}\"/" "$config_path"
done

echo "Scoped BoringCache tags to ${scope}."
