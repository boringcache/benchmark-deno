#!/usr/bin/env bash
set -euo pipefail

tag="${1:-}"
if [[ ! "$tag" =~ ^vcli-canary-[0-9a-f]{12}$ ]]; then
  echo "Expected an immutable CLI canary tag such as vcli-canary-0123456789ab" >&2
  exit 1
fi
if [[ "$(uname -s)-$(uname -m)" != "Linux-x86_64" ]]; then
  echo "The Deno canary proof currently supports Linux x86_64 only." >&2
  exit 1
fi

asset="boringcache-linux-amd64"
release_url="https://github.com/boringcache/cli/releases/download/${tag}"
temporary_dir="$(mktemp -d)"
trap 'rm -rf "$temporary_dir"' EXIT

curl --fail --silent --show-error --location \
  "${release_url}/${asset}" \
  --output "${temporary_dir}/${asset}"
curl --fail --silent --show-error --location \
  "${release_url}/SHA256SUMS" \
  --output "${temporary_dir}/SHA256SUMS"

checksum_line="$(awk -v asset="$asset" '$2 == asset { print; found = 1 } END { if (!found) exit 1 }' "${temporary_dir}/SHA256SUMS")"
(
  cd "$temporary_dir"
  printf '%s\n' "$checksum_line" | sha256sum --check -
)

bin_dir="${RUNNER_TEMP:-/tmp}/boringcache-canary-${tag}/bin"
mkdir -p "$bin_dir"
install -m 0755 "${temporary_dir}/${asset}" "${bin_dir}/boringcache"
"${bin_dir}/boringcache" --version

if [[ -n "${GITHUB_PATH:-}" ]]; then
  printf '%s\n' "$bin_dir" >> "$GITHUB_PATH"
fi
printf '%s\n' "$bin_dir"
