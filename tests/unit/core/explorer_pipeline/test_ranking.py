"""Unit tests for explorer cohort ranking helpers."""

from __future__ import annotations

import pytest

from benchbox.core.explorer_pipeline.models import BenchmarkSummary, PlatformRow, RankingConfig
from benchbox.core.explorer_pipeline.ranking import rank_platforms

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _make_summary(
    *,
    primary_metric: str,
    primary_order: str,
    platforms: list[PlatformRow],
) -> BenchmarkSummary:
    return BenchmarkSummary(
        benchmark="tpch",
        scale_factor=0.01,
        phase="power",
        query_ids=[],
        platforms=platforms,
        ranking=RankingConfig(
            primary_metric=primary_metric,
            secondary_metric="display_geomean_ms",
            primary_order=primary_order,
        ),
    )


def _make_platform_row(
    platform_id: str,
    *,
    power_score: float | None = None,
    display_geomean_ms: float | None = None,
) -> PlatformRow:
    return PlatformRow(
        result_id=f"result-{platform_id}",
        short_id=platform_id,
        platform_id=platform_id,
        platform=platform_id,
        platform_version=None,
        tuning_mode=None,
        tuning_hash=None,
        execution_mode=None,
        trust_label="maintainer-run",
        run_date="2026-05-05T00:00:00Z",
        is_ranking_eligible=True,
        power_score=power_score,
        display_geomean_ms=display_geomean_ms,
        sample_geomean_ms=None,
        cost_usd=None,
        compliance_class=None,
        percentile_stats=None,
        phase_durations=None,
        timings={},
    )


def test_latency_speedup_references_ignore_non_positive_metric_values() -> None:
    ranked = rank_platforms(
        _make_summary(
            primary_metric="display_geomean_ms",
            primary_order="asc",
            platforms=[
                _make_platform_row("zero", display_geomean_ms=0.0),
                _make_platform_row("duckdb", display_geomean_ms=100.0),
                _make_platform_row("sqlite", display_geomean_ms=200.0),
            ],
        )
    )

    by_platform = {row.row.platform_id: row for row in ranked.rows}

    assert ranked.best_value == pytest.approx(100.0)
    assert ranked.slowest_value == pytest.approx(200.0)
    assert by_platform["zero"].speedup_vs_best is None
    assert by_platform["duckdb"].speedup_vs_best == pytest.approx(1.0)
    assert by_platform["sqlite"].speedup_vs_slowest == pytest.approx(1.0)


def test_power_score_speedup_references_ignore_non_positive_metric_values() -> None:
    ranked = rank_platforms(
        _make_summary(
            primary_metric="power_score",
            primary_order="desc",
            platforms=[
                _make_platform_row("duckdb", power_score=3000.0),
                _make_platform_row("sqlite", power_score=1500.0),
                _make_platform_row("negative", power_score=-1.0),
            ],
        )
    )

    by_platform = {row.row.platform_id: row for row in ranked.rows}

    assert ranked.best_value == pytest.approx(3000.0)
    assert ranked.slowest_value == pytest.approx(1500.0)
    assert by_platform["duckdb"].speedup_vs_best == pytest.approx(1.0)
    assert by_platform["sqlite"].speedup_vs_slowest == pytest.approx(1.0)
    assert by_platform["negative"].speedup_vs_slowest is None
