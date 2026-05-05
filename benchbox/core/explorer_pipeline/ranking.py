"""Shared cohort ranking helpers for explorer read models."""

from __future__ import annotations

from dataclasses import dataclass

from benchbox.core.explorer_pipeline.compare_math import speedup_vs_best, speedup_vs_slowest
from benchbox.core.explorer_pipeline.models import BenchmarkSummary, PlatformRow


@dataclass(frozen=True)
class RankedPlatform:
    """A platform row plus its cohort-relative ranking metrics."""

    row: PlatformRow
    metric_value: float | None
    rank: int | None
    total_ranked: int
    speedup_vs_best: float | None
    speedup_vs_slowest: float | None


@dataclass(frozen=True)
class RankedCohort:
    """Canonical ranking result for a benchmark/scale/phase cohort."""

    rows: list[RankedPlatform]
    primary_metric: str
    primary_order: str
    higher_is_better: bool
    best_value: float | None
    slowest_value: float | None


def rank_platforms(summary: BenchmarkSummary) -> RankedCohort:
    """Rank a benchmark summary with standard competition ranking.

    Tied rows share the same rank and the next distinct row skips by the tie
    size. Null primary metrics sort last and receive no rank.
    """

    ranking = summary.ranking
    primary_metric = ranking.primary_metric if ranking else "display_geomean_ms"
    primary_order = ranking.primary_order if ranking else "asc"
    higher_is_better = primary_order == "desc"

    def metric_value(row: PlatformRow) -> float | None:
        return row.power_score if primary_metric == "power_score" else row.display_geomean_ms

    def sort_key(row: PlatformRow) -> tuple[bool, float]:
        value = metric_value(row)
        if value is None:
            return (True, 0.0)
        return (False, -value if higher_is_better else value)

    sorted_rows = sorted(summary.platforms, key=sort_key)
    values = [value for value in (metric_value(row) for row in sorted_rows) if value is not None]
    best_value = (max(values) if higher_is_better else min(values)) if values else None
    slowest_value = (min(values) if higher_is_better else max(values)) if values else None

    ranked_rows: list[RankedPlatform] = []
    current_rank = 1
    previous_value: float | None = None
    for idx, row in enumerate(sorted_rows):
        value = metric_value(row)
        if value is None:
            rank = None
        else:
            if previous_value is not None and value != previous_value:
                current_rank = idx + 1
            rank = current_rank
            previous_value = value
        ranked_rows.append(
            RankedPlatform(
                row=row,
                metric_value=value,
                rank=rank,
                total_ranked=len(values),
                speedup_vs_best=speedup_vs_best(value, best_value, higher_is_better=higher_is_better),
                speedup_vs_slowest=speedup_vs_slowest(value, slowest_value, higher_is_better=higher_is_better),
            )
        )

    return RankedCohort(
        rows=ranked_rows,
        primary_metric=primary_metric,
        primary_order=primary_order,
        higher_is_better=higher_is_better,
        best_value=best_value,
        slowest_value=slowest_value,
    )
