from __future__ import annotations

from dataclasses import dataclass

import pytest

from benchbox.core.visualization.chart_generator import (
    generate_comparison_charts,
    normalized_from_dataframe,
    normalized_from_sql_vs_df,
    normalized_from_unified,
)
from benchbox.core.visualization.chart_types import ALL_CHART_TYPES
from benchbox.core.visualization.result_plotter import NormalizedQuery, NormalizedResult

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_all_chart_types_count_matches_registry() -> None:
    """Guard against forward drift: adding a chart type without updating chartRegistry.ts.

    When the count here and in chartRegistry.meta.test.ts disagree, the mismatch
    surfaces in CI so the developer knows to update the TS registry too.
    """
    assert len(ALL_CHART_TYPES) == 16, (
        f"Expected 16 chart types but found {len(ALL_CHART_TYPES)}. "
        "If you added a chart type, also update chartRegistry.ts and chartRegistry.meta.test.ts."
    )


def test_generate_comparison_charts_empty_results_returns_empty(tmp_path):
    assert generate_comparison_charts([], tmp_path) == {}


def test_generate_comparison_charts_exports_supported_chart_types(monkeypatch, tmp_path):
    def _render_single_ascii_chart(results, chart_type, options, subtitle=None):  # noqa: ARG001
        return f"{chart_type}:ok"

    monkeypatch.setattr(
        "benchbox.core.visualization.ascii_api.render_ascii_chart_from_results",
        _render_single_ascii_chart,
    )

    results = [
        NormalizedResult(
            benchmark="comparison",
            platform="duckdb",
            scale_factor=0.01,
            execution_id=None,
            timestamp=None,
            total_time_ms=10.0,
            avg_time_ms=None,
            success_rate=1.0,
            cost_total=None,
            queries=[NormalizedQuery(query_id="Q1", execution_time_ms=10.0, status="SUCCESS")],
        )
    ]

    exported = generate_comparison_charts(results, tmp_path)

    # All three comparison chart types should render (performance_bar, distribution_box, query_heatmap)
    assert set(exported.keys()) == {"performance_bar", "distribution_box", "query_heatmap"}
    for path in exported.values():
        assert path.exists()


@dataclass
class _FakeQueryResult:
    query_id: str
    mean_time_ms: float
    status: str = "SUCCESS"


@dataclass
class _FakePlatformResult:
    platform: str
    query_results: list[_FakeQueryResult]
    total_time_ms: float
    success_rate: float
    timestamp: str | None = None


@dataclass
class _FakeSQLVsDFQuery:
    query_id: str
    sql_time_ms: float
    df_time_ms: float
    status: str = "SUCCESS"


@dataclass
class _FakeSQLVsDFSummary:
    sql_platform: str
    df_platform: str
    query_results: list[_FakeSQLVsDFQuery]


def test_normalized_from_unified_maps_core_fields():
    source = [
        _FakePlatformResult(
            platform="duckdb",
            query_results=[_FakeQueryResult(query_id="Q1", mean_time_ms=20.0)],
            total_time_ms=20.0,
            success_rate=1.0,
        )
    ]
    normalized = normalized_from_unified(source)
    assert len(normalized) == 1
    assert normalized[0].platform == "duckdb"
    assert normalized[0].queries[0].query_id == "Q1"


def test_normalized_from_dataframe_uses_timestamp_when_present():
    source = [
        _FakePlatformResult(
            platform="polars-df",
            query_results=[_FakeQueryResult(query_id="Q7", mean_time_ms=0.0)],
            total_time_ms=0.0,
            success_rate=0.8,
            timestamp="2026-02-09T00:00:00",
        )
    ]
    normalized = normalized_from_dataframe(source)
    assert normalized[0].timestamp == "2026-02-09T00:00:00"
    assert normalized[0].queries[0].execution_time_ms is None


def test_normalized_from_sql_vs_df_returns_two_platform_results():
    summary = _FakeSQLVsDFSummary(
        sql_platform="duckdb",
        df_platform="polars-df",
        query_results=[_FakeSQLVsDFQuery(query_id="Q1", sql_time_ms=10.0, df_time_ms=15.0)],
    )
    normalized = normalized_from_sql_vs_df(summary)

    assert len(normalized) == 2
    assert normalized[0].platform == "duckdb"
    assert normalized[1].platform == "polars-df"
    assert normalized[0].total_time_ms == 10.0
    assert normalized[1].total_time_ms == 15.0
