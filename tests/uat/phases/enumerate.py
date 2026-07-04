"""Enumerate phase: resolve the final cell list given config filters and registry truth."""

from __future__ import annotations

from dataclasses import dataclass

from tests.uat.compatibility import CompatibilityRule, compatibility_rule_for
from tests.uat.config import UATConfig
from tests.uat.matrix import (
    BenchmarkInfo,
    filter_scales_by_registry,
    load_benchmarks,
    missing_benchmarks_from_include,
    resolve_benchmarks,
    resolve_platforms,
)

# Rows recorded with this status are registry/ladder-derived accounting
# entries rather than platform/benchmark compatibility-rule prunes (those use
# `CompatibilityRule.status`, e.g. "blocked"). Reusing `CompatibilityPrunedCell`
# for both keeps a single pruned-accounting shape (compatibility_pruned.jsonl)
# per the anti-pattern this module avoids: inventing a second, differently
# shaped accounting file for registry-derived drops.
REGISTRY_PRUNE_STATUS = "pruned-registry"
BENCHMARK_NOT_IN_REGISTRY_RULE_ID = "benchmark-not-in-registry"


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
    platform_groups_default = ("sql",) if config.platforms.uses_implicit_group_default else ()
    benchmark_groups_default = ("all",) if config.benchmarks.uses_implicit_group_default else ()
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

    if config.scales.override is not None:
        requested = [config.scales.override]
    else:
        requested = list(config.scales.rungs)

    cells: list[Cell] = []
    compatibility_pruned: list[CompatibilityPrunedCell] = []
    include_release_gate_runtime_envelopes = config.compatibility.release_gate_runtime_envelopes

    # `resolve_benchmarks` silently drops `benchmarks.include` entries absent
    # from the registry (see `missing_benchmarks_from_include`'s docstring) -
    # so a typo'd/removed benchmark id never reaches `benchmark_list` below.
    # Surface it here as a visible accounting row instead of a zero-signal
    # drop, one row per platform x requested scale (mirrors the shape
    # `_pruned_rows_for_rule` already uses for compatibility-rule prunes).
    for missing_benchmark in missing_benchmarks_from_include(config.benchmarks.include, benchmarks):
        for platform in platform_list:
            compatibility_pruned.extend(
                _registry_absent_rows(platform=platform, benchmark=missing_benchmark, requested=requested)
            )

    for platform in platform_list:
        for benchmark in benchmark_list:
            info = benchmarks.get(benchmark)
            if info is None:
                # Defensive: `benchmark_list` is built from `benchmarks` above,
                # so this should be unreachable, but a config-benchmark id
                # absent from the registry must never vanish silently -
                # record the same accounting row rather than a bare continue.
                compatibility_pruned.extend(
                    _registry_absent_rows(platform=platform, benchmark=benchmark, requested=requested)
                )
                continue
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
            dropped = [scale for scale in requested if scale not in filtered]
            uses_min_scale_fallback = not filtered and config.scales.override is None and info.min_scale is not None
            if uses_min_scale_fallback:
                # The whole requested ladder was outside scale_options (e.g.
                # joinorder/tpcds_obt are single-scale-1.0-only benchmarks
                # requested at the 0.01 smoke scale); the benchmark still
                # runs, just at its canonical min_scale instead of vanishing,
                # so this is a substitution, not a drop - no accounting row.
                filtered = [info.min_scale]
            elif dropped:
                # Some, but not all, requested scales survived: the dropped
                # ones truly do not run at any scale and must be visible in
                # accounting output instead of silently shrinking the ladder.
                compatibility_pruned.extend(
                    _ladder_pruned_rows(platform=platform, benchmark=benchmark, dropped=dropped)
                )
            for scale in filtered:
                cells.append(Cell(platform=platform, benchmark=benchmark, scale=scale))
    return EnumerationResult(cells=tuple(cells), compatibility_pruned=tuple(compatibility_pruned))


def _registry_absent_rows(
    *,
    platform: str,
    benchmark: str,
    requested: list[float],
) -> list[CompatibilityPrunedCell]:
    """Accounting rows for a benchmark id absent from the registry entirely."""
    return [
        CompatibilityPrunedCell(
            platform=platform,
            benchmark=benchmark,
            scale=scale,
            rule_id=BENCHMARK_NOT_IN_REGISTRY_RULE_ID,
            status=REGISTRY_PRUNE_STATUS,
            reason=(
                f"Benchmark {benchmark!r} was requested in the config but is not present in the "
                "benchmark registry (typo'd or removed benchmark id)."
            ),
            evidence="tests.uat.matrix.load_benchmarks() BENCHMARK_METADATA keys",
        )
        for scale in requested
    ]


def _ladder_pruned_rows(
    *,
    platform: str,
    benchmark: str,
    dropped: list[float],
) -> list[CompatibilityPrunedCell]:
    """Accounting rows for scales dropped by the registry scale-ladder filter."""
    return [
        CompatibilityPrunedCell(
            platform=platform,
            benchmark=benchmark,
            scale=scale,
            rule_id=f"uat.ladder.{benchmark}.scale-not-in-registry",
            status=REGISTRY_PRUNE_STATUS,
            reason=(
                f"scale {scale} is outside {benchmark}'s registered scale_options and was dropped "
                "by the scale-ladder registry filter."
            ),
            evidence="tests.uat.matrix.filter_scales_by_registry against benchmark registry scale_options",
        )
        for scale in dropped
    ]


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
