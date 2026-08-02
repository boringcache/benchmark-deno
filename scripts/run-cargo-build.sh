#!/usr/bin/env bash
set -euo pipefail

command=(cargo build)
if [[ "${DENO_USE_BORINGCACHE_CARGO:-0}" == "1" ]]; then
  command=(boringcache cargo --fail-on-cache-error)
  case "${DENO_BORINGCACHE_CARGO_ACCESS:-}" in
    publish)
      command+=(--write)
      ;;
    consume)
      command+=(--read-only)
      ;;
    *)
      echo "DENO_BORINGCACHE_CARGO_ACCESS must be publish or consume" >&2
      exit 1
      ;;
  esac
  if [[ "${DENO_BORINGCACHE_CARGO_SKIP_SAVE:-0}" == "1" ]]; then
    command+=(--skip-save)
  fi
  if [[ -n "${DENO_BORINGCACHE_NATIVE_EVIDENCE_DIR:-}" ]]; then
    phase="${DENO_CARGO_PHASE:-build}"
    command+=(--native-tool-evidence-json "${DENO_BORINGCACHE_NATIVE_EVIDENCE_DIR}/${phase}.json")
  fi
  if [[ -n "${DENO_BORINGCACHE_METADATA_PHASE:-}" ]]; then
    command+=(--metadata-hint "phase=${DENO_BORINGCACHE_METADATA_PHASE}")
  fi
  command+=(build)
fi

if [[ -z "${DENO_CARGO_EVIDENCE_FILE:-}" ]]; then
  exec "${command[@]}" "$@"
fi

mkdir -p "$(dirname "$DENO_CARGO_EVIDENCE_FILE")"
"${command[@]}" --message-format=json-render-diagnostics "$@" |
  tee -a "$DENO_CARGO_EVIDENCE_FILE"
