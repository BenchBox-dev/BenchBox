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
from tests.uat import docker_assets

# Connection facts (reachability host:port, platform-option ports/credentials)
# are owned by tests.uat.docker_assets and derived from the docker-compose
# `ports:` mappings rather than duplicated here. matrix consumes them via
# docker_assets.host_reachability_endpoint / platform_extra_opts /
# local_managed_platform_extra_opts so the two surfaces cannot drift and an env
# override (e.g. SINGLESTORE_HOST_PORT) flows through to the probe and the
# adapter `port=` option alike.

# Platform -> extra benchbox CLI flags (not --platform-option).
# velox: Docker Desktop's 11.7 GB ceiling cannot fit 3xSF=1 TPC-H passes
# inside a Spark/Velox container; one warmup + one measurement run is
# sufficient for functional verification.
PLATFORM_CLI_FLAGS: dict[str, list[str]] = {
    "velox": ["--iterations", "1"],
}

# Platform -> uv extra name (`uv run --extra X`).
# modin[ray] and databend-driver are NOT in the default dev dependency-group
# (pyproject.toml [dependency-groups] dev) -- only under [project.optional-
# dependencies] -- so a plain `uv sync` never installs them (see
# uat-operator-provisioning finding 1). "modin-df" is the matrix/CLI platform
# key (see UAT_DATAFRAME_PLATFORM_BASES); the pyproject extra is named
# "modin" (no -df suffix).
PLATFORM_UV_EXTRA: dict[str, str] = {
    "clickhouse-local": "clickhouse-local",
    "clickhouse-server": "clickhouse-server",
    "lakesail": "lakesail",
    "singlestore": "singlestore",
    "influxdb": "influxdb",
    "modin-df": "modin",
    "databend": "databend",
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
    "native-sql": FAST_NATIVE_PLATFORMS + SLOW_NATIVE_PLATFORMS,
    "sql": SQL_PLATFORMS,
    "dataframe": DATAFRAME_PLATFORMS,
    "docker": DOCKER_PLATFORMS,
    "docker-fast": FAST_DOCKER_PLATFORMS,
    "docker-slow": SLOW_DOCKER_PLATFORMS,
    "all": SQL_PLATFORMS + DATAFRAME_PLATFORMS,
}


def known_platform_ids() -> frozenset[str]:
    """Full registry-known platform ids UAT's `platforms.include` may name.

    Union of `PlatformRegistry.get_sql_platforms()` and
    `get_dataframe_platforms()`, plus the `-df` CLI alias suffix for every
    dataframe-capable platform (`benchbox.cli.platform.PLATFORM_ALIASES`
    maps e.g. `polars-df` -> `polars`; mirrored here by suffix rather than
    importing CLI code into the UAT framework). This is the same "true
    registry" boundary `missing_benchmarks_from_include` uses via
    `load_benchmarks()` -- broader than any single curated `PLATFORM_GROUPS`
    bucket, so a real (if UAT-out-of-scope, e.g. a cloud platform) registry
    id is never flagged, only a genuine typo/removed id.
    """
    sql = set(PlatformRegistry.get_sql_platforms())
    dataframe = set(PlatformRegistry.get_dataframe_platforms())
    # Guard against ids that already carry the suffix (e.g. `databricks-df`
    # is registered under both capabilities) so we don't mint spurious
    # `databricks-df-df` entries.
    df_aliases = {f"{platform}-df" for platform in dataframe if not platform.endswith("-df")}
    return frozenset(sql | dataframe | df_aliases)


def missing_platforms_from_include(
    include: Iterable[str],
    known: Iterable[str] | None = None,
) -> list[str]:
    """Return `include` entries naming a platform absent from the registry.

    `resolve_platforms` silently drops `include` entries not in
    `known_platform_ids()` (mirrors `missing_benchmarks_from_include` /
    `resolve_benchmarks` for benchmarks) - so a typo'd or removed platform id
    in a sweep config's `platforms.include` list would otherwise vanish with
    zero signal before `enumerate_cells_with_pruning` ever sees it. This
    exposes exactly which requested ids were dropped for that reason,
    preserving request order and de-duplicating, so callers can turn them
    into accounting rows instead of a silent drop.
    """
    known_set = set(known_platform_ids()) if known is None else set(known)
    seen: set[str] = set()
    missing: list[str] = []
    for platform in include:
        if platform not in known_set and platform not in seen:
            seen.add(platform)
            missing.append(platform)
    return missing


def resolve_platforms(
    groups: Iterable[str] = (),
    include: Iterable[str] = (),
    exclude: Iterable[str] = (),
    known: Iterable[str] | None = None,
) -> list[str]:
    """Resolve a final platform list given group, include, and exclude filters.

    Order: groups expanded first (in the order given, deduplicated by first
    occurrence), then `include` appended, then `exclude` removed. `include`
    entries absent from `known` (default `known_platform_ids()`) are silently
    dropped, mirroring `resolve_benchmarks`; use `missing_platforms_from_include`
    to surface those drops as accounting rows.
    """
    known_set = set(known_platform_ids()) if known is None else set(known)
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
        if platform in known_set and platform not in seen:
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


def probe_platform_reachability(platform: str, *, timeout_s: float = 2.0) -> bool:
    """Return True iff `platform` has no port mapping or its port is open RIGHT NOW.

    The no-cache variant: never reads `_REACHABILITY_CACHE` and never writes
    to it. Two callers need that guarantee, for opposite reasons.

    1. The per-cell liveness probe (`phases/execute.py`). A cached answer is
       useless to it by construction -- it exists precisely to notice that a
       stack which WAS reachable has since died, which is the only way to
       catch a container that outlives the post-start readiness check. The
       2026-08-04 CedarDB incident died ~29s after `up --wait` returned and
       every subsequent cell was recorded as a cell failure.
    2. The post-start readiness check. Writing `True` here would poison the
       cache for whatever probes next, converting a later real probe into a
       stale cached pass.

    `platform_is_reachable` remains the cached, once-per-process entry point
    for callers that just want "is this platform up" at sweep or platform
    granularity. The reachability endpoint is re-resolved from the
    compose-derived facts on every call so an env override (e.g.
    SINGLESTORE_HOST_PORT) set before the probe is honored.
    """
    addr = docker_assets.host_reachability_endpoint(platform)
    if addr is None:
        # No probe configured -> assume reachable. Costs no socket, so the
        # per-cell liveness probe is free for native platforms (duckdb, ...).
        return True
    host, _, port_s = addr.partition(":")
    try:
        port = int(port_s)
    except ValueError:
        return True
    return tcp_probe(host, port, timeout_s=timeout_s)


def platform_is_reachable(platform: str) -> bool:
    """Return True iff `platform` has no port mapping or its port is open.

    Cached per platform for this process (see `_REACHABILITY_CACHE`);
    invalidated only by `invalidate_reachability_cache_after_lifecycle_change`.
    Use `probe_platform_reachability` when a fresh answer is required.
    """
    if platform in _REACHABILITY_CACHE:
        return _REACHABILITY_CACHE[platform]
    reachable = probe_platform_reachability(platform)
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


def missing_benchmarks_from_include(
    include: Iterable[str],
    benchmarks: dict[str, BenchmarkInfo] | None = None,
) -> list[str]:
    """Return `include` entries naming a benchmark absent from the registry.

    `resolve_benchmarks` silently drops `include` entries that are not keys of
    `benchmarks` (so its group/exclude filtering never has to special-case an
    unknown id) - which means a typo'd or removed benchmark id in a sweep
    config's `benchmarks.include` list vanishes with zero signal before
    `enumerate_cells_with_pruning` ever sees it. This exposes exactly which
    requested ids were dropped for that reason, preserving request order and
    de-duplicating, so callers can turn them into accounting rows instead of
    a silent drop.
    """
    if benchmarks is None:
        benchmarks = load_benchmarks()
    seen: set[str] = set()
    missing: list[str] = []
    for bid in include:
        if bid not in benchmarks and bid not in seen:
            seen.add(bid)
            missing.append(bid)
    return missing


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
    quiet: bool = True,
) -> list[str]:
    """Build the full `uv run -- benchbox run ...` argv for a single cell.

    Combines uv extras, platform `--platform-option` blocks, platform CLI
    flags, and any caller-provided extra argv.

    ``quiet`` defaults to ``True`` so the final stdout line is the result-JSON
    path (parsed by the runner). Pass ``quiet=False`` to capture a full
    diagnostic transcript when a cell exits non-zero with no captured output.
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
    ]
    if quiet:
        argv += ["--quiet"]
    argv += [
        "--phases",
        phases,
    ]
    if compression is not None:
        argv += ["--compression", compression]
    argv += PLATFORM_CLI_FLAGS.get(platform, [])
    argv += docker_assets.platform_extra_opts(platform)
    if local_managed_platform:
        argv += docker_assets.local_managed_platform_extra_opts(platform)
    argv += list(extra_args)
    return argv


def benchbox_run_official_argv(
    platform: str,
    benchmark: str,
    scale: float,
    *,
    phases: str,
    streams: int,
    seed: int | None = None,
    extra_args: Iterable[str] = (),
    local_managed_platform: bool = False,
    quiet: bool = True,
) -> list[str]:
    """Build the `uv run -- benchbox run-official ...` argv for a throughput cell.

    `run-official` (unlike `run`) has a `--streams` option that reaches
    `BenchmarkConfig.concurrency` via `_forward_requested_streams`
    (`benchbox/cli/commands/run_official.py`) -- the only CLI surface that
    can request N>1 concurrent throughput streams today; see
    `tests.uat.throughput` and the `throughput-stream-count-wiring-defect`
    TODO's `deferred` note. `run-official` requires a TPC-compliant scale
    factor (`tests.uat.throughput.TPC_ALLOWED_SCALE_FACTORS`). UAT uses
    `--quiet` by default so the deprecated command reuses the same final
    bare-path stdout contract as `benchbox run`; callers can disable it for
    a verbose diagnostic rerun.
    """
    argv = uv_run_argv(platform)
    argv += [
        "benchbox",
        "run-official",
        benchmark,
        "--platform",
        platform,
        "--scale",
        str(scale),
        "--phases",
        phases,
        "--streams",
        str(streams),
    ]
    if seed is not None:
        argv += ["--seed", str(seed)]
    if quiet:
        argv += ["--quiet"]
    argv += PLATFORM_CLI_FLAGS.get(platform, [])
    argv += docker_assets.platform_extra_opts(platform)
    if local_managed_platform:
        argv += docker_assets.local_managed_platform_extra_opts(platform)
    argv += list(extra_args)
    return argv
