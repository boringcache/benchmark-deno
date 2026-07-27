# benchmark-deno

Reproducible Linux x86 release-build proof for
[`denoland/deno`](https://github.com/denoland/deno). It compares Deno's current
GitHub Actions `target/` archive strategy with BoringCache's managed remote
Rust compiler cache.

Stable proof runs pin `boringcache/one` `v1.14.0` by immutable commit and keep
Rust installation in the host workflow. Canary runs require an exact immutable
CLI tag.

The completed proof and the dated prospect assessment are in
[`RESULTS.md`](RESULTS.md) and [`PROSPECT.md`](PROSPECT.md).

## The question

For a normal adjacent Deno commit on a fresh runner, does remote compiler
artifact reuse beat restoring the previous commit's multi-gigabyte `target/`
archive?

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

### BoringCache candidate

The candidate uses an immutable `boringcache/one` release in `sccache` proxy
mode:

1. Build the base commit with an empty, run-scoped remote compiler cache.
2. Preserve Cargo registry state, but do not archive `target/`. This pinned
   Deno pair has no Cargo git dependencies, so the candidate does not configure
   an entry for a path Cargo never creates.
3. On a fresh runner, restore the same run-scoped cache with
   `trust-policy=restore`.
4. Build the head commit and capture `sccache --show-stats`.

Both strategies use Rust 1.95.0, Deno's `v2.x` snapshot-minifier runtime, and
Deno's Linux sysroot, LLVM 22, linker-plugin LTO, ThinLTO cache flags, release
packages, binaries, and `denort_desktop` build.

## Run it

The repository needs these Actions secrets:

- `BORINGCACHE_RESTORE_TOKEN`
- `BORINGCACHE_SAVE_TOKEN`

Run **Deno Rust cache proof** from the Actions tab. The optional `cli_version`
input can pin a canary CLI release. The two strategies run in parallel and the
final job publishes one comparison table and JSON artifact.

## Interpreting the result

The rolling row is the decision row. A useful result should have all three:

- lower restore-plus-build time than the Actions cache baseline
- a high Rust compiler-cache hit rate for the unchanged graph
- materially less stored data than the base Cargo plus target archives

If the rolling build is slower, the report says so directly. Before proposing
a migration, repeat the run and add macOS only after Linux shows a stable win.

## Local checks

The full build is intentionally GitHub-only because it modifies an ephemeral
Ubuntu runner to match Deno's sysroot. The benchmark harness can be checked
locally with:

```console
python3 -m unittest discover -s test -v
shellcheck scripts/*.sh
actionlint .github/workflows/*.yml
```
