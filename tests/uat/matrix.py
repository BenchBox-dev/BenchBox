"""Platform/benchmark matrix machinery for the UAT framework.

This is the Python port of the bash machinery in
`scripts/local_stress_test.sh`. It is deliberately a structural mirror so
that the parity test (`tests/uat/test_matrix.py::test_bash_parity`) can
assert that every key in the bash case statements has a matching entry
here, and vice versa.

Sequential platform execution discipline. Per UAT W3 line 222 (in
`_project/handoffs/results-explorer-uat-retrospective-20260502.md`),
parallel platforms contaminate timings. Callers must iterate platforms
sequentially; the framework's higher layers enforce this at config
load time. Do not add a `parallel=True` knob here.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Iterable

# Platform → "host:port" for TCP reachability probes. Mirrors
# `get_platform_port` in scripts/local_stress_test.sh.
PLATFORM_PORTS: dict[str, str] = {
    "lakesail": "localhost:50051",
    "singlestore": "localhost:13306",
    "questdb": "localhost:8812",
    "presto": "localhost:18081",
    "trino": "localhost:18080",
    "clickhouse-server": "localhost:9000",
    "starrocks": "localhost:19030",
    "cedardb": "localhost:5435",
    "databend": "localhost:8000",
    "doris": "localhost:19031",
    "influxdb": "localhost:8181",
    "pg-duckdb": "localhost:5432",
    "pg-mooncake": "localhost:5432",
    "timescaledb": "localhost:5432",
    "postgresql": "localhost:5432",
    "velox": "localhost:50051",
}

# Platform → list of `--platform-option` argv to append. Mirrors
# `get_platform_extra_opts` in scripts/local_stress_test.sh:164-173.
PLATFORM_EXTRA_OPTS: dict[str, list[str]] = {
    "questdb": ["--platform-option", "http_port=19000"],
    "starrocks": [
        "--platform-option",
        "port=19030",
        "--platform-option",
        "http_port=18040",
    ],
    "doris": [
        "--platform-option",
        "port=19031",
        "--platform-option",
        "http_port=18030",
        "--platform-option",
        "be_http_port=18040",
    ],
    "singlestore": [
        "--platform-option",
        "port=13306",
        "--platform-option",
        "password=benchbox",
    ],
    "velox": [
        "--platform-option",
        "deployment=remote",
        "--platform-option",
        "endpoint=sc://localhost:50051",
    ],
}

# Platform → local managed Docker credentials appended only when the caller is
# running a UAT-managed Docker stack. Keep this separate from
# PLATFORM_EXTRA_OPTS because that mapping is a parity mirror of
# scripts/local_stress_test.sh.
LOCAL_MANAGED_PLATFORM_EXTRA_OPTS: dict[str, list[str]] = {
    "pg-duckdb": ["--platform-option", "password=benchbox"],
    "pg-mooncake": ["--platform-option", "password=benchbox"],
    "timescaledb": ["--platform-option", "password=benchbox"],
    "postgresql": ["--platform-option", "password=benchbox"],
}

# Platform → extra benchbox CLI flags (not --platform-option). Mirrors
# `get_platform_cli_flags` in scripts/local_stress_test.sh:187-192.
# velox: Docker Desktop's 11.7 GB ceiling cannot fit 3xSF=1 TPC-H passes
# inside a Spark/Velox container; one warmup + one measurement run is
# sufficient for functional verification.
PLATFORM_CLI_FLAGS: dict[str, list[str]] = {
    "velox": ["--iterations", "1"],
}

# Platform → uv extra name (`uv run --extra X`). Mirrors
# `get_platform_uv_extra` in scripts/local_stress_test.sh:548-555.
PLATFORM_UV_EXTRA: dict[str, str] = {
    "clickhouse-local": "clickhouse-local",
    "lakesail": "lakesail",
    "singlestore": "singlestore",
    "influxdb": "influxdb",
}

# Platform groupings (mirrors lines 127-137 of the bash script).
# Consumed by both the UAT framework and the integration matrix test;
# align with both before changing.
LOCAL_SQL_PLATFORMS: tuple[str, ...] = ("duckdb", "sqlite", "datafusion")
FAST_NATIVE_PLATFORMS: tuple[str, ...] = tuple(platform for platform in LOCAL_SQL_PLATFORMS if platform != "sqlite") + (
    "clickhouse-local",
)
FAST_DOCKER_PLATFORMS: tuple[str, ...] = (
    "lakesail",
    "clickhouse-server",
    "cedardb",
    "starrocks",
)
SLOW_NATIVE_PLATFORMS: tuple[str, ...] = tuple(platform for platform in LOCAL_SQL_PLATFORMS if platform == "sqlite") + (
    "spark",
)
SLOW_DOCKER_PLATFORMS: tuple[str, ...] = (
    "postgresql",
    "presto",
    "trino",
    "databend",
    "doris",
    "influxdb",
    "pg-duckdb",
    "pg-mooncake",
    "timescaledb",
    "questdb",
    "singlestore",
    "velox",
)
DATAFRAME_PLATFORMS: tuple[str, ...] = (
    "polars-df",
    "pandas-df",
    "modin-df",
    "pyspark-df",
    "dask-df",
    "datafusion-df",
)

PLATFORM_GROUPS: dict[str, tuple[str, ...]] = {
    "fast": FAST_NATIVE_PLATFORMS + FAST_DOCKER_PLATFORMS,
    "slow": SLOW_NATIVE_PLATFORMS + SLOW_DOCKER_PLATFORMS,
    "sql": (FAST_NATIVE_PLATFORMS + FAST_DOCKER_PLATFORMS + SLOW_NATIVE_PLATFORMS + SLOW_DOCKER_PLATFORMS),
    "dataframe": DATAFRAME_PLATFORMS,
    "docker": FAST_DOCKER_PLATFORMS + SLOW_DOCKER_PLATFORMS,
    "docker-fast": FAST_DOCKER_PLATFORMS,
    "docker-slow": SLOW_DOCKER_PLATFORMS,
    "all": (
        FAST_NATIVE_PLATFORMS
        + FAST_DOCKER_PLATFORMS
        + SLOW_NATIVE_PLATFORMS
        + SLOW_DOCKER_PLATFORMS
        + DATAFRAME_PLATFORMS
    ),
}


def resolve_platforms(
    groups: Iterable[str] = (),
    include: Iterable[str] = (),
    exclude: Iterable[str] = (),
) -> list[str]:
    """Resolve a final platform list given group, include, and exclude filters.

    Order: groups expanded first (in the order given, deduplicated by first
    occurrence), then `include` appended, then `exclude` removed.
    """
    seen: set[str] = set()
    resolved: list[str] = []
    for group in groups:
        if group not in PLATFORM_GROUPS:
            raise ValueError(f"Unknown platform group {group!r}; valid: {sorted(PLATFORM_GROUPS)}")
        for platform in PLATFORM_GROUPS[group]:
            if platform not in seen:
                seen.add(platform)
                resolved.append(platform)
    for platform in include:
        if platform not in seen:
            seen.add(platform)
            resolved.append(platform)
    excluded = set(exclude)
    return [p for p in resolved if p not in excluded]


# ---------------------------------------------------------------------------
# TCP reachability with sentinel-file cache equivalent.
# ---------------------------------------------------------------------------

# Bash uses one sentinel file per platform under $TMPDIR; the Python port
# uses an in-process dict keyed by platform name. Same effect: probe once
# per platform per sweep, not once per cell.
_REACHABILITY_CACHE: dict[str, bool] = {}


def reset_reachability_cache() -> None:
    """Clear the per-platform reachability cache (test/sweep-restart hook)."""
    _REACHABILITY_CACHE.clear()


def tcp_probe(host: str, port: int, timeout_s: float = 2.0) -> bool:
    """Return True iff a TCP connection to (host, port) succeeds within timeout.

    Mirrors `tcp_probe` in scripts/local_stress_test.sh:201-210, which uses
    nc when available and falls back to bash /dev/tcp. The Python port uses
    socket.create_connection with the same 2-second default timeout.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except (OSError, ValueError):
        return False


def platform_is_reachable(platform: str) -> bool:
    """Return True iff `platform` has no port mapping or its port is open.

    Mirrors `platform_is_reachable` in scripts/local_stress_test.sh:213-227.
    Cached per platform name (matching the bash sentinel-file semantics).
    """
    if platform in _REACHABILITY_CACHE:
        return _REACHABILITY_CACHE[platform]
    addr = PLATFORM_PORTS.get(platform)
    if addr is None:
        # No probe configured → assume reachable (bash behaviour).
        _REACHABILITY_CACHE[platform] = True
        return True
    host, _, port_s = addr.partition(":")
    try:
        port = int(port_s)
    except ValueError:
        _REACHABILITY_CACHE[platform] = True
        return True
    reachable = tcp_probe(host, port)
    _REACHABILITY_CACHE[platform] = reachable
    return reachable


# ---------------------------------------------------------------------------
# Benchmark enumeration via the registry.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BenchmarkInfo:
    """Subset of registry metadata the framework consumes."""

    benchmark_id: str
    category: str
    default_scale: float
    min_scale: float | None
    scale_options: tuple[float, ...]
    supports_dataframe: bool
    surface: str = "public"


def load_benchmarks() -> dict[str, BenchmarkInfo]:
    """Read the benchmark registry directly (no eval, no shell-out).

    The bash script imports the same registry via
    `uv run --no-sync -- python -c '...'` (lines 232-263); the Python
    port imports it as a library. A registry rename surfaces as an
    ImportError here, not as a silent skip.
    """
    from benchbox.core.benchmark_registry import BENCHMARK_METADATA

    out: dict[str, BenchmarkInfo] = {}
    for bid, meta in BENCHMARK_METADATA.items():
        out[bid] = BenchmarkInfo(
            benchmark_id=bid,
            category=meta.get("category", ""),
            surface=str(meta.get("surface", "public")),
            default_scale=float(meta.get("default_scale", 1.0)),
            min_scale=(float(meta["min_scale"]) if meta.get("min_scale") is not None else None),
            scale_options=tuple(float(s) for s in meta.get("scale_options", ())),
            supports_dataframe=bool(meta.get("supports_dataframe", True)),
        )
    return out


CATEGORY_GROUPS: dict[str, tuple[str, ...]] = {
    "tpc": ("TPC",),
    "primitives": ("Primitives",),
    "industry": ("Industry",),
    "academic": ("Academic",),
    "timeseries": ("Time Series",),
    "realworld": ("Real World",),
    "aiml": ("AI/ML",),
    "experimental": ("Experimental",),
    "all": (
        "TPC",
        "Primitives",
        "Industry",
        "Academic",
        "Time Series",
        "Real World",
        "AI/ML",
        "Experimental",
    ),
}


def resolve_benchmarks(
    groups: Iterable[str] = (),
    include: Iterable[str] = (),
    exclude: Iterable[str] = (),
    benchmarks: dict[str, BenchmarkInfo] | None = None,
) -> list[str]:
    """Resolve a final benchmark list given group, include, and exclude filters."""
    if benchmarks is None:
        benchmarks = load_benchmarks()
    seen: set[str] = set()
    resolved: list[str] = []
    for group in groups:
        if group not in CATEGORY_GROUPS:
            raise ValueError(f"Unknown benchmark group {group!r}; valid: {sorted(CATEGORY_GROUPS)}")
        target_categories = set(CATEGORY_GROUPS[group])
        for bid, info in benchmarks.items():
            if info.surface == "public" and info.category in target_categories and bid not in seen:
                seen.add(bid)
                resolved.append(bid)
    for bid in include:
        if bid in benchmarks and bid not in seen:
            seen.add(bid)
            resolved.append(bid)
    excluded = set(exclude)
    return [b for b in resolved if b not in excluded]


def smoke_scale_for(benchmark_id: str, info: BenchmarkInfo | None = None) -> float:
    """Return the per-benchmark smoke-test scale.

    Mirrors the inline Python in scripts/local_stress_test.sh:240-245:
    `min_scale` if set; `default_scale` otherwise. TPC-DS is forced to
    0.01 because the registry default is 1.0 for methodology reasons but
    the local smoke suite intentionally exercises patched subscale
    support.
    """
    if info is None:
        info = load_benchmarks()[benchmark_id]
    if benchmark_id == "tpcds":
        return 0.01
    if info.min_scale is not None:
        return info.min_scale
    return info.default_scale


def filter_scales_by_registry(
    benchmark_id: str,
    requested_scales: Iterable[float],
    info: BenchmarkInfo | None = None,
) -> list[float]:
    """Drop requested scales that fall outside the registry's scale_options.

    Fix forward from bash, per the parent TODO's W2 note: the bash script
    honours `min_scale` via the smoke-scale lookup but does not enforce
    the upper bound on a `--scale` override. This Python port enforces
    both bounds.

    A requested scale is kept when it appears in `scale_options` OR
    `scale_options` is empty (bench has no declared options). The result
    preserves request order.
    """
    if info is None:
        info = load_benchmarks()[benchmark_id]
    if not info.scale_options:
        # No declared options → cannot enforce bounds; trust the request.
        return list(requested_scales)
    allowed = set(info.scale_options)
    return [s for s in requested_scales if s in allowed]


# ---------------------------------------------------------------------------
# Command-fragment helpers.
# ---------------------------------------------------------------------------


def uv_run_argv(platform: str) -> list[str]:
    """Return the `uv run ...` prefix for a given platform.

    Platforms with a registered uv extra use `uv run --extra X --`;
    others use `uv run --no-sync --` to avoid per-invocation sync
    overhead. Matches scripts/local_stress_test.sh:449-452.
    """
    extra = PLATFORM_UV_EXTRA.get(platform)
    if extra is not None:
        return ["uv", "run", "--extra", extra, "--"]
    return ["uv", "run", "--no-sync", "--"]


def benchbox_run_argv(
    platform: str,
    benchmark: str,
    scale: float,
    *,
    phases: str = "load,power",
    compression: str | None = None,
    extra_args: Iterable[str] = (),
    local_managed_platform: bool = False,
) -> list[str]:
    """Build the full `uv run -- benchbox run ...` argv for a single cell.

    Combines uv extras, platform `--platform-option` blocks, platform CLI
    flags, and any caller-provided extra argv. The shape mirrors
    scripts/local_stress_test.sh:453-464 exactly.
    """
    argv = uv_run_argv(platform)
    argv += [
        "benchbox",
        "run",
        "--platform",
        platform,
        "--benchmark",
        benchmark,
        "--scale",
        str(scale),
        "--non-interactive",
        "--quiet",
        "--phases",
        phases,
    ]
    if compression is not None:
        argv += ["--compression", compression]
    argv += PLATFORM_CLI_FLAGS.get(platform, [])
    argv += PLATFORM_EXTRA_OPTS.get(platform, [])
    if local_managed_platform:
        argv += LOCAL_MANAGED_PLATFORM_EXTRA_OPTS.get(platform, [])
    argv += list(extra_args)
    return argv
