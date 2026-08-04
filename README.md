# BoringCache Deno benchmark

This repository contains the BoringCache benchmark for Deno.

Benchmark workflows are in [`.github/workflows/`](.github/workflows/), with configuration in [`.boringcache.toml`](.boringcache.toml).

The active profile mirrors Deno's generated `build release linux-x86_64` setup
and release compilation units. The immutable BoringCache One v1.16.8 Action is
the cache integration: its Cargo mode owns dependency, `target/`, source
freshness, and sccache lifecycle around the otherwise-upstream build. The job
preinstalls the Action's default sccache 0.16.0 because released Cargo mode
requires the native tool to be present before invoking the CLI lifecycle.
Deno's two release Cargo commands remain two commands; combining them changes
Cargo feature unification and would make the benchmark a different workload.

Each source update creates a fresh adjacent base/head cohort, so a release
recipe change cannot silently reuse an older target identity. The persistent
rolling lane remains available as a manually selected storage/correctness probe.
Every build first checks the pinned Deno checkout against the generated release
job and stops on recipe or Rust toolchain drift.
