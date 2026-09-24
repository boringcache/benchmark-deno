# BoringCache Deno benchmark

This repository contains the BoringCache benchmark for Deno.

Benchmark workflows are in [`.github/workflows/`](.github/workflows/), with configuration in [`.boringcache.toml`](.boringcache.toml).

The [RunsOn cache comparison](.github/workflows/deno-runs-on-cache.yml) runs the same Deno release Cargo commands on fresh 16 vCPU, 64 GiB Flex runners in `us-east-1`. RunsOn Magic Cache and BoringCache both cache the Cargo registry, Git dependencies, and target directory. Each provider builds the pinned base revision cold, rebuilds it on a fresh runner, then builds its adjacent revision on a third runner. Every phase writes a new cache snapshot and checks the release artifacts. Compare total cache and build time; the setup and build columns split work differently for the two providers. Inspect the Magic Cache logs for fallback warnings before using the results.

The [target plus sccache comparison](.github/workflows/deno-runs-on-sccache.yml) repeats those phases with the same source and two Cargo commands. BoringCache uses its Cargo target and remote sccache adapters. Magic Cache archives the target and a local sccache directory after each build. The cache snapshots have different storage formats, so compare the completed build and cache path as a whole.

Run the [connection workflow](.github/workflows/connect-runs-on-s3.yml) once and approve the repository binding to `boringcache/benchmark-runs-on-s3-clean` before dispatching the comparison.
