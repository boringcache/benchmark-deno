# Deno prospect review

Assessment date: 2026-07-27

## Recommendation

Deno is a strong account and a weak target for a generic "replace your Rust
cache" pitch. Market BoringCache as a design-partner pilot for one narrow CI
lane, not as a proven full-release acceleration.

The best next wedge is either a hybrid sccache + ThinLTO cache or the Linux
debug build. Do not lead with Docker: the repository has a development-container
Dockerfile, but no Docker Buildx workflow or meaningful image-build cache
surface in its main CI.

## Why the account matters

- [`denoland/deno`](https://github.com/denoland/deno) is primarily Rust, had
  107,830 stars and 6,233 forks at review time, and was receiving commits on the
  day of the assessment.
- Its generated [CI definition](https://github.com/denoland/deno/blob/094e47196e7f8a747c53c6612f9047e92e4c02b7/.github/workflows/ci.ts)
  spans Linux, macOS, Windows, x86_64, and ARM. A sampled successful pull-request
  run expanded to roughly 140 build and test jobs.
- Deno currently restores Cargo home and the full Cargo `target/` tree through
  GitHub Actions cache, then repairs mtimes with its own action. No remote
  sccache service is configured in the workflow.
- In the latest 98 completed pull-request CI runs reviewed, 63 succeeded, 13
  failed, 10 were cancelled, and 12 required approval; median elapsed time was
  49 minutes. The latest 29 completed `main` CI runs contained 24 failures, four
  cancellations, and one success, with a 118-minute median. Recent failures
  were concentrated in test lanes such as macOS Node compatibility, so caching
  is not a blanket reliability fix.
- A representative [successful PR run](https://github.com/denoland/deno/actions/runs/30299270057)
  spent about 52 minutes in `build release linux-x86_64`. It restored a 2.80 GB
  target archive, then performed release build/link phases of about 21m40s,
  11m39s, and a 15m10s startup-order relink.

## Product fit

| BoringCache surface | Fit | Evidence |
|---|---|---|
| Remote Rust sccache alone | Not a release migration yet | The proof reached 98% hits but finished 8m26s slower than target restoration. |
| sccache + narrow ThinLTO archive | Best release follow-up | It preserves compiler reuse while targeting the non-cacheable link tail. |
| Linux debug Rust cache | Best high-frequency wedge | Ordinary PRs run it, and it has less ThinLTO/relink work than release. |
| Cargo/tool cache | Secondary | Dependency restore works, but Deno's expensive time is in build/link work. |
| Docker/BuildKit | Poor | No main CI image-build workflow was found. |

## Outreach

The most relevant technical contacts are
[`@bartlomieju`](https://github.com/bartlomieju), who has recently changed CI
runners, cache versions, and release-LTO capacity, and
[`@nathanwhit`](https://github.com/nathanwhit), who has recently changed startup
ordering and snapshot/link performance.

Suggested message:

> We reproduced Deno's Linux release build on an adjacent commit and tested a
> run-scoped remote Rust cache against the existing target archive. The Rust
> graph reused extremely well: 2,957 hits, 59 misses, and zero cache errors.
> But the full result was 8m26s slower because ThinLTO and the release relink,
> not Rust compilation, dominate the tail.
>
> We do not want to sell you a misleading sccache replacement. We would like to
> test one focused follow-up at our cost: either preserve only the capped
> ThinLTO cache alongside remote compiler artifacts, or benchmark the everyday
> Linux debug lane. The harness, pinned commits, and losing result are public.

That is a credible engineering-led opening. Gate any stronger performance or
migration claim on a repeated hybrid/debug win.
