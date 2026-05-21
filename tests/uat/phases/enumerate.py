"""Enumerate phase: resolve the final cell list given config filters and registry truth."""

from __future__ import annotations

from dataclasses import dataclass

from tests.uat.compatibility import CompatibilityRule, compatibility_rule_for
from tests.uat.config import UATConfig
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
    config: UATConfig,
    *,
    benchmarks: dict[str, BenchmarkInfo] | None = None,
) -> list[Cell]:
    """Build the cell list from a validated config.

    - Resolves platforms via groups/include/exclude.
    - Resolves benchmarks via groups/include/exclude.
    - Drops dataframe platforms paired with SQL-only benchmarks.
    - For each (platform, benchmark), filters the scale ladder against
      the registry's `scale_options`.
    - Honours `scales.override` (single scale per cell) over `scales.rungs`.
    """
    return list(enumerate_cells_with_pruning(config, benchmarks=benchmarks).cells)


def enumerate_cells_with_pruning(
    config: UATConfig,
    *,
    benchmarks: dict[str, BenchmarkInfo] | None = None,
) -> EnumerationResult:
    """Build executable cells plus compatibility-pruned accounting rows."""
    benchmarks = benchmarks if benchmarks is not None else load_benchmarks()

    # Default groups apply only when neither `groups` nor `include` is set.
    # Otherwise an explicit `include` would otherwise be unioned with the
    # default group, producing too-large matrices.
    platform_groups_default = ("sql",) if config.platforms.groups is None and not config.platforms.include else ()
    benchmark_groups_default = ("all",) if config.benchmarks.groups is None and not config.benchmarks.include else ()
    platform_list = resolve_platforms(
        groups=config.platforms.groups if config.platforms.groups is not None else platform_groups_default,
        include=config.platforms.include,
        exclude=config.platforms.exclude,
    )
    benchmark_list = resolve_benchmarks(
        groups=config.benchmarks.groups if config.benchmarks.groups is not None else benchmark_groups_default,
        include=config.benchmarks.include,
        exclude=config.benchmarks.exclude,
        benchmarks=benchmarks,
    )

    cells: list[Cell] = []
    compatibility_pruned: list[CompatibilityPrunedCell] = []
    include_release_gate_runtime_envelopes = config.compatibility.release_gate_runtime_envelopes
    for platform in platform_list:
        for benchmark in benchmark_list:
            info = benchmarks.get(benchmark)
            if info is None:
                continue
            if config.scales.override is not None:
                requested = [config.scales.override]
            else:
                requested = list(config.scales.rungs)
            rule = compatibility_rule_for(
                platform,
                benchmark,
                info,
                include_release_gate_runtime_envelopes=include_release_gate_runtime_envelopes,
            )
            if rule is not None:
                compatibility_pruned.extend(
                    _pruned_rows_for_rule(platform=platform, benchmark=benchmark, requested=requested, rule=rule)
                )
                continue
            filtered = filter_scales_by_registry(benchmark, requested, info=info)
            if not filtered and config.scales.override is None and info.min_scale is not None:
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
