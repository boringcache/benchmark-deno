#!/usr/bin/env bash
set -euo pipefail

version="${1:-0.16.0}"
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Expected an exact sccache version such as 0.16.0" >&2
  exit 1
fi
if [[ "$(uname -s)-$(uname -m)" != "Linux-x86_64" ]]; then
  echo "The Deno sccache installer currently supports Linux x86_64 only." >&2
  exit 1
fi

release="v${version}"
directory="sccache-${release}-x86_64-unknown-linux-musl"
archive="${directory}.tar.gz"
release_url="https://github.com/mozilla/sccache/releases/download/${release}"
temporary_dir="$(mktemp -d)"
trap 'rm -rf "$temporary_dir"' EXIT

curl --fail --silent --show-error --location \
  "${release_url}/${archive}" \
  --output "${temporary_dir}/${archive}"
curl --fail --silent --show-error --location \
  "${release_url}/${archive}.sha256" \
  --output "${temporary_dir}/${archive}.sha256"

expected="$(awk 'NR == 1 { print $1 }' "${temporary_dir}/${archive}.sha256")"
actual="$(sha256sum "${temporary_dir}/${archive}" | awk '{ print $1 }')"
[[ "$expected" == "$actual" ]] || {
  echo "sccache checksum verification failed" >&2
  exit 1
}

tar -xzf "${temporary_dir}/${archive}" -C "$temporary_dir"
bin_dir="${RUNNER_TEMP:-/tmp}/sccache-${version}/bin"
mkdir -p "$bin_dir"
install -m 0755 "${temporary_dir}/${directory}/sccache" "${bin_dir}/sccache"
"${bin_dir}/sccache" --version

if [[ -n "${GITHUB_PATH:-}" ]]; then
  printf '%s\n' "$bin_dir" >> "$GITHUB_PATH"
fi
printf '%s\n' "$bin_dir"
