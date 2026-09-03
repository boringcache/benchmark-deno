#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "${repo_root}/scripts/deno-release-recipe.env"
llvm_version="${DENO_LLVM_VERSION}"
sysroot_release="${DENO_SYSROOT_RELEASE}"

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
  echo "The Deno release proof currently supports Linux x86_64 only." >&2
  exit 1
fi
if [[ -z "${GITHUB_ENV:-}" ]]; then
  echo "GITHUB_ENV is required; run this script inside GitHub Actions." >&2
  exit 1
fi

cd "${repo_root}/upstream"

# Keep this step semantically aligned with Deno's generated
# "Set up incremental LTO and sysroot build" step.
export DEBIAN_FRONTEND=noninteractive
sudo apt-get -qq remove --purge -y man-db >/dev/null 2>&1
sudo apt-get -qq remove \
  'clang-12*' 'clang-13*' 'clang-14*' 'clang-15*' 'clang-16*' \
  'clang-17*' 'clang-18*' 'clang-19*' 'clang-20*' 'clang-21*' \
  'llvm-12*' 'llvm-13*' 'llvm-14*' 'llvm-15*' 'llvm-16*' \
  'llvm-17*' 'llvm-18*' 'llvm-19*' 'llvm-20*' 'llvm-21*' \
  'lld-12*' 'lld-13*' 'lld-14*' 'lld-15*' 'lld-16*' 'lld-17*' \
  'lld-18*' 'lld-19*' 'lld-20*' 'lld-21*' >/dev/null 2>&1

echo "deb http://apt.llvm.org/noble/ llvm-toolchain-noble-${llvm_version} main" \
  | sudo dd of="/etc/apt/sources.list.d/llvm-toolchain-noble-${llvm_version}.list"
curl https://apt.llvm.org/llvm-snapshot.gpg.key \
  | gpg --dearmor \
  | sudo dd of=/etc/apt/trusted.gpg.d/llvm-snapshot.gpg
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  "clang-${llvm_version}" "lld-${llvm_version}" "clang-tools-${llvm_version}" \
  "clang-format-${llvm_version}" "clang-tidy-${llvm_version}" || (
  echo 'Failed. Trying again.'
  sudo apt-get clean
  sudo apt-get update
  sudo apt-get install -y --no-install-recommends \
    "clang-${llvm_version}" "lld-${llvm_version}" "clang-tools-${llvm_version}" \
    "clang-format-${llvm_version}" "clang-tidy-${llvm_version}"
)
(yes '' | sudo update-alternatives --force --all) >/dev/null 2>&1 || true

"clang-${llvm_version}" -c -o /tmp/memfd_create_shim.o tools/memfd_create_shim.c -fPIC
"clang-${llvm_version}" -c -o /tmp/glibc_math_shim.o tools/glibc_math_shim.c -fPIC

echo "Decompressing sysroot..."
curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
  --retry 5 --retry-all-errors --retry-delay 2 \
  --output /tmp/sysroot.tar.xz \
  "https://github.com/denoland/deno_sysroot_build/releases/download/${sysroot_release}/sysroot-$(uname -m).tar.xz"
cd /
xzcat /tmp/sysroot.tar.xz | sudo tar -x
sudo mount --rbind /dev /sysroot/dev
sudo mount --rbind /sys /sysroot/sys
sudo mount --rbind /home /sysroot/home
sudo mount -t proc /proc /sysroot/proc
cd

echo "Done."
echo "sysroot env:"
cat /sysroot/.env
set +u
# shellcheck disable=SC1091
source /sysroot/.env

echo "
CARGO_PROFILE_BENCH_INCREMENTAL=false
CARGO_PROFILE_RELEASE_INCREMENTAL=false
RUSTFLAGS<<__DENO_BASE_RUSTFLAGS
  -C linker-plugin-lto=true
  -C linker=clang-${llvm_version}
  -C link-arg=-fuse-ld=lld-${llvm_version}
  -C link-arg=-Wl,--icf=safe
  -C link-arg=-ldl
  -C link-arg=-Wl,--allow-shlib-undefined
  -C link-arg=-Wl,--thinlto-cache-dir=$(pwd)/target/release/lto-cache
  -C link-arg=-Wl,--thinlto-cache-policy,cache_size_bytes=700m
  -C link-arg=/tmp/memfd_create_shim.o
  -C link-arg=/tmp/glibc_math_shim.o
  -C link-arg=-Wl,--wrap=expf
  -C link-arg=-Wl,--wrap=powf
  -C link-arg=-Wl,--wrap=exp2f
  -C link-arg=-Wl,--wrap=log2f
  -C link-arg=-Wl,--wrap=logf
  --cfg tokio_unstable
  $RUSTFLAGS
__DENO_BASE_RUSTFLAGS
RUSTDOCFLAGS<<__DENO_BASE_RUSTDOCFLAGS
  -C linker-plugin-lto=true
  -C linker=clang-${llvm_version}
  -C link-arg=-fuse-ld=lld-${llvm_version}
  -C link-arg=-Wl,--icf=safe
  -C link-arg=-ldl
  -C link-arg=-Wl,--allow-shlib-undefined
  -C link-arg=-Wl,--thinlto-cache-dir=$(pwd)/target/release/lto-cache
  -C link-arg=-Wl,--thinlto-cache-policy,cache_size_bytes=700m
  -C link-arg=/tmp/memfd_create_shim.o
  -C link-arg=/tmp/glibc_math_shim.o
  -C link-arg=-Wl,--wrap=expf
  -C link-arg=-Wl,--wrap=powf
  -C link-arg=-Wl,--wrap=exp2f
  -C link-arg=-Wl,--wrap=log2f
  -C link-arg=-Wl,--wrap=logf
  --cfg tokio_unstable
  $RUSTFLAGS
__DENO_BASE_RUSTDOCFLAGS
CC=/usr/bin/clang-${llvm_version}
CFLAGS=$CFLAGS
" > "$GITHUB_ENV"
set -u
