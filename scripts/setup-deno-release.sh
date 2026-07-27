#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
upstream_dir="${repo_root}/upstream"
github_env="${GITHUB_ENV:-}"
llvm_version=22
sysroot_release=sysroot-20250207

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
  echo "The Deno release proof currently supports Linux x86_64 only." >&2
  exit 1
fi
if [[ -z "$github_env" ]]; then
  echo "GITHUB_ENV is required; run this script inside GitHub Actions." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
sudo apt-get -qq remove --purge -y man-db >/dev/null 2>&1 || true
sudo apt-get -qq remove -y \
  'clang-12*' 'clang-13*' 'clang-14*' 'clang-15*' 'clang-16*' \
  'clang-17*' 'clang-18*' 'clang-19*' 'clang-20*' 'clang-21*' \
  'llvm-12*' 'llvm-13*' 'llvm-14*' 'llvm-15*' 'llvm-16*' \
  'llvm-17*' 'llvm-18*' 'llvm-19*' 'llvm-20*' 'llvm-21*' \
  'lld-12*' 'lld-13*' 'lld-14*' 'lld-15*' 'lld-16*' 'lld-17*' \
  'lld-18*' 'lld-19*' 'lld-20*' 'lld-21*' >/dev/null 2>&1 || true

echo "deb http://apt.llvm.org/noble/ llvm-toolchain-noble-${llvm_version} main" \
  | sudo tee "/etc/apt/sources.list.d/llvm-toolchain-noble-${llvm_version}.list" >/dev/null
curl -fsSL https://apt.llvm.org/llvm-snapshot.gpg.key \
  | gpg --dearmor \
  | sudo tee /etc/apt/trusted.gpg.d/llvm-snapshot.gpg >/dev/null

sudo apt-get update
install_llvm() {
  sudo apt-get install -y --no-install-recommends \
    "clang-${llvm_version}" \
    "lld-${llvm_version}" \
    "clang-tools-${llvm_version}" \
    "clang-format-${llvm_version}" \
    "clang-tidy-${llvm_version}"
}
install_llvm || {
  echo "LLVM installation failed; cleaning apt state and retrying once." >&2
  sudo apt-get clean
  sudo apt-get update
  install_llvm
}
(yes '' | sudo update-alternatives --force --all) >/dev/null 2>&1 || true

"clang-${llvm_version}" -c \
  -o /tmp/deno-benchmark-memfd-create-shim.o \
  "${upstream_dir}/tools/memfd_create_shim.c" \
  -fPIC
"clang-${llvm_version}" -c \
  -o /tmp/deno-benchmark-glibc-math-shim.o \
  "${upstream_dir}/tools/glibc_math_shim.c" \
  -fPIC

sysroot_archive="${RUNNER_TEMP:-/tmp}/deno-benchmark-sysroot.tar.xz"
wget -q \
  "https://github.com/denoland/deno_sysroot_build/releases/download/${sysroot_release}/sysroot-$(uname -m).tar.xz" \
  -O "$sysroot_archive"
sudo tar -xJf "$sysroot_archive" -C /

mount_sysroot_path() {
  local source_path="$1"
  local target_path="/sysroot${source_path}"
  if ! mountpoint -q "$target_path"; then
    sudo mount --rbind "$source_path" "$target_path"
  fi
}
mount_sysroot_path /dev
mount_sysroot_path /sys
mount_sysroot_path /home
if ! mountpoint -q /sysroot/proc; then
  sudo mount -t proc /proc /sysroot/proc
fi

# The sysroot supplies the base CFLAGS and Rust flags. Match Deno's generated
# CI workflow, then persist the fully expanded values for the build step.
set +u
# shellcheck disable=SC1091
source /sysroot/.env
set -u

{
  echo "CARGO_PROFILE_BENCH_INCREMENTAL=false"
  echo "CARGO_PROFILE_RELEASE_INCREMENTAL=false"
  echo "CC=/usr/bin/clang-${llvm_version}"
  echo "CFLAGS=${CFLAGS:-}"
  echo "RUSTFLAGS<<DENO_BENCHMARK_RUSTFLAGS"
  cat <<EOF
  -C linker-plugin-lto=true
  -C linker=clang-${llvm_version}
  -C link-arg=-fuse-ld=lld-${llvm_version}
  -C link-arg=-Wl,--icf=safe
  -C link-arg=-ldl
  -C link-arg=-Wl,--allow-shlib-undefined
  -C link-arg=-Wl,--thinlto-cache-dir=${upstream_dir}/target/release/lto-cache
  -C link-arg=-Wl,--thinlto-cache-policy,cache_size_bytes=700m
  -C link-arg=/tmp/deno-benchmark-memfd-create-shim.o
  -C link-arg=/tmp/deno-benchmark-glibc-math-shim.o
  -C link-arg=-Wl,--wrap=expf
  -C link-arg=-Wl,--wrap=powf
  -C link-arg=-Wl,--wrap=exp2f
  -C link-arg=-Wl,--wrap=log2f
  -C link-arg=-Wl,--wrap=logf
  --cfg tokio_unstable
  ${RUSTFLAGS:-}
EOF
  echo "DENO_BENCHMARK_RUSTFLAGS"
  echo "RUSTDOCFLAGS<<DENO_BENCHMARK_RUSTDOCFLAGS"
  cat <<EOF
  -C linker-plugin-lto=true
  -C linker=clang-${llvm_version}
  -C link-arg=-fuse-ld=lld-${llvm_version}
  -C link-arg=-Wl,--icf=safe
  -C link-arg=-ldl
  -C link-arg=-Wl,--allow-shlib-undefined
  -C link-arg=-Wl,--thinlto-cache-dir=${upstream_dir}/target/release/lto-cache
  -C link-arg=-Wl,--thinlto-cache-policy,cache_size_bytes=700m
  -C link-arg=/tmp/deno-benchmark-memfd-create-shim.o
  -C link-arg=/tmp/deno-benchmark-glibc-math-shim.o
  -C link-arg=-Wl,--wrap=expf
  -C link-arg=-Wl,--wrap=powf
  -C link-arg=-Wl,--wrap=exp2f
  -C link-arg=-Wl,--wrap=log2f
  -C link-arg=-Wl,--wrap=logf
  --cfg tokio_unstable
  ${RUSTFLAGS:-}
EOF
  echo "DENO_BENCHMARK_RUSTDOCFLAGS"
} >> "$github_env"

echo "Configured Deno's Linux release sysroot and LLVM ${llvm_version} environment."
