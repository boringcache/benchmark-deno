# BoringCache Deno benchmark

This repository contains the BoringCache benchmark for Deno's exact Linux
release Cargo workload.

The CLI plans are the product contract:

- [`.boringcache.toml`](.boringcache.toml) owns the persistent rolling chain.
- [`plans/`](plans/) owns the release proof's cold, sccache-only, and combined
  target+sccache lanes.
- GitHub Actions activates a committed plan in the clean upstream checkout and
  runs the CLI there; it does not rewrite cache tags, layer membership, or
  Cargo commands.

The layer proof seeds one adjacent source pair, then compares compiler caching
without a transported target against compiler caching with Cargo's target
snapshot. Each lane retains the Action receipt with native sccache statistics,
target-restore state, and command timing.
