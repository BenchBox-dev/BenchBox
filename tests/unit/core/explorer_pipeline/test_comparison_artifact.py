"""Unit tests for build_comparison_artifact and disambiguate_platform_labels."""

from __future__ import annotations

import pytest

from benchbox.core.explorer_pipeline.models import (
    ComparisonArtifact,
    DetailResult,
    QueryDisplayTiming,
)
from benchbox.core.explorer_pipeline.transformer import build_comparison_artifact
from benchbox.core.labels import disambiguate_platform_labels as _disambiguate_platform_labels

pytestmark = [pytest.mark.unit, pytest.mark.fast]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE: dict = {
    "benchmark": "tpch",
    "scale_factor": 0.1,
    "platform": "DuckDB",
    "platform_id": "duckdb",
    "driver_version": None,
    "run_date": "2026-04-01",
    "total_duration_s": 60.0,
    "geomean_ms": 100.0,
    "display_geomean_ms": 100.0,
    "power_score": 3000.0,
    "environment": {},
    "queries": [],
    "has_plans": False,
    "has_tuning": False,
    "bundle_download_url": "",
    "trust_label": "maintainer-run",
    "visibility": "public-curated",
    "platform_version": None,
    "execution_mode": None,
    "tuning_mode": None,
    "tuning_hash": None,
    "test_type": "power",
    "validation_status": None,
    "cost_usd": None,
}


def _make_detail(
    result_id: str = "r1",
    display_timings: list[QueryDisplayTiming] | None = None,
    **kwargs,
) -> DetailResult:
    data = dict(_BASE)
    data.update(kwargs)
    data["result_id"] = result_id
    data["display_timings"] = display_timings or [
        QueryDisplayTiming(query_id="Q1", display_ms=10.0, sample_count=3),
        QueryDisplayTiming(query_id="Q2", display_ms=20.0, sample_count=3),
    ]
    return DetailResult.model_validate(data)


DUCKDB = _make_detail("r1")
SQLITE = _make_detail(
    "r2",
    platform="SQLite",
    platform_id="sqlite",
    driver_version=None,
    display_geomean_ms=200.0,
    power_score=300.0,
    display_timings=[
        QueryDisplayTiming(query_id="Q1", display_ms=100.0, sample_count=3),
        QueryDisplayTiming(query_id="Q2", display_ms=200.0, sample_count=3),
    ],
)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestComparisonArtifactSchema:
    def test_schema_version_is_2(self) -> None:
        art = build_comparison_artifact([DUCKDB, SQLITE])
        assert art.schema_version == 2

    def test_pydantic_validates_roundtrip(self) -> None:
        art = build_comparison_artifact([DUCKDB, SQLITE])
        dumped = art.model_dump()
        validated = ComparisonArtifact.model_validate(dumped)
        assert validated.schema_version == art.schema_version
        assert validated.benchmark == art.benchmark

    def test_raises_on_different_benchmarks(self) -> None:
        other = _make_detail("r2", benchmark="clickbench", platform_id="clickbench")
        with pytest.raises(ValueError, match="benchmark"):
            build_comparison_artifact([DUCKDB, other])

    def test_raises_on_different_scale_factors(self) -> None:
        other = _make_detail("r2", scale_factor=1.0, platform_id="sqlite")
        with pytest.raises(ValueError, match="scale factor"):
            build_comparison_artifact([DUCKDB, other])

    def test_raises_on_empty_list(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            build_comparison_artifact([])


# ---------------------------------------------------------------------------
# Row construction
# ---------------------------------------------------------------------------


class TestComparisonRows:
    def test_row_count_matches_input(self) -> None:
        art = build_comparison_artifact([DUCKDB, SQLITE])
        assert len(art.rows) == 2

    def test_result_ids_preserved_in_order(self) -> None:
        art = build_comparison_artifact([DUCKDB, SQLITE])
        assert [r.result_id for r in art.rows] == ["r1", "r2"]

    def test_display_labels_populated(self) -> None:
        art = build_comparison_artifact([DUCKDB, SQLITE])
        assert art.rows[0].display_label == "DuckDB"
        assert art.rows[1].display_label == "SQLite"

    def test_ranking_primary_metric_tpch(self) -> None:
        art = build_comparison_artifact([DUCKDB, SQLITE])
        assert art.ranking_primary_metric == "power_score"

    def test_ranking_primary_metric_clickbench(self) -> None:
        cb1 = _make_detail("r1", benchmark="clickbench")
        cb2 = _make_detail("r2", benchmark="clickbench", platform="SQLite", platform_id="sqlite")
        art = build_comparison_artifact([cb1, cb2])
        assert art.ranking_primary_metric == "display_geomean_ms"

    def test_single_result_rows_ok(self) -> None:
        art = build_comparison_artifact([DUCKDB])
        assert len(art.rows) == 1
        assert len(art.query_cells) == 2

    def test_rows_carry_audit_and_display_fields(self) -> None:
        # ComparisonRow must expose enough state for Compare.tsx to render
        # byte-identically to the per-detail fallback path.
        d = _make_detail(
            "r1",
            driver_version="1.2.0",
            total_duration_s=42.5,
            geomean_ms=99.0,
            compliance_class="full",
        )
        art = build_comparison_artifact([d])
        row = art.rows[0]
        assert row.platform == "DuckDB"
        assert row.driver_version == "1.2.0"
        assert row.total_duration_s == pytest.approx(42.5)
        assert row.geomean_ms == pytest.approx(99.0)
        assert row.compliance_class == "full"
        assert row.query_count == 2


# ---------------------------------------------------------------------------
# Query cell math
# ---------------------------------------------------------------------------


class TestQueryCells:
    def test_query_ids_natural_sorted(self) -> None:
        d1 = _make_detail(
            "r1",
            display_timings=[
                QueryDisplayTiming(query_id="Q10", display_ms=5.0, sample_count=1),
                QueryDisplayTiming(query_id="Q2", display_ms=10.0, sample_count=1),
                QueryDisplayTiming(query_id="Q1", display_ms=15.0, sample_count=1),
            ],
        )
        art = build_comparison_artifact([d1])
        assert [c.query_id for c in art.query_cells] == ["Q1", "Q2", "Q10"]

    def test_display_ms_per_row_values(self) -> None:
        art = build_comparison_artifact([DUCKDB, SQLITE])
        q1 = next(c for c in art.query_cells if c.query_id == "Q1")
        assert q1.display_ms_per_row == [10.0, 100.0]

    def test_fastest_ms_is_min(self) -> None:
        art = build_comparison_artifact([DUCKDB, SQLITE])
        q1 = next(c for c in art.query_cells if c.query_id == "Q1")
        assert q1.fastest_ms == pytest.approx(10.0)

    def test_slowest_ms_is_max(self) -> None:
        art = build_comparison_artifact([DUCKDB, SQLITE])
        q1 = next(c for c in art.query_cells if c.query_id == "Q1")
        assert q1.slowest_ms == pytest.approx(100.0)

    def test_speedup_vs_slowest_definition(self) -> None:
        # speedup_vs_slowest = slowest / this  (always >= 1 for the fastest)
        art = build_comparison_artifact([DUCKDB, SQLITE])
        q1 = next(c for c in art.query_cells if c.query_id == "Q1")
        # DUCKDB: 100 / 10 = 10x  |  SQLITE: 100 / 100 = 1x
        assert q1.speedup_vs_slowest_per_row[0] == pytest.approx(10.0)
        assert q1.speedup_vs_slowest_per_row[1] == pytest.approx(1.0)

    def test_missing_query_produces_none_entry(self) -> None:
        # SQLITE doesn't have Q3 - its cell should be None
        d1 = _make_detail(
            "r1",
            display_timings=[
                QueryDisplayTiming(query_id="Q1", display_ms=10.0, sample_count=1),
                QueryDisplayTiming(query_id="Q3", display_ms=30.0, sample_count=1),
            ],
        )
        d2 = _make_detail(
            "r2",
            platform="SQLite",
            platform_id="sqlite",
            display_timings=[
                QueryDisplayTiming(query_id="Q1", display_ms=100.0, sample_count=1),
            ],
        )
        art = build_comparison_artifact([d1, d2])
        q3 = next(c for c in art.query_cells if c.query_id == "Q3")
        assert q3.display_ms_per_row == [30.0, None]
        assert q3.speedup_vs_slowest_per_row[1] is None

    def test_all_failed_query_produces_all_none(self) -> None:
        d1 = _make_detail(
            "r1",
            display_timings=[QueryDisplayTiming(query_id="Q1", display_ms=None, sample_count=0)],
        )
        d2 = _make_detail(
            "r2",
            platform="SQLite",
            platform_id="sqlite",
            display_timings=[QueryDisplayTiming(query_id="Q1", display_ms=None, sample_count=0)],
        )
        art = build_comparison_artifact([d1, d2])
        q1 = art.query_cells[0]
        assert q1.display_ms_per_row == [None, None]
        assert q1.fastest_ms is None
        assert q1.slowest_ms is None
        assert all(v is None for v in q1.speedup_vs_slowest_per_row)

    def test_single_result_speedup_is_one(self) -> None:
        art = build_comparison_artifact([DUCKDB])
        q1 = art.query_cells[0]
        # Only one result: slowest == fastest == this → speedup = 1.0
        assert q1.speedup_vs_slowest_per_row[0] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Comparability warnings
# ---------------------------------------------------------------------------


class TestComparabilityWarnings:
    def test_no_warnings_for_clean_pair(self) -> None:
        art = build_comparison_artifact([DUCKDB, SQLITE])
        assert art.comparability_warnings == []

    def test_cross_test_type_warning(self) -> None:
        d_power = _make_detail("r1", test_type="power")
        d_standard = _make_detail("r2", platform="SQLite", platform_id="sqlite", test_type="standard")
        art = build_comparison_artifact([d_power, d_standard])
        assert any(w.dimension == "Test type" for w in art.comparability_warnings)
        test_type_warning = next(w for w in art.comparability_warnings if w.dimension == "Test type")
        assert set(test_type_warning.values) == {"power", "standard"}

    def test_cross_tuning_warning(self) -> None:
        d_tuned = _make_detail("r1", tuning_mode="tuned")
        d_no_tune = _make_detail("r2", platform="SQLite", platform_id="sqlite", tuning_mode="notuning")
        art = build_comparison_artifact([d_tuned, d_no_tune])
        assert any(w.dimension == "Tuning config" for w in art.comparability_warnings)

    def test_query_count_mismatch_warning(self) -> None:
        d_short = _make_detail(
            "r1",
            display_timings=[QueryDisplayTiming(query_id="Q1", display_ms=10.0, sample_count=1)],
        )
        d_long = _make_detail(
            "r2",
            platform="SQLite",
            platform_id="sqlite",
            display_timings=[
                QueryDisplayTiming(query_id="Q1", display_ms=100.0, sample_count=1),
                QueryDisplayTiming(query_id="Q2", display_ms=200.0, sample_count=1),
            ],
        )
        art = build_comparison_artifact([d_short, d_long])
        assert any(w.dimension == "Query scope" for w in art.comparability_warnings)

    def test_execution_mode_warning(self) -> None:
        d_sql = _make_detail("r1", execution_mode="sql")
        d_df = _make_detail("r2", platform="SQLite", platform_id="sqlite", execution_mode="dataframe")
        art = build_comparison_artifact([d_sql, d_df])
        assert any(w.dimension == "Execution mode" for w in art.comparability_warnings)


# ---------------------------------------------------------------------------
# Platform label disambiguation
# ---------------------------------------------------------------------------


class TestDisambiguatePlatformLabels:
    def test_unique_platforms_unchanged(self) -> None:
        d1 = _make_detail("r1", platform="DuckDB", platform_id="duckdb")
        d2 = _make_detail("r2", platform="SQLite", platform_id="sqlite")
        labels = _disambiguate_platform_labels([d1, d2])
        assert labels == ["DuckDB", "SQLite"]

    def test_same_platform_disambiguated_by_driver_version(self) -> None:
        d1 = _make_detail("r1", platform="DuckDB", platform_id="duckdb", driver_version="1.0.0")
        d2 = _make_detail("r2", platform="DuckDB", platform_id="duckdb", driver_version="1.2.0")
        labels = _disambiguate_platform_labels([d1, d2])
        assert labels == ["DuckDB v1.0.0", "DuckDB v1.2.0"]

    def test_same_platform_disambiguated_by_execution_mode(self) -> None:
        d1 = _make_detail("r1", platform="DuckDB", platform_id="duckdb", execution_mode="sql")
        d2 = _make_detail("r2", platform="DuckDB", platform_id="duckdb", execution_mode="dataframe")
        labels = _disambiguate_platform_labels([d1, d2])
        assert labels == ["DuckDB (sql)", "DuckDB (df)"]

    def test_same_platform_disambiguated_by_scale_factor(self) -> None:
        d1 = _make_detail("r1", platform="DuckDB", platform_id="duckdb", scale_factor=0.1)
        d2 = _make_detail("r2", platform="DuckDB", platform_id="duckdb", scale_factor=1.0)
        labels = _disambiguate_platform_labels([d1, d2])
        assert labels[0] == "DuckDB SF0.1"
        assert labels[1] == "DuckDB SF1"

    def test_triple_collision_produces_unique_labels(self) -> None:
        d1 = _make_detail("r1", platform="DuckDB", platform_id="duckdb", driver_version="1.0.0")
        d2 = _make_detail("r2", platform="DuckDB", platform_id="duckdb", driver_version="1.1.0")
        d3 = _make_detail("r3", platform="DuckDB", platform_id="duckdb", driver_version="1.2.0")
        labels = _disambiguate_platform_labels([d1, d2, d3])
        assert len(set(labels)) == 3

    def test_single_result_no_suffix(self) -> None:
        d1 = _make_detail("r1", platform="DuckDB", platform_id="duckdb")
        labels = _disambiguate_platform_labels([d1])
        assert labels == ["DuckDB"]

    def test_same_driver_version_cascade_to_execution_mode(self) -> None:
        """When driver_version is equal it doesn't disambiguate; cascade continues to execution_mode."""
        d1 = _make_detail("r1", platform="DuckDB", platform_id="duckdb", driver_version="1.2.0", execution_mode="sql")
        d2 = _make_detail(
            "r2", platform="DuckDB", platform_id="duckdb", driver_version="1.2.0", execution_mode="dataframe"
        )
        labels = _disambiguate_platform_labels([d1, d2])
        # No version suffix (versions are equal); execution_mode adds the suffix.
        assert labels == ["DuckDB (sql)", "DuckDB (df)"]
