"""Enumerate phase: resolve the final cell list given config filters and registry truth."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from tests.uat.compatibility import CompatibilityRule, compatibility_rule_for
from tests.uat.matrix import (
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


@dataclass(frozen=True)
class CompatibilityPrunedCell:
    platform: str
    benchmark: str
    scale: float
    rule_id: str
    status: str
    reason: str
    evidence: str


@dataclass(frozen=True)
class EnumerationResult:
    cells: tuple[Cell, ...]
    compatibility_pruned: tuple[CompatibilityPrunedCell, ...]

    @property
    def candidate_count(self) -> int:
        return len(self.cells) + len(self.compatibility_pruned)


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
    return list(enumerate_cells_with_pruning(raw, benchmarks=benchmarks).cells)


def enumerate_cells_with_pruning(
    raw: dict[str, Any],
    *,
    benchmarks: dict[str, BenchmarkInfo] | None = None,
) -> EnumerationResult:
    """Build executable cells plus compatibility-pruned accounting rows."""
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
    compatibility_pruned: list[CompatibilityPrunedCell] = []
    for platform in platform_list:
        for benchmark in benchmark_list:
            info = benchmarks.get(benchmark)
            if info is None:
                continue
            if override is not None:
                requested = [float(override)]
            else:
                requested = [float(r) for r in rungs]
            rule = compatibility_rule_for(platform, benchmark, info)
            if rule is not None:
                compatibility_pruned.extend(
                    _pruned_rows_for_rule(platform=platform, benchmark=benchmark, requested=requested, rule=rule)
                )
                continue
            filtered = filter_scales_by_registry(benchmark, requested, info=info)
            if not filtered and override is None and info.min_scale is not None:
                filtered = [info.min_scale]
            for scale in filtered:
                cells.append(Cell(platform=platform, benchmark=benchmark, scale=scale))
    return EnumerationResult(cells=tuple(cells), compatibility_pruned=tuple(compatibility_pruned))


def _pruned_rows_for_rule(
    *,
    platform: str,
    benchmark: str,
    requested: list[float],
    rule: CompatibilityRule,
) -> list[CompatibilityPrunedCell]:
    return [
        CompatibilityPrunedCell(
            platform=platform,
            benchmark=benchmark,
            scale=scale,
            rule_id=rule.rule_id,
            status=rule.status,
            reason=rule.reason,
            evidence=rule.evidence,
        )
        for scale in requested
    ]


def _as_list(value: Iterable | None) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)
