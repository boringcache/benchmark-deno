#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import re
import shlex
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

BASE_RUSTFLAGS = [
    "-C linker-plugin-lto=true",
    "-C linker=clang-{llvm}",
    "-C link-arg=-fuse-ld=lld-{llvm}",
    "-C link-arg=-Wl,--icf=safe",
    "-C link-arg=-ldl",
    "-C link-arg=-Wl,--allow-shlib-undefined",
    "-C link-arg=-Wl,--thinlto-cache-dir=$(pwd)/target/release/lto-cache",
    "-C link-arg=-Wl,--thinlto-cache-policy,cache_size_bytes=700m",
    "-C link-arg=/tmp/memfd_create_shim.o",
    "-C link-arg=/tmp/glibc_math_shim.o",
    "-C link-arg=-Wl,--wrap=expf",
    "-C link-arg=-Wl,--wrap=powf",
    "-C link-arg=-Wl,--wrap=exp2f",
    "-C link-arg=-Wl,--wrap=log2f",
    "-C link-arg=-Wl,--wrap=logf",
    "--cfg tokio_unstable",
    "$RUSTFLAGS",
]


class RecipeMismatch(RuntimeError):
    pass


def load_phase_selector():
    path = ROOT / "scripts/select-deno-cargo-phase.py"
    spec = importlib.util.spec_from_file_location("select_deno_cargo_phase", path)
    if not spec or not spec.loader:
        raise RecipeMismatch(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_settings(path: Path) -> dict[str, str]:
    settings: dict[str, str] = {}
    for number, raw_line in enumerate(path.read_text().splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise RecipeMismatch(f"Invalid setting at {path}:{number}: {raw_line}")
        key, raw_value = line.split("=", 1)
        if not raw_value:
            settings[key] = ""
            continue
        values = shlex.split(raw_value)
        if len(values) != 1:
            raise RecipeMismatch(f"Expected one value for {key} at {path}:{number}")
        settings[key] = values[0]
    return settings


def extract_job(workflow: str, job_name: str) -> str:
    match = re.search(
        rf"^  {re.escape(job_name)}:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)",
        workflow,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise RecipeMismatch(f"Missing upstream job: {job_name}")
    return match.group("body")


def extract_step(job: str, step_name: str) -> str:
    match = re.search(
        rf"^      - name: {re.escape(step_name)}\n"
        rf"(?P<body>.*?)(?=^      - (?:name:|uses:)|\Z)",
        job,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise RecipeMismatch(f"Missing upstream step in Linux release job: {step_name}")
    return match.group("body")


def extract_rustflag_blocks(setup_step: str) -> list[list[str]]:
    blocks = re.findall(
        r"(?:RUSTFLAGS|RUSTDOCFLAGS)<<__1\n(?P<body>.*?)^\s*__1$",
        setup_step,
        re.MULTILINE | re.DOTALL,
    )
    return [
        [line.strip() for line in block.splitlines() if line.strip()]
        for block in blocks
    ]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RecipeMismatch(message)


def verify(upstream: Path) -> str:
    contract = read_settings(ROOT / "scripts/deno-release-recipe.env")
    benchmark_source = read_settings(ROOT / "benchmark-source.env")

    toolchain_path = upstream / "rust-toolchain.toml"
    workflow_path = upstream / ".github/workflows/ci.generated.yml"
    require(toolchain_path.is_file(), f"Missing {toolchain_path}")
    require(workflow_path.is_file(), f"Missing {workflow_path}")

    toolchain_text = toolchain_path.read_text()
    channel_match = re.search(r'^channel = "([^"]+)"$', toolchain_text, re.MULTILINE)
    components_match = re.search(
        r'^components = \[(?P<components>[^\]]*)\]$', toolchain_text, re.MULTILINE
    )
    require(channel_match is not None, "Missing channel in upstream/rust-toolchain.toml")
    require(
        components_match is not None,
        "Missing components in upstream/rust-toolchain.toml",
    )
    toolchain_channel = channel_match.group(1)
    toolchain_components = re.findall(r'"([^"]+)"', components_match.group("components"))
    require(
        toolchain_channel == benchmark_source["DENO_RUST_VERSION"],
        "DENO_RUST_VERSION no longer matches upstream/rust-toolchain.toml",
    )
    require(
        "rust-src" in toolchain_components,
        "Deno's pinned toolchain no longer includes rust-src",
    )

    job = extract_job(
        workflow_path.read_text(), contract["DENO_UPSTREAM_RELEASE_JOB"]
    )
    for variable, action in (
        ("DENO_CHECKOUT_ACTION", contract["DENO_CHECKOUT_ACTION"]),
        ("DENO_SETUP_ACTION", contract["DENO_SETUP_ACTION"]),
        ("DENO_TOOLCHAIN_ACTION", contract["DENO_TOOLCHAIN_ACTION"]),
    ):
        require(action in job, f"Deno's Linux release job changed {variable}")
    for setting in (
        "CARGO_TERM_COLOR: always",
        "RUST_BACKTRACE: full",
        "RUST_LIB_BACKTRACE: 0",
    ):
        require(setting in job, f"Deno's Linux release job changed {setting}")

    setup_step = extract_step(job, "Set up incremental LTO and sysroot build")
    frame_step = extract_step(job, "Configure frame-pointer panic traces")
    build_step = extract_step(job, "Build release")

    llvm = contract["DENO_LLVM_VERSION"]
    sysroot = contract["DENO_SYSROOT_RELEASE"]
    require(
        f"llvm-toolchain-noble-{llvm} main" in setup_step,
        f"Deno's Linux release job no longer uses LLVM {llvm}",
    )
    for package in ("clang", "lld", "clang-tools", "clang-format", "clang-tidy"):
        require(
            f"{package}-{llvm}" in setup_step,
            f"Deno's Linux release setup no longer installs {package}-{llvm}",
        )
    require(
        f"releases/download/{sysroot}/sysroot-" in setup_step,
        f"Deno's Linux release job no longer uses {sysroot}",
    )

    expected_base_flags = [flag.format(llvm=llvm) for flag in BASE_RUSTFLAGS]
    rustflag_blocks = extract_rustflag_blocks(setup_step)
    require(
        rustflag_blocks == [expected_base_flags, expected_base_flags],
        "Deno's sysroot RUSTFLAGS or RUSTDOCFLAGS changed; resync setup-deno-linux.sh",
    )

    frame_flags = contract["DENO_FRAME_POINTER_RUSTFLAGS"]
    require(
        'echo "RUSTC_BOOTSTRAP=1" >> "$GITHUB_ENV"' in frame_step,
        "Deno's Linux release job no longer enables RUSTC_BOOTSTRAP for build-std",
    )
    require(
        f'echo "$RUSTFLAGS {frame_flags}"' in frame_step,
        "Deno's Linux release frame-pointer RUSTFLAGS changed",
    )

    build_std = contract["DENO_BUILD_STD_ARG"]
    feature = contract["DENO_PANIC_TRACE_FEATURE"]
    expected_builds = [
        f"cargo build {build_std} --release --locked -p deno -p denort "
        f"-p test_server --bin deno --bin denort --bin test_server --features={feature}",
        f"cargo build {build_std} --release --locked -p denort_desktop",
    ]
    actual_builds = [
        line.strip()
        for line in build_step.splitlines()
        if line.strip().startswith("cargo build ")
    ]
    require(
        actual_builds == expected_builds,
        "Deno's generated Linux release build commands changed; resync "
        "deno-release-recipe.env and .boringcache.toml",
    )
    require(
        "DENO_SNAPSHOT_MINIFY_SOURCES: '1'" in build_step,
        "Deno's Linux release snapshot-minification setting changed",
    )

    local_setup = (ROOT / "scripts/setup-deno-linux.sh").read_text()
    local_frame_setup = (
        ROOT / "scripts/configure-deno-frame-pointers.sh"
    ).read_text()
    cargo_plan = (ROOT / ".boringcache.toml").read_text()
    local_workflows = "\n".join(
        (ROOT / relative_path).read_text()
        for relative_path in (
            ".github/workflows/deno-cargo-product.yml",
            ".github/workflows/deno-cargo-rolling-chain.yml",
        )
    )
    for action in (
        contract["DENO_CHECKOUT_ACTION"],
        contract["DENO_SETUP_ACTION"],
        contract["DENO_TOOLCHAIN_ACTION"],
    ):
        require(
            action in local_workflows,
            f"Benchmark workflows do not use Deno's pinned action: {action}",
        )
    for setting in (
        "CARGO_TERM_COLOR: always",
        "RUST_BACKTRACE: full",
        "RUST_LIB_BACKTRACE: 0",
    ):
        require(
            local_workflows.count(setting) == 2,
            f"Both benchmark workflows must preserve Deno's job env: {setting}",
        )
    for setting in (
        "DENO_LLVM_VERSION",
        "DENO_SYSROOT_RELEASE",
    ):
        require(setting in local_setup, f"setup-deno-linux.sh does not use {setting}")
    require(
        "DENO_FRAME_POINTER_RUSTFLAGS" in local_frame_setup,
        "configure-deno-frame-pointers.sh does not use DENO_FRAME_POINTER_RUSTFLAGS",
    )
    expected_local_flags = [
        flag.replace(f"clang-{llvm}", "clang-${llvm_version}")
        .replace(f"lld-{llvm}", "lld-${llvm_version}")
        for flag in expected_base_flags
    ]
    for flag in expected_local_flags:
        require(
            local_setup.count(f"  {flag}\n") == 2,
            f"setup-deno-linux.sh no longer mirrors Deno's RUSTFLAGS: {flag}",
        )
    for setting in (
        "CARGO_PROFILE_BENCH_INCREMENTAL=false",
        "CARGO_PROFILE_RELEASE_INCREMENTAL=false",
        "CC=/usr/bin/clang-${llvm_version}",
    ):
        require(setting in local_setup, f"setup-deno-linux.sh is missing {setting}")
    require(
        'echo "$RUSTFLAGS ${DENO_FRAME_POINTER_RUSTFLAGS}"' in local_frame_setup,
        "configure-deno-frame-pointers.sh no longer appends Deno's exact flags",
    )
    command_match = re.search(
        r"^command\s*=\s*\[(?P<body>.*?)^\]$",
        cargo_plan,
        re.MULTILINE | re.DOTALL,
    )
    require(command_match is not None, "Missing BoringCache Cargo command")
    actual_cargo_plan = re.findall(r'"([^"]*)"', command_match.group("body"))
    phase_selector = load_phase_selector()
    expected_cargo_plan = shlex.split(expected_builds[0])
    require(
        actual_cargo_plan == expected_cargo_plan,
        "The committed BoringCache Cargo plan no longer matches Deno's first "
        "Linux release command; resync .boringcache.toml",
    )
    require(
        phase_selector.cargo_command(contract, "primary") == expected_cargo_plan,
        "The primary Cargo phase selector no longer matches Deno's release job",
    )
    require(
        phase_selector.cargo_command(contract, "desktop")
        == shlex.split(expected_builds[1]),
        "The desktop Cargo phase selector no longer matches Deno's release job",
    )

    return benchmark_source["DENO_HEAD_SHA"]


def main() -> int:
    upstream = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "upstream"
    try:
        source_sha = verify(upstream.resolve())
    except (KeyError, RecipeMismatch) as error:
        print(f"Deno release recipe mismatch: {error}", file=sys.stderr)
        return 1

    print(f"Verified Deno Linux release recipe at {source_sha}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
