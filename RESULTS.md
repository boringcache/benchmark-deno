# Deno Rust cache proof results

Run date: 2026-07-27

Proof run: [GitHub Actions run 30309154588](https://github.com/boringcache/benchmark-deno/actions/runs/30309154588)

Pinned pair: `0c965f5e` -> `c3ea533f` (one Rust file and one TypeScript file changed)

Product cohort: BoringCache CLI `v1.14.0` and `boringcache/one@6b7033721b37075b2138fd0c769bf088e0836ce6`

## Decision result

| Strategy | Restore/setup | Build | End-to-end | Seed storage | Rust cache result |
|---|---:|---:|---:|---:|---:|
| GitHub Actions Cargo + `target/` archives | 65s | 1,747s | 1,812s | 2.77 GiB | n/a |
| BoringCache Cargo registry + remote sccache | 16s | 2,253s | 2,269s | 2.07 GiB | 2,957 hits / 59 misses (98%) |

BoringCache stored 749,640,398 fewer bytes, a 25.2% reduction, but was 457
seconds (25.2%) slower on the rolling restore-plus-build path. This result does
not support replacing Deno's release `target/` archive with sccache alone.

The useful technical result is the combination of a 98% Rust cache hit rate
and a slower overall build. Deno's release surface is dominated after
compilation by ThinLTO, linking, and snapshot work. Restoring `target/` retains
that state; compiler-object caching does not.

## Release hybrid follow-up

Run date: 2026-07-28

Proof run: [GitHub Actions run 30333408848](https://github.com/boringcache/benchmark-deno/actions/runs/30333408848)

Benchmark commit: `4a364a9edfb799e214c6bc4f03baaeaaff6265fb`

This follow-up added a run-scoped archive of
`target/release/lto-cache` to the BoringCache Cargo + sccache lane. Both
rolling jobs ran on fresh hosted runners.

| Strategy | Restore/setup | Build | End-to-end | Seed storage | Rust cache result |
|---|---:|---:|---:|---:|---:|
| GitHub Actions Cargo + `target/` archives | 83s | 1,470s | 1,553s | 2.77 GiB | n/a |
| BoringCache Cargo + sccache + ThinLTO archive | 15s | 2,018s | 2,033s | 2.20 GiB | 2,957 hits / 59 misses (98.04%) |

BoringCache stored 607,739,750 fewer bytes, a 20.5% reduction, but was 480
seconds (30.9%) slower end to end. This is not a migration win.

The ThinLTO entry was healthy and small: 739.84 MB logical data compressed to
141.85 MB, saved in 5.5 seconds, and restored in 8.0 seconds. The rolling build
verified the directory was non-empty before compiling. BoringCache telemetry
reported zero backend errors, and sccache reads averaged 3 ms.

Preserving this narrow linker cache therefore does not recover the advantage
of the full target archive. The remaining gap is in Cargo fingerprints,
build-script and proc-macro outputs, already-linked artifacts, final binaries,
and other build-graph state elsewhere under `target/`.

## Linux debug follow-up

Run date: 2026-07-28

Proof run: [GitHub Actions run 30333410651](https://github.com/boringcache/benchmark-deno/actions/runs/30333410651)

Benchmark commit: `4a364a9edfb799e214c6bc4f03baaeaaff6265fb`

The debug proof used the same pinned pair and product cohort as the release
proof. Both rolling jobs ran on fresh hosted runners.

| Strategy | Restore/setup | Build | End-to-end | Seed storage | Rust cache result |
|---|---:|---:|---:|---:|---:|
| GitHub Actions Cargo + `target/` archives | 45s | 356s | 401s | 1.71 GiB | n/a |
| BoringCache Cargo registry + remote sccache | 12s | 1,017s | 1,029s | 1.19 GiB | 1,538 hits / 54 misses (96.6%) |

BoringCache stored 556,443,808 fewer bytes, a 30.3% reduction, but was 628
seconds (156.6%) slower end to end. This is not a migration win.

The compiler cache itself was hot across Rust, C/C++, and assembler requests,
and service-side telemetry reported zero backend errors. The restore-only
sccache process reported five cache errors and 54 rejected writes for the 54
misses, as expected for a fail-closed read-only rolling lane. Those misses do
not explain the 10-minute gap.

The important result is that Deno's Linux debug command still inherits its
sysroot linker-plugin ThinLTO flags and performs local link, snapshot, and
build-graph work. The Actions lane restores all of `target/`; the sccache lane
does not restore that state. A high compiler-request hit rate therefore does
not translate into a faster complete Deno build on this surface either.

## Full-target plus sccache migration control

Run date: 2026-07-28

Proof runs:

- [Release run 30339284716](https://github.com/boringcache/benchmark-deno/actions/runs/30339284716)
- [Debug run 30339284781](https://github.com/boringcache/benchmark-deno/actions/runs/30339284781)

Benchmark commit: `a3c9118ca6f0bc166c5efbe2f6c0bb02a211b376`

These controls did not repeat either cold build. Each promotion job restored
the exact run-scoped Actions Cargo and full-target archives from the completed
proof, published their actual contents to BoringCache, and recorded zero build
seconds. The rolling job then restored those archives plus the source proof's
sccache tag on a fresh runner and applied Deno's mtime action.

| Profile | Strategy | Restore/setup | Build | End-to-end | Stored data | Rust cache result |
|---|---|---:|---:|---:|---:|---:|
| Release | Actions Cargo + `target/` | 83s | 1,470s | 1,553s | 2.77 GiB | n/a |
| Release | BoringCache same paths + sccache | 54s | 1,809s | 1,863s | 4.24 GiB | 907 hits / 16 misses (98.27%) |
| Debug | Actions Cargo + `target/` | 45s | 356s | 401s | 1.71 GiB | n/a |
| Debug | BoringCache same paths + sccache | 39s | 502s | 541s | 2.51 GiB | 477 hits / 7 misses (98.55%) |

The BoringCache release control was 310 seconds (20.0%) slower; the debug
control was 140 seconds (34.9%) slower. Neither supports migration.

Target restoration itself worked and was faster. The release target archive
restored 2.28 GiB in 42.5 seconds; all archive setup completed 29 seconds
faster than Actions. Debug restored its 1.42 GiB target archive in 30 seconds;
all archive setup completed six seconds faster. Service telemetry reported
zero backend errors for both runs. Local extraction was the only archive-side
watch item.

The BoringCache archive components alone also stored less: 2,605,418,417 bytes
for release, 12.2% below Actions, and 1,677,512,969 bytes for debug, 8.8% below
Actions. Adding the source sccache CAS raised total storage 53.4% and 46.3%,
respectively.

This no-cold control has one deliberate migration constraint: its promoted
target tree was originally built without `RUSTC_WRAPPER`, then consumed with
sccache enabled. The hundreds of compiler requests despite full-target reuse
are consistent with wrapper/fingerprint churn, although the available Cargo
output does not prove that cause. The result is valid for the first migrated
rolling build, but it is not a steady-state sample from a target tree seeded
under sccache.

## Storage correction

The comparison artifact generated by this run records zero bytes for the
Actions seed because its branch predated the strict storage-measurement fix
already present on `main`.

The two saved entries remain visible through GitHub's cache API and total
2,969,113,947 bytes:

- target archive: 2,815,031,100 bytes
- Cargo archive: 154,082,847 bytes

The helper now performs client-side prefix matching, accepts either token name,
and fails the workflow rather than publishing a zero measurement. The exact
cache API rows for this run return the total above.

## Decision

All requested sccache shapes lost: release sccache alone, release sccache plus
the narrow ThinLTO archive, debug sccache alone, and the first-migration
full-target plus sccache controls. Deno is not a current sccache migration
prospect.

If this account is revisited without another cold build, the only useful
remaining control is BoringCache archive mode over the promoted Cargo and full
target entries with sccache disabled. That would isolate archive transport from
wrapper compatibility. Do not make a performance claim until such a paired
rolling sample wins and repeats.
