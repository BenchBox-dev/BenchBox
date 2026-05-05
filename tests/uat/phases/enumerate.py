"""Enumerate phase: resolve the final cell list given config filters and registry truth."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from tests.uat.matrix import (
    DATAFRAME_PLATFORMS,
    KNOWN_SQL_ONLY_BENCHMARKS,
    BenchmarkInfo,
    filter_scales_by_registry,
    load_benchmarks,
    resolve_benchmarks,
    resolve_platforms,
)


@dataclass(frozen=True)
class Cell:
    platform: str
    benchmark: str
    scale: float


def _is_dataframe_platform(platform: str) -> bool:
    return platform in DATAFRAME_PLATFORMS


def _is_sql_only(benchmark: str, info: BenchmarkInfo) -> bool:
    if benchmark in KNOWN_SQL_ONLY_BENCHMARKS:
        return True
    return not info.supports_dataframe


def enumerate_cells(
    raw: dict[str, Any],
    *,
    benchmarks: dict[str, BenchmarkInfo] | None = None,
) -> list[Cell]:
    """Build the cell list from a validated config's `raw:` payload.

    - Resolves platforms via groups/include/exclude.
    - Resolves benchmarks via groups/include/exclude.
    - Drops dataframe platforms paired with SQL-only benchmarks.
    - For each (platform, benchmark), filters the scale ladder against
      the registry's `scale_options`.
    - Honours `scales.override` (single scale per cell) over `scales.rungs`.
    """
    benchmarks = benchmarks if benchmarks is not None else load_benchmarks()
    platforms_cfg = raw.get("platforms") or {}
    benchmarks_cfg = raw.get("benchmarks") or {}
    scales_cfg = raw.get("scales") or {}

    # Default groups apply only when neither `groups` nor `include` is set.
    # Otherwise an explicit `include` would otherwise be unioned with the
    # default group, producing too-large matrices.
    platform_groups_default = ["sql"] if "include" not in platforms_cfg else []
    benchmark_groups_default = ["all"] if "include" not in benchmarks_cfg else []
    platform_list = resolve_platforms(
        groups=_as_list(platforms_cfg.get("groups", platform_groups_default)),
        include=_as_list(platforms_cfg.get("include", [])),
        exclude=_as_list(platforms_cfg.get("exclude", [])),
    )
    benchmark_list = resolve_benchmarks(
        groups=_as_list(benchmarks_cfg.get("groups", benchmark_groups_default)),
        include=_as_list(benchmarks_cfg.get("include", [])),
        exclude=_as_list(benchmarks_cfg.get("exclude", [])),
        benchmarks=benchmarks,
    )

    override = scales_cfg.get("override")
    rungs = _as_list(scales_cfg.get("rungs", [0.01]))

    cells: list[Cell] = []
    for platform in platform_list:
        for benchmark in benchmark_list:
            info = benchmarks.get(benchmark)
            if info is None:
                continue
            if _is_dataframe_platform(platform) and _is_sql_only(benchmark, info):
                continue
            if override is not None:
                requested = [float(override)]
            else:
                requested = [float(r) for r in rungs]
            filtered = filter_scales_by_registry(benchmark, requested, info=info)
            if not filtered and override is None and info.min_scale is not None:
                filtered = [info.min_scale]
            for scale in filtered:
                cells.append(Cell(platform=platform, benchmark=benchmark, scale=scale))
    return cells


def _as_list(value: Iterable | None) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)
