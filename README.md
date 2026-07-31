# benchmark-deno

Reproducible Linux x86 release and debug build proofs for
[`denoland/deno`](https://github.com/denoland/deno). It compares Deno's current
GitHub Actions `target/` archive strategy with deliberately separate
BoringCache candidates:

- remote sccache plus only the capped release ThinLTO archive
- remote sccache alone for Deno's ordinary Linux debug build
- the same promoted Cargo and full-`target/` archive contents plus remote
  sccache, as a migration control that does not repeat the cold build
- a same-seed cohort that combines persistent `target/` with sccache on both
  sides and changes only archived-local versus eagerly warmed remote storage

Stable proof runs pin `boringcache/one` `v1.15.0` by immutable commit and keep
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
3. When BoringCache restores the existing full target state as well as
   sccache, does the complete migration beat the Actions restore-plus-build
   path?
4. If a promoted target was seeded without `RUSTC_WRAPPER`, how much rolling
   work comes from enabling sccache after restore rather than archive transport?
5. When one compiler environment seeds both products, how does an Actions
   archive containing local sccache plus `target/` compare with BoringCache's
   explicit `full-target` profile plus remote sccache adapter?

The proof reports the parts needed to answer that honestly:

- cache restore or proxy setup time
- release build time
- restore-plus-build time
- base cache storage
- native `sccache` hits, misses, and non-cacheable compilations
- Deno mtime-cache counters, exact restored source mtimes, and Cargo's own
  fresh-versus-rebuilt target decisions for the full-target control

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

The two compiler-cache experiments use an immutable `boringcache/one` release
in `sccache` proxy mode:

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

The full-target control does not run another cold build. It restores the exact
run-scoped Actions Cargo and target archives from the completed proof, promotes
their actual contents into BoringCache archive entries, and reuses that proof's
run-scoped sccache tag. Its fresh rolling runner restores all three surfaces,
applies Deno's mtime action, and builds the same pinned head commit. The
promoted base artifact records zero build seconds so it cannot be mistaken for
a second cold sample. The rolling gate fails unless Deno reports restored,
non-invalid timestamps, those timestamps match the filesystem exactly, and
Cargo's JSON messages contain both accepted-fresh and rebuilt targets.

The focused **Deno release target identity control** restores that same
promoted BoringCache target archive but deliberately leaves `RUSTC_WRAPPER`
unset. It records the same exact-mtime and Cargo freshness evidence and compares
against the source Actions rolling artifact. This isolates archive transport
from adapter-environment and native-wrapper overhead before spending another
cold build on a wrapper-consistent target seed.

The **Deno release sccache plus target cohort** is the paired follow-up. One
base build uses sccache's documented disk-plus-WebDAV chain so the same compiler
outputs populate both BoringCache and a local disk cache, then snapshots the
same Cargo and target state into both archive products. The seed and both
rolling jobs run Deno's own mtime action, so unchanged source identities line
up with the restored target fingerprints. Deno's production target exclusions
are applied once to the shared tree before either product saves it. Fresh
rolling jobs restore the same Cargo registry, Cargo binaries, and normalized
target paths; only sccache's local-disk versus remote representation differs.
They keep
`RUSTC_WRAPPER`, `CC`, `CXX`, and incremental settings identical while comparing
BoringCache's eagerly warmed remote sccache with the Actions-archived local
sccache. The report refuses to compare different runner image releases, CPU
models, core counts, memory classes, or compiler environments, and includes
exact target freshness plus native hit/miss counts.

The **Deno Cargo archive chunks canary** is the first-class product proof. An
exact immutable CLI runs the pinned base and adjacent head entirely through
`boringcache cargo`; the CLI owns target transport, source freshness, Cargo
registry and Git state, and the sccache proxy. One local base target is
published as both the ordinary GNU-tar archive and `archive-chunks-v1`, then
fresh rolling runners consume each representation through the same command.
Both representations and rolling consumers share the current run's compiler
cache, published by that same base invocation; no historical cache generation
is accepted. The workflow only scopes run-specific tags and verifies the signed
result, Cargo JSON evidence, exact source mtimes, and native sccache counters.

This canary does not run Deno's mtime Action or manually restore/save any Cargo
surface. Its two Deno Cargo phases use the CLI's explicit lifecycle flags:
restore happens on the first phase, save happens on the final phase, and both
phases share the same target and sccache product plan.

## Run it

The repository needs these Actions secrets:

- `BORINGCACHE_RESTORE_TOKEN`
- `BORINGCACHE_SAVE_TOKEN`

Run **Deno release hybrid cache proof**, **Deno Linux debug cache proof**,
either full-target proof, **Deno release sccache plus target cohort**, or
**Deno Cargo archive chunks canary** from the Actions tab. The optional
`cli_version` input can pin a canary CLI release. Full-target proofs also
require the completed source proof run ID whose seed and Actions result should
be reused. Each proof publishes one comparison table and JSON artifact.

The target identity control additionally takes the completed full-target run
that owns the promoted archive and the source run that owns the paired Actions
baseline. It never publishes or mutates cache state.

The sccache-plus-target cohort takes only the CLI release. It creates run-scoped
seed state for both products from one build and never falls back to historical
target or sccache generations.

## Interpreting the result

The rolling row is the decision row. A smaller-cache experiment should have
all three:

- lower restore-plus-build time than the Actions cache baseline
- a high Rust compiler-cache hit rate for the unchanged graph
- materially less stored data than the base Cargo plus target archives

The release-hybrid result is not a pure remote-sccache claim; its artifact names
the ThinLTO archive explicitly. The full-target control is intentionally a
superset of the baseline and may store more data because it adds sccache; judge
it first on restore-plus-build time. If any rolling build is slower, the report
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
