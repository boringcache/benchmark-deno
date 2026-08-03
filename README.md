# benchmark-deno

Deno correctness and rolling-reuse proof for the first-class BoringCache Cargo
adapter.

The live benchmark has one BoringCache product boundary:

```console
boringcache cargo build --release --locked
```

The released CLI owns Cargo registry and Git dependency state, the typed Cargo
target snapshot, transported source freshness, native sccache, restore, native
evidence, and publication. The workflow owns the pinned source, Deno build
environment, timing, and verification.

## Workflows

`deno-cargo-product.yml` publishes the pinned base commit through
`boringcache cargo --write`, then consumes it at the adjacent head on a fresh
runner through `boringcache cargo --read-only`.

`deno-cargo-rolling-chain.yml` advances an existing signed Cargo target through
one adjacent commit. It verifies source freshness, Cargo artifact reuse,
sccache health, exactly one target publication, and target accumulation.

`deno-rust-cache-proof.yml` is the small dispatch surface for those two
workflows. Cargo product is the default.

Historical remote-sccache-only, hybrid, full-target, Actions/cache, mtime, and
transport-control experiments remain documented in `RESULTS.md`, `PROSPECT.md`,
Git, and GitHub Actions history. They are not live runner implementations.

## Tokens

CI uses split tokens:

- `BORINGCACHE_RESTORE_TOKEN` for restore and read-only proxy access;
- `BORINGCACHE_SAVE_TOKEN` for trusted publication.
