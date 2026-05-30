"""Platform/benchmark matrix machinery for the UAT framework.

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

from benchbox.core.benchmark_registry import CATEGORY_ORDER
from benchbox.core.platform_registry import PlatformRegistry

# Platform -> "host:port" for TCP reachability probes.
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

# Platform -> list of `--platform-option` argv to append.
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
# PLATFORM_EXTRA_OPTS because that mapping applies even when UAT probes
# externally managed local platforms.
LOCAL_MANAGED_PLATFORM_EXTRA_OPTS: dict[str, list[str]] = {
    "pg-duckdb": ["--platform-option", "password=benchbox"],
    "pg-mooncake": ["--platform-option", "password=benchbox"],
    "timescaledb": ["--platform-option", "password=benchbox"],
    "postgresql": ["--platform-option", "password=benchbox"],
}

# Platform -> extra benchbox CLI flags (not --platform-option).
# velox: Docker Desktop's 11.7 GB ceiling cannot fit 3xSF=1 TPC-H passes
# inside a Spark/Velox container; one warmup + one measurement run is
# sufficient for functional verification.
PLATFORM_CLI_FLAGS: dict[str, list[str]] = {
    "velox": ["--iterations", "1"],
}

# Platform -> uv extra name (`uv run --extra X`).
PLATFORM_UV_EXTRA: dict[str, str] = {
    "clickhouse-local": "clickhouse-local",
    "lakesail": "lakesail",
    "singlestore": "singlestore",
    "influxdb": "influxdb",
}

# Platform groupings.
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
UAT_DATAFRAME_PLATFORM_BASES: tuple[str, ...] = (
    "polars",
    "pandas",
    "modin",
    "pyspark",
    "dask",
    "datafusion",
)

SQL_PLATFORMS: tuple[str, ...] = ()
DOCKER_PLATFORMS: tuple[str, ...] = ()
DATAFRAME_PLATFORMS: tuple[str, ...] = ()


def _registry_platform_subset(
    group_name: str,
    candidates: tuple[str, ...],
    registry_platforms: Iterable[str],
) -> tuple[str, ...]:
    registry_set = set(registry_platforms)
    missing = tuple(platform for platform in candidates if platform not in registry_set)
    if missing:
        raise ValueError(f"UAT {group_name} platforms missing from platform registry: {missing}")
    return candidates


def _dataframe_selector_platforms() -> tuple[str, ...]:
    registry_platforms = set(PlatformRegistry.get_dataframe_platforms())
    missing = tuple(platform for platform in UAT_DATAFRAME_PLATFORM_BASES if platform not in registry_platforms)
    if missing:
        raise ValueError(f"UAT dataframe platforms missing from platform registry: {missing}")
    return tuple(f"{platform}-df" for platform in UAT_DATAFRAME_PLATFORM_BASES)


SQL_PLATFORMS = _registry_platform_subset(
    "sql",
    FAST_NATIVE_PLATFORMS + FAST_DOCKER_PLATFORMS + SLOW_NATIVE_PLATFORMS + SLOW_DOCKER_PLATFORMS,
    PlatformRegistry.get_sql_platforms(),
)
DOCKER_PLATFORMS = _registry_platform_subset(
    "docker",
    FAST_DOCKER_PLATFORMS + SLOW_DOCKER_PLATFORMS,
    PlatformRegistry.get_self_hosted_platforms(),
)
DATAFRAME_PLATFORMS = _dataframe_selector_platforms()

PLATFORM_GROUPS: dict[str, tuple[str, ...]] = {
    "fast": FAST_NATIVE_PLATFORMS + FAST_DOCKER_PLATFORMS,
    "slow": SLOW_NATIVE_PLATFORMS + SLOW_DOCKER_PLATFORMS,
    "sql": SQL_PLATFORMS,
    "dataframe": DATAFRAME_PLATFORMS,
    "docker": DOCKER_PLATFORMS,
    "docker-fast": FAST_DOCKER_PLATFORMS,
    "docker-slow": SLOW_DOCKER_PLATFORMS,
    "all": SQL_PLATFORMS + DATAFRAME_PLATFORMS,
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

# Bash used one sentinel file per platform under $TMPDIR; the Python port
# uses an in-process dict keyed by platform name. Same effect: probe once
# per platform for this process, not once per cell. Runtime code clears the
# cache only after UAT-managed platform lifecycle changes that can make a
# prior reachability answer stale.
_REACHABILITY_CACHE: dict[str, bool] = {}


def invalidate_reachability_cache_after_lifecycle_change() -> None:
    """Clear cached reachability after UAT starts or mutates a local platform."""
    _REACHABILITY_CACHE.clear()


def tcp_probe(host: str, port: int, timeout_s: float = 2.0) -> bool:
    """Return True iff a TCP connection to (host, port) succeeds within timeout."""
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except (OSError, ValueError):
        return False


def platform_is_reachable(platform: str) -> bool:
    """Return True iff `platform` has no port mapping or its port is open."""
    if platform in _REACHABILITY_CACHE:
        return _REACHABILITY_CACHE[platform]
    addr = PLATFORM_PORTS.get(platform)
    if addr is None:
        # No probe configured -> assume reachable.
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
    """Read the benchmark registry directly."""
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


def category_group_slug(category: str) -> str:
    return "".join(ch for ch in category.lower() if ch.isalnum())


CATEGORY_GROUPS: dict[str, tuple[str, ...]] = {
    category_group_slug(category): (category,) for category in CATEGORY_ORDER
}
CATEGORY_GROUPS["all"] = tuple(CATEGORY_ORDER)


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

    Use `min_scale` when set and `default_scale` otherwise. TPC-DS is
    forced to 0.01 because the registry default is 1.0 for methodology
    reasons but the local smoke suite intentionally exercises patched
    subscale support.
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
    overhead.
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
    flags, and any caller-provided extra argv.
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
