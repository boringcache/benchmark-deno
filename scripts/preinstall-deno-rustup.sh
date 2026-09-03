#!/usr/bin/env bash
set -euo pipefail

# Keep this semantically equivalent to Deno's generated rustup workaround; the
# wrapper only adapts it to the benchmark repository layout.
if command -v rustup >/dev/null 2>&1; then
  if ! rustup --version 2>&1 | grep -q '1\.29\.0'; then
    exit 0
  fi
  echo "Detected broken rustup 1.29.0, replacing with 1.28.2"
fi

case "${RUNNER_OS}-${RUNNER_ARCH}" in
  Linux-X64) target=x86_64-unknown-linux-gnu; ext= ;;
  Linux-ARM64) target=aarch64-unknown-linux-gnu; ext= ;;
  macOS-X64) target=x86_64-apple-darwin; ext= ;;
  macOS-ARM64) target=aarch64-apple-darwin; ext= ;;
  Windows-X64) target=x86_64-pc-windows-msvc; ext=.exe ;;
  Windows-ARM64) target=aarch64-pc-windows-msvc; ext=.exe ;;
  *) echo "Unsupported: ${RUNNER_OS}-${RUNNER_ARCH}"; exit 1 ;;
esac

curl --proto '=https' --tlsv1.2 --retry 10 --retry-connrefused -fsSL \
  "https://static.rust-lang.org/rustup/archive/1.28.2/${target}/rustup-init${ext}" \
  -o "rustup-init${ext}"
chmod +x "rustup-init${ext}"
"./rustup-init${ext}" -y --default-toolchain none --no-modify-path
rm "rustup-init${ext}"
echo "${CARGO_HOME:-$HOME/.cargo}/bin" >> "$GITHUB_PATH"
