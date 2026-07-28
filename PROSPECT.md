# Deno prospect review

Assessment date: 2026-07-28

## Recommendation

Deno is a strong account but not a current BoringCache performance prospect.
Do not pitch a Rust-cache migration from this evidence. Four tested sccache
shapes lost on rolling restore plus build, including the release ThinLTO hybrid,
the ordinary Linux debug lane, and no-cold controls that restored the same full
target state before enabling sccache.

The archive backend itself restored the promoted target state correctly and
faster than Actions, but that signal is not enough for outreach because the
complete build remained slower. Do not lead with Docker either: the repository
has a development-container Dockerfile, but no Docker Buildx workflow or
meaningful image-build cache surface in its main CI.

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
| Remote Rust sccache alone | No | Release reached 98% hits but still lost; debug reached 96.6% and was 10m28s slower. |
| sccache + narrow ThinLTO archive | No | The 141.85 MB LTO entry restored in 8s, but the complete release path was 8m slower. |
| Full target + sccache | No first-migration win | Archive setup beat Actions by 29s release and 6s debug, but the complete paths lost by 5m10s and 2m20s. |
| Full-target archive only | Unproven transport control | Promoted archive components used 12.2% less storage release and 8.8% less debug; sccache must be disabled to isolate this signal. |
| Cargo/tool cache | Secondary | Dependency restore works, but Deno's expensive time is in build/link work. |
| Docker/BuildKit | Poor | No main CI image-build workflow was found. |

## Outreach

The most relevant technical contacts are
[`@bartlomieju`](https://github.com/bartlomieju), who has recently changed CI
runners, cache versions, and release-LTO capacity, and
[`@nathanwhit`](https://github.com/nathanwhit), who has recently changed startup
ordering and snapshot/link performance.

Do not send the earlier design-partner pitch. The follow-ups it proposed are
now complete and losing. Keep the contacts only for a future archive-only
transport control or a materially different product surface. Any future note
should lead with the public losing results and make no acceleration claim until
a paired rolling sample wins and repeats.
