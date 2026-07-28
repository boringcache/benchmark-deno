# benchmark-deno

Reproducible Linux x86 release and debug build proofs for
[`denoland/deno`](https://github.com/denoland/deno). It compares Deno's current
GitHub Actions `target/` archive strategy with two deliberately separate
BoringCache candidates:

- remote sccache plus only the capped release ThinLTO archive
- remote sccache alone for Deno's ordinary Linux debug build

Stable proof runs pin `boringcache/one` `v1.14.0` by immutable commit and keep
Rust installation in the host workflow. Canary runs require an exact immutable
CLI tag.

The completed proof and the dated prospect assessment are in
[`RESULTS.md`](RESULTS.md) and [`PROSPECT.md`](PROSPECT.md).

## The questions

For a normal adjacent Deno commit on a fresh runner:

1. Does remote compiler reuse plus the narrow ThinLTO archive beat restoring
   the previous commit's multi-gigabyte release `target/` archive?
2. Does remote compiler reuse beat whole-`target/` restoration for the
   high-frequency Linux debug build?

The proof reports the parts needed to answer that honestly:

- cache restore or proxy setup time
- release build time
- restore-plus-build time
- base cache storage
- native `sccache` hits, misses, and non-cacheable compilations

It does not claim that compiler caching accelerates Deno's startup-order trace
or second ThinLTO relink. Those stages are deliberately excluded and called out
in the generated report.

## Pinned rolling pair

The source pair lives in [`benchmark-source.env`](benchmark-source.env):

- base: `0c965f5e5f7105bd6d3fe0d1f696f2c7a3bc6899`
- head: `c3ea533fd836abdf3aa0e205d6c358e60054dd4d`
- change: `runtime/ops/fs_events.rs` and `ext/node/polyfills/fs.ts`

The two commits are parent and child. `prepare-source.sh` verifies that
relationship before either build, so a mistyped or unsuitable pair fails
before spending runner time.

## Comparison

### Actions cache baseline

The baseline mirrors the relevant parts of Deno's generated CI workflow:

1. Build the base commit without restoring `target/`.
2. Save Cargo home and `target/` as separate Actions caches.
3. On a fresh runner, restore both caches for the head commit.
4. Run Deno's pinned `.github/mtime_cache/action.js` implementation from the
   nested Deno checkout.
5. Build the head commit.

The target archive uses the same exclusions as Deno's workflow.

### BoringCache candidates

Both candidates use an immutable `boringcache/one` release in `sccache` proxy
mode:

1. Build the base commit with an empty, run-scoped remote compiler cache.
2. Preserve Cargo registry state. The release-hybrid row additionally archives
   only `target/release/lto-cache`; the debug row archives no build output.
3. On a fresh runner, restore the same run-scoped cache with
   `trust-policy=restore`.
4. Build the head commit and capture `sccache --show-stats`.

All strategies use Rust 1.95.0, Deno's `v2.x` snapshot-minifier runtime, and
Deno's Linux sysroot, LLVM 22, linker-plugin LTO, and ThinLTO cache flags. The
release command includes Deno's release binaries and `denort_desktop`; the
debug command is the pinned ordinary-PR command with
`CARGO_PROFILE_DEV_DEBUG=0`.

## Run it

The repository needs these Actions secrets:

- `BORINGCACHE_RESTORE_TOKEN`
- `BORINGCACHE_SAVE_TOKEN`

Run **Deno release hybrid cache proof** and **Deno Linux debug cache proof**
from the Actions tab. The optional `cli_version` input can pin a canary CLI
release. Each proof runs its two strategies in parallel and publishes one
comparison table and JSON artifact.

## Interpreting the result

The rolling row is the decision row. A useful result should have all three:

- lower restore-plus-build time than the Actions cache baseline
- a high Rust compiler-cache hit rate for the unchanged graph
- materially less stored data than the base Cargo plus target archives

The release-hybrid result is not a pure remote-sccache claim; its artifact names
the ThinLTO archive explicitly. If either rolling build is slower, the report
says so directly. Before proposing a migration, repeat the winning run and add
macOS only after Linux shows a stable win.

## Local checks

The full build is intentionally GitHub-only because it modifies an ephemeral
Ubuntu runner to match Deno's sysroot. The benchmark harness can be checked
locally with:

```console
python3 -m unittest discover -s test -v
shellcheck scripts/*.sh
actionlint .github/workflows/*.yml
```
