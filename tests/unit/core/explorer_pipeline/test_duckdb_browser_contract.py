"""DuckDB browser contract tests (G-1, G-10, G-11 exit gates).

Verifies that build_full() produces the canonical 10-table schema defined in
browser-duckdb-schema.sql and that all tables are populated with correct data.
"""

from __future__ import annotations

import math
from pathlib import Path

import duckdb
import pytest

from benchbox.core.explorer_pipeline.pipeline import SUBMISSION_MANIFEST_SUFFIX, ExplorerPipeline
from tests.unit.core.explorer_pipeline.conftest import MINIMAL_BUNDLE

pytestmark = [pytest.mark.unit, pytest.mark.fast]

# ---------------------------------------------------------------------------
# Shared fixture - runs the full pipeline once per class and returns the DB path
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build a full pipeline output from MINIMAL_BUNDLE and return the DB path."""
    import json

    base = tmp_path_factory.mktemp("pipeline_output")
    data_dir = base / "data"
    bundles_dir = data_dir / "bundles"
    bundles_dir.mkdir(parents=True)
    (bundles_dir / "bundle.json").write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")

    output_dir = base / "out"
    ExplorerPipeline().run(data_dir, output_dir, bundle_url_prefix="/results/data/bundles")

    return output_dir / "results.duckdb"


def _connect(db: Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db), read_only=True)


# ---------------------------------------------------------------------------
# G-1: Schema contract - all 10 canonical tables and 2 views must exist
# ---------------------------------------------------------------------------


class TestG1SchemaContract:
    """All canonical tables and views exist with the expected column sets."""

    EXPECTED_TABLES = {
        "results": {
            "result_id",
            "benchmark",
            "scale_factor",
            "platform",
            "platform_id",
            "driver_version",
            "run_date",
            "power_score",
            "total_duration_s",
            "geomean_ms",
            "display_geomean_ms",
            "query_count",
            "logical_query_count",
            "has_display_timing",
            "valid_query_count",
            "missing_query_count",
            "zero_timing_count",
            "display_exclusion_reason",
            "comparison_exclusion_reason",
            "ranking_exclusion_reason",
            "trust_label",
            "visibility",
            "platform_version",
            "execution_mode",
            "tuning_mode",
            "tuning_hash",
            "test_type",
            "validation_status",
            "cost_usd",
            "normalized_cost_usd",
            "cost_model_version",
            "cost_model_source",
            "cost_scope",
            "cost_status",
            "billing_unit",
            "pricing_region",
            "deployment_class",
            "cloud_provider",
            "cloud_region",
            "instance_or_warehouse",
            "instance_type",
            "warehouse_size",
            "node_count",
            "cluster_size",
            "storage_format",
            "storage_tier",
            "compliance_class",
            "is_ranking_eligible",
            "has_plans",
            "plans_published",
            "has_tuning",
            "bundle_download_url",
        },
        "result_environment": {"result_id", "os", "arch", "cpu_count", "memory_gb", "python"},
        "result_phase_durations": {"result_id", "phase", "duration_s"},
        "query_display_timings": {
            "result_id",
            "query_id",
            "display_ms",
            "sample_count",
            "is_valid_display_timing",
            "timing_exclusion_reason",
        },
        "query_executions": {"result_id", "query_id", "duration_ms", "status", "run_type", "iter", "stream"},
        "benchmark_matrix_cells": {
            "benchmark",
            "scale_factor",
            "phase",
            "result_id",
            "platform_id",
            "query_id",
            "display_ms",
            "is_valid_display_timing",
            "timing_exclusion_reason",
        },
        "benchmark_rankings": {
            "benchmark",
            "scale_factor",
            "phase",
            "result_id",
            "platform_id",
            "platform",
            "short_id",
            "trust_label",
            "tuning_mode",
            "tuning_hash",
            "execution_mode",
            "compliance_class",
            "run_date",
            "is_ranking_eligible",
            "has_display_timing",
            "logical_query_count",
            "valid_query_count",
            "missing_query_count",
            "zero_timing_count",
            "display_exclusion_reason",
            "comparison_exclusion_reason",
            "ranking_exclusion_reason",
            "power_score",
            "display_geomean_ms",
            "sample_geomean_ms",
            "cost_usd",
            "primary_metric",
            "primary_order",
            "rank",
            "total_in_cohort",
            "cohort_ranked_count",
            "cohort_ranking_exclusion_reason",
            "percentile_p50",
            "percentile_p90",
            "percentile_p95",
            "percentile_p99",
            "speedup_vs_best",
            "speedup_vs_slowest_in_cohort",
        },
        "cohort_metadata": {
            "cohort_key",
            "benchmark",
            "scale_factor",
            "phase",
            "cohort_label",
            "cohort_href",
            "platform_count",
            "cohort_ranked_count",
            "cohort_ranking_exclusion_reason",
            "primary_metric",
            "primary_order",
            "platform_id",
            "platform",
            "result_id",
            "has_display_timing",
            "logical_query_count",
            "valid_query_count",
            "missing_query_count",
            "zero_timing_count",
            "display_exclusion_reason",
            "comparison_exclusion_reason",
            "ranking_exclusion_reason",
            "rank",
            "metric_value",
            "speedup_vs_best",
        },
        "meta_leaderboard": {"platform_id", "platform", "avg_rank", "n_cohorts"},
        "short_ids": {"short_id", "result_id"},
    }

    EXPECTED_VIEWS = {
        "result_detail_metrics": {
            "result_id",
            "benchmark",
            "scale_factor",
            "platform",
            "platform_id",
            "driver_version",
            "run_date",
            "power_score",
            "total_duration_s",
            "geomean_ms",
            "display_geomean_ms",
            "query_count",
            "logical_query_count",
            "has_display_timing",
            "valid_query_count",
            "missing_query_count",
            "zero_timing_count",
            "display_exclusion_reason",
            "comparison_exclusion_reason",
            "ranking_exclusion_reason",
            "trust_label",
            "visibility",
            "platform_version",
            "execution_mode",
            "tuning_mode",
            "tuning_hash",
            "test_type",
            "validation_status",
            "cost_usd",
            "normalized_cost_usd",
            "cost_model_version",
            "cost_model_source",
            "cost_scope",
            "cost_status",
            "billing_unit",
            "pricing_region",
            "deployment_class",
            "cloud_provider",
            "cloud_region",
            "instance_or_warehouse",
            "instance_type",
            "warehouse_size",
            "node_count",
            "cluster_size",
            "storage_format",
            "storage_tier",
            "compliance_class",
            "has_plans",
            "plans_published",
            "has_tuning",
            "bundle_download_url",
            "os",
            "arch",
            "cpu_count",
            "memory_gb",
            "python",
        },
        "platform_index_rows": {
            "result_id",
            "benchmark",
            "scale_factor",
            "platform",
            "platform_id",
            "driver_version",
            "run_date",
            "power_score",
            "total_duration_s",
            "geomean_ms",
            "display_geomean_ms",
            "query_count",
            "logical_query_count",
            "has_display_timing",
            "valid_query_count",
            "missing_query_count",
            "zero_timing_count",
            "display_exclusion_reason",
            "comparison_exclusion_reason",
            "ranking_exclusion_reason",
            "trust_label",
            "tuning_mode",
            "execution_mode",
            "compliance_class",
            "cost_usd",
            "normalized_cost_usd",
            "cost_model_version",
            "cost_model_source",
            "cost_scope",
            "cost_status",
            "billing_unit",
            "pricing_region",
            "deployment_class",
            "cloud_provider",
            "cloud_region",
            "instance_or_warehouse",
            "instance_type",
            "warehouse_size",
            "node_count",
            "cluster_size",
            "storage_format",
            "storage_tier",
        },
    }

    @pytest.mark.parametrize("table_name,expected_cols", list(EXPECTED_TABLES.items()))
    def test_table_has_expected_columns(self, db_path: Path, table_name: str, expected_cols: set[str]) -> None:
        with _connect(db_path) as con:
            actual = {row[0] for row in con.execute(f"DESCRIBE {table_name}").fetchall()}
        assert expected_cols.issubset(actual), f"Table {table_name!r} missing columns: {expected_cols - actual}"

    @pytest.mark.parametrize("view_name,expected_cols", list(EXPECTED_VIEWS.items()))
    def test_view_has_expected_columns(self, db_path: Path, view_name: str, expected_cols: set[str]) -> None:
        with _connect(db_path) as con:
            actual = {row[0] for row in con.execute(f"DESCRIBE {view_name}").fetchall()}
        assert expected_cols.issubset(actual), f"View {view_name!r} missing columns: {expected_cols - actual}"

    def test_all_tables_are_queryable(self, db_path: Path) -> None:
        with _connect(db_path) as con:
            for name in self.EXPECTED_TABLES:
                count = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                assert isinstance(count, int), f"SELECT COUNT(*) FROM {name} did not return int"

    def test_all_views_are_queryable(self, db_path: Path) -> None:
        with _connect(db_path) as con:
            for name in self.EXPECTED_VIEWS:
                count = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                assert isinstance(count, int), f"SELECT COUNT(*) FROM {name} did not return int"


# ---------------------------------------------------------------------------
# Source-fidelity tests - raw_copy columns match the committed bundle exactly
# ---------------------------------------------------------------------------


class TestSourceFidelity:
    """raw_copy columns match committed bundle fields verbatim."""

    def _result_row(self, db_path: Path) -> dict:
        with _connect(db_path) as con:
            row = con.execute("SELECT * FROM results LIMIT 1").fetchone()
            description = con.description
            assert description is not None
            assert row is not None
            cols = [d[0] for d in description]
        return dict(zip(cols, row))

    def test_benchmark_matches_bundle(self, db_path: Path) -> None:
        assert self._result_row(db_path)["benchmark"] == "tpch"

    def test_platform_matches_bundle(self, db_path: Path) -> None:
        assert self._result_row(db_path)["platform"] == "duckdb"

    def test_scale_factor_matches_bundle(self, db_path: Path) -> None:
        assert self._result_row(db_path)["scale_factor"] == pytest.approx(0.1)

    def test_run_date_matches_bundle(self, db_path: Path) -> None:
        # run.timestamp "2026-03-15T10:00:00.000000" → "2026-03-15"
        assert self._result_row(db_path)["run_date"] == "2026-03-15"

    def test_query_count_matches_bundle(self, db_path: Path) -> None:
        # MINIMAL_BUNDLE has 2 queries
        assert self._result_row(db_path)["query_count"] == 2
        assert self._result_row(db_path)["logical_query_count"] == 2

    def test_power_score_matches_bundle(self, db_path: Path) -> None:
        # summary.tpc_metrics.power_at_size = 1234.56
        assert self._result_row(db_path)["power_score"] == pytest.approx(1234.56)

    def test_total_duration_s_matches_bundle(self, db_path: Path) -> None:
        # run.total_duration_ms = 45000 → 45.0 s
        assert self._result_row(db_path)["total_duration_s"] == pytest.approx(45.0)

    def test_trust_label_set_correctly(self, db_path: Path) -> None:
        assert self._result_row(db_path)["trust_label"] == "maintainer-run"

    def test_visibility_set_correctly(self, db_path: Path) -> None:
        assert self._result_row(db_path)["visibility"] == "public-curated"

    def test_bundle_download_url_constructed(self, db_path: Path) -> None:
        row = self._result_row(db_path)
        result_id = row["result_id"]
        assert row["bundle_download_url"] == f"/results/data/bundles/{result_id}.json"

    def test_normalized_cost_defaults_to_unavailable(self, db_path: Path) -> None:
        row = self._result_row(db_path)
        assert row["cost_usd"] is None
        assert row["normalized_cost_usd"] is None
        assert row["cost_status"] == "unavailable"
        assert row["cost_scope"] == "compute_only"
        assert row["billing_unit"] == "unknown"
        assert row["pricing_region"] == "unknown"
        assert row["cloud_provider"] is None

    def test_query_executions_count(self, db_path: Path) -> None:
        with _connect(db_path) as con:
            count = con.execute("SELECT COUNT(*) FROM query_executions").fetchone()[0]
        # MINIMAL_BUNDLE has 2 query rows
        assert count == 2

    def test_query_execution_duration_values(self, db_path: Path) -> None:
        with _connect(db_path) as con:
            rows = con.execute("SELECT query_id, duration_ms FROM query_executions ORDER BY query_id").fetchall()
        by_query = {r[0]: r[1] for r in rows}
        assert by_query["Q1"] == pytest.approx(8000.0)
        assert by_query["Q6"] == pytest.approx(4000.0)

    def test_environment_row_populated(self, db_path: Path) -> None:
        with _connect(db_path) as con:
            row = con.execute(
                "SELECT os, arch, cpu_count, memory_gb, python FROM result_environment LIMIT 1"
            ).fetchone()
        assert row is not None
        os_val, arch, cpu_count, memory_gb, python_ver = row
        assert "macOS" in os_val
        assert arch == "arm64"
        assert cpu_count == 10
        assert memory_gb == pytest.approx(32.0)
        assert python_ver == "3.12.0"


# ---------------------------------------------------------------------------
# Parity tests - derived metrics match canonical Python reference computations
# ---------------------------------------------------------------------------


class TestDerivedMetricParity:
    """Derived columns match the canonical Python reference within tolerance."""

    def test_display_geomean_ms_parity(self, db_path: Path) -> None:
        """display_geomean_ms == geometric mean of per-query display_ms medians."""
        with _connect(db_path) as con:
            actual = con.execute("SELECT display_geomean_ms FROM results LIMIT 1").fetchone()[0]
        # Q1=8000, Q6=4000 → geomean = sqrt(8000 * 4000) ≈ 5656.854...
        expected = math.exp((math.log(8000.0) + math.log(4000.0)) / 2)
        assert actual == pytest.approx(expected, rel=1e-9)

    def test_platform_id_is_provenance_stripped_slug(self, db_path: Path) -> None:
        """platform_id is lowercase provenance-stripped slug of platform.name."""
        with _connect(db_path) as con:
            row = con.execute("SELECT platform, platform_id FROM results LIMIT 1").fetchone()
        # bundle platform.name = "duckdb" → platform_id = "duckdb"
        assert row[1] == "duckdb"

    def test_is_ranking_eligible_true_for_maintainer_run(self, db_path: Path) -> None:
        """is_ranking_eligible == True for maintainer-run + public-curated."""
        with _connect(db_path) as con:
            val = con.execute("SELECT is_ranking_eligible FROM results LIMIT 1").fetchone()[0]
        assert val is True

    def test_query_display_timings_parity(self, db_path: Path) -> None:
        """query_display_timings.display_ms matches canonical _query_display_ms."""
        with _connect(db_path) as con:
            rows = con.execute(
                "SELECT query_id, display_ms, sample_count FROM query_display_timings ORDER BY query_id"
            ).fetchall()
        by_query = {r[0]: (r[1], r[2]) for r in rows}
        # Single measurement run → display_ms is the run's ms value, sample_count=1
        assert by_query["Q1"][0] == pytest.approx(8000.0, rel=1e-9)
        assert by_query["Q1"][1] == 1
        assert by_query["Q6"][0] == pytest.approx(4000.0, rel=1e-9)
        assert by_query["Q6"][1] == 1

    def test_benchmark_matrix_cells_match_display_timings(self, db_path: Path) -> None:
        """benchmark_matrix_cells.display_ms == query_display_timings.display_ms."""
        with _connect(db_path) as con:
            cells = con.execute(
                "SELECT bmc.query_id, bmc.display_ms, qdt.display_ms"
                " FROM benchmark_matrix_cells bmc"
                " JOIN query_display_timings qdt"
                "   ON bmc.result_id = qdt.result_id AND bmc.query_id = qdt.query_id"
                " ORDER BY bmc.query_id"
            ).fetchall()
        assert len(cells) == 2
        for query_id, bmc_ms, qdt_ms in cells:
            assert bmc_ms == pytest.approx(qdt_ms, rel=1e-9), (
                f"Matrix cell display_ms != query_display_timings.display_ms for {query_id}"
            )

    def test_benchmark_rankings_rank_1_for_only_platform(self, db_path: Path) -> None:
        """With one platform, rank must be 1 and total_in_cohort must be 1."""
        with _connect(db_path) as con:
            row = con.execute("SELECT rank, total_in_cohort FROM benchmark_rankings LIMIT 1").fetchone()
        assert row is not None
        assert row[0] == 1
        assert row[1] == 1

    def test_result_detail_metrics_view_has_environment(self, db_path: Path) -> None:
        """result_detail_metrics LEFT JOIN includes environment columns."""
        with _connect(db_path) as con:
            row = con.execute("SELECT os, arch, cpu_count FROM result_detail_metrics LIMIT 1").fetchone()
        assert row is not None
        assert "macOS" in (row[0] or "")
        assert row[1] == "arm64"
        assert row[2] == 10


# ---------------------------------------------------------------------------
# G-10: Short-ID uniqueness
# ---------------------------------------------------------------------------


class TestG10ShortIdUniqueness:
    """Every short_id is unique and maps to exactly one result_id."""

    def test_short_ids_table_populated(self, db_path: Path) -> None:
        with _connect(db_path) as con:
            count = con.execute("SELECT COUNT(*) FROM short_ids").fetchone()[0]
        assert count >= 1

    def test_short_id_uniqueness(self, db_path: Path) -> None:
        with _connect(db_path) as con:
            total = con.execute("SELECT COUNT(*) FROM short_ids").fetchone()[0]
            distinct = con.execute("SELECT COUNT(DISTINCT short_id) FROM short_ids").fetchone()[0]
        assert total == distinct, "Duplicate short_ids found"

    def test_result_id_uniqueness(self, db_path: Path) -> None:
        with _connect(db_path) as con:
            total = con.execute("SELECT COUNT(*) FROM short_ids").fetchone()[0]
            distinct = con.execute("SELECT COUNT(DISTINCT result_id) FROM short_ids").fetchone()[0]
        assert total == distinct, "Duplicate result_ids in short_ids table"

    def test_short_id_length_at_least_8(self, db_path: Path) -> None:
        with _connect(db_path) as con:
            min_len = con.execute("SELECT MIN(LENGTH(short_id)) FROM short_ids").fetchone()[0]
        assert min_len is not None and min_len >= 8

    def test_short_ids_cover_all_results(self, db_path: Path) -> None:
        """Every result_id in results has a corresponding short_id."""
        with _connect(db_path) as con:
            missing = con.execute(
                "SELECT COUNT(*) FROM results r"
                " LEFT JOIN short_ids s ON r.result_id = s.result_id"
                " WHERE s.result_id IS NULL"
            ).fetchone()[0]
        assert missing == 0, f"{missing} result(s) have no short_id"


# ---------------------------------------------------------------------------
# G-11: View compliance - views must not contain computed metrics
# ---------------------------------------------------------------------------


class TestG11ViewCompliance:
    """Views only contain bare column references and LEFT JOINs (no aggregation/arithmetic)."""

    def test_result_detail_metrics_row_count_equals_results(self, db_path: Path) -> None:
        """View is a 1:1 projection - row count matches results table."""
        with _connect(db_path) as con:
            view_count = con.execute("SELECT COUNT(*) FROM result_detail_metrics").fetchone()[0]
            table_count = con.execute("SELECT COUNT(*) FROM results").fetchone()[0]
        assert view_count == table_count

    def test_platform_index_rows_count_equals_results(self, db_path: Path) -> None:
        """View is a 1:1 projection - row count matches results table."""
        with _connect(db_path) as con:
            view_count = con.execute("SELECT COUNT(*) FROM platform_index_rows").fetchone()[0]
            table_count = con.execute("SELECT COUNT(*) FROM results").fetchone()[0]
        assert view_count == table_count

    def test_result_detail_metrics_values_match_base_table(self, db_path: Path) -> None:
        """View columns carry the same values as the underlying results table."""
        with _connect(db_path) as con:
            result = con.execute(
                "SELECT v.result_id, v.benchmark, v.display_geomean_ms"
                " FROM result_detail_metrics v"
                " JOIN results r ON v.result_id = r.result_id"
                " WHERE v.benchmark != r.benchmark OR v.display_geomean_ms IS DISTINCT FROM r.display_geomean_ms"
            ).fetchall()
        assert len(result) == 0, "View columns diverge from base table"

    def test_platform_index_rows_values_match_base_table(self, db_path: Path) -> None:
        """View columns carry the same values as the underlying results table."""
        with _connect(db_path) as con:
            result = con.execute(
                "SELECT v.result_id"
                " FROM platform_index_rows v"
                " JOIN results r ON v.result_id = r.result_id"
                " WHERE v.benchmark != r.benchmark OR v.trust_label != r.trust_label"
            ).fetchall()
        assert len(result) == 0, "platform_index_rows columns diverge from base table"


class TestG11ViewProjectionCompliance:
    """sqlglot-driven enumeration: every view projects bare columns or whitelisted passthroughs only."""

    WHITELISTED_FUNCTIONS = {"CAST", "COALESCE", "TRY_CAST"}

    def _iter_views(self, con: duckdb.DuckDBPyConnection) -> list[tuple[str, str]]:
        rows = con.execute(
            "SELECT view_name, sql FROM duckdb_views() WHERE schema_name = 'main' AND internal = FALSE"
        ).fetchall()
        return [(name, sql) for name, sql in rows if sql]

    def test_views_exist_for_enumeration(self, db_path: Path) -> None:
        with _connect(db_path) as con:
            views = self._iter_views(con)
        names = {name for name, _ in views}
        assert "result_detail_metrics" in names
        assert "platform_index_rows" in names

    def test_every_view_projection_is_bare_column_or_whitelisted_passthrough(self, db_path: Path) -> None:
        """Enumerate views, parse each with sqlglot, assert no arithmetic/aggregation/CASE/window."""
        import sqlglot
        from sqlglot import exp

        with _connect(db_path) as con:
            views = self._iter_views(con)

        violations: list[str] = []
        for view_name, view_sql in views:
            tree = sqlglot.parse_one(view_sql, read="duckdb")
            select = tree.find(exp.Select)
            assert select is not None, f"view {view_name!r} has no top-level SELECT"

            for projection in select.expressions:
                node = projection.unalias() if isinstance(projection, exp.Alias) else projection

                if isinstance(node, exp.Column):
                    continue

                if isinstance(node, (exp.Cast, exp.TryCast)):
                    inner = node.this
                    if isinstance(inner, exp.Column):
                        continue
                    violations.append(f"{view_name}.{projection.alias_or_name}: CAST over non-column")
                    continue

                if isinstance(node, exp.Coalesce):
                    args = [node.this, *(node.args.get("expressions") or [])]
                    has_column = any(isinstance(a, exp.Column) for a in args)
                    literals_only = all(isinstance(a, (exp.Column, exp.Literal, exp.Null)) for a in args)
                    if has_column and literals_only:
                        continue
                    violations.append(f"{view_name}.{projection.alias_or_name}: COALESCE over non-literal args")
                    continue

                # Anything else - arithmetic, aggregate, CASE, window, IIF, function call - is a violation.
                kind = type(node).__name__
                violations.append(f"{view_name}.{projection.alias_or_name}: disallowed projection kind {kind}")

            for disallowed in (exp.Window, exp.Case, exp.AggFunc):
                hits = list(select.find_all(disallowed))
                # Allow matches inside subqueries that are themselves views (none expected here).
                for hit in hits:
                    violations.append(f"{view_name}: contains disallowed {disallowed.__name__} node")

        assert not violations, "view projection violations:\n  " + "\n  ".join(violations)


# ---------------------------------------------------------------------------
# Variant preservation: cohort_metadata keeps every publishable variant and
# the Home meta-leaderboard keeps the best rank per platform per cohort.
# Regression coverage for the W2 silent-dedup + platform_agg last-write-wins
# bug, see W8 in explorer-canonical-browser-duckdb-read-model.yaml.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def variant_db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Two-bundle fixture: same platform, same cohort, different tuning modes."""
    import copy
    import json

    tuned = copy.deepcopy(MINIMAL_BUNDLE)
    tuned["run"]["id"] = "run-tuned"
    tuned["config"] = {"tuning_mode": "tuned"}
    for q in tuned["queries"]:
        q["ms"] = q["ms"] / 4.0
    tuned["summary"]["tpc_metrics"]["power_at_size"] = 5000.0

    notuning = copy.deepcopy(MINIMAL_BUNDLE)
    notuning["run"]["id"] = "run-notuning"
    notuning["config"] = {"tuning_mode": "notuning"}

    base = tmp_path_factory.mktemp("variant_pipeline_output")
    data_dir = base / "data"
    bundles_dir = data_dir / "bundles"
    bundles_dir.mkdir(parents=True)
    (bundles_dir / "tuned.json").write_text(json.dumps(tuned), encoding="utf-8")
    (bundles_dir / "notuning.json").write_text(json.dumps(notuning), encoding="utf-8")

    output_dir = base / "out"
    ExplorerPipeline().run(data_dir, output_dir, bundle_url_prefix="/results/data/bundles")
    return output_dir / "results.duckdb"


@pytest.fixture(scope="module")
def tie_db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Three-platform fixture where two rows tie on the primary metric."""
    import copy
    import json

    bundles = []
    for platform, power_score in (("duckdb", 5000.0), ("sqlite", 5000.0), ("polars", 1000.0)):
        bundle = copy.deepcopy(MINIMAL_BUNDLE)
        bundle["run"]["id"] = f"run-{platform}"
        bundle["platform"]["name"] = platform
        bundle["summary"]["tpc_metrics"]["power_at_size"] = power_score
        bundles.append((platform, bundle))

    base = tmp_path_factory.mktemp("tie_pipeline_output")
    data_dir = base / "data"
    bundles_dir = data_dir / "bundles"
    bundles_dir.mkdir(parents=True)
    for platform, bundle in bundles:
        (bundles_dir / f"{platform}.json").write_text(json.dumps(bundle), encoding="utf-8")

    output_dir = base / "out"
    ExplorerPipeline().run(data_dir, output_dir, bundle_url_prefix="/results/data/bundles")
    return output_dir / "results.duckdb"


@pytest.fixture(scope="module")
def eligibility_db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Three-platform fixture where the numerically best row is not ranking-eligible."""
    import copy
    import json

    bundles = []
    for platform, power_score in (("duckdb", 5000.0), ("community", 10000.0), ("sqlite", 1000.0)):
        bundle = copy.deepcopy(MINIMAL_BUNDLE)
        bundle["run"]["id"] = f"run-{platform}"
        bundle["platform"]["name"] = platform
        bundle["summary"]["tpc_metrics"]["power_at_size"] = power_score
        bundles.append((platform, bundle))

    base = tmp_path_factory.mktemp("eligibility_pipeline_output")
    data_dir = base / "data"
    bundles_dir = data_dir / "bundles"
    bundles_dir.mkdir(parents=True)
    for platform, bundle in bundles:
        (bundles_dir / f"{platform}.json").write_text(json.dumps(bundle), encoding="utf-8")
    (bundles_dir / f"community{SUBMISSION_MANIFEST_SUFFIX}").write_text(
        json.dumps({"bundle_file": "community.json"}),
        encoding="utf-8",
    )

    output_dir = base / "out"
    ExplorerPipeline().run(data_dir, output_dir, bundle_url_prefix="/results/data/bundles")
    return output_dir / "results.duckdb"


class TestCohortVariantPreservation:
    def test_cohort_metadata_keeps_all_variants(self, variant_db_path: Path) -> None:
        with _connect(variant_db_path) as con:
            rows = con.execute(
                "SELECT result_id, tuning_mode, rank FROM cohort_metadata"
                " WHERE cohort_key = 'tpch-sf0.1-power' ORDER BY rank"
            ).fetchall()
        assert len(rows) == 2, "cohort_metadata must preserve both publishable variants"
        assert {r[1] for r in rows} == {"tuned", "notuning"}
        assert [r[2] for r in rows] == [1, 2]

    def test_cohort_metadata_carries_short_id_and_trust_label(self, variant_db_path: Path) -> None:
        with _connect(variant_db_path) as con:
            rows = con.execute(
                "SELECT short_id, trust_label FROM cohort_metadata WHERE cohort_key = 'tpch-sf0.1-power'"
            ).fetchall()
        for short_id, trust_label in rows:
            assert short_id, "short_id must be populated on every cohort_metadata row"
            assert trust_label, "trust_label must be populated on every cohort_metadata row"

    def test_cohort_metadata_pk_is_cohort_key_result_id(self, variant_db_path: Path) -> None:
        """Primary key is (cohort_key, result_id), not (cohort_key, platform_id)."""
        with _connect(variant_db_path) as con:
            row = con.execute(
                "SELECT constraint_text FROM duckdb_constraints()"
                " WHERE table_name = 'cohort_metadata' AND constraint_type = 'PRIMARY KEY'"
            ).fetchone()
        assert row is not None, "cohort_metadata must declare a PRIMARY KEY"
        constraint_text = row[0]
        assert "cohort_key" in constraint_text and "result_id" in constraint_text, constraint_text
        assert "platform_id" not in constraint_text, (
            f"platform_id must not be in the PK (would dedupe variants): {constraint_text}"
        )

    def test_meta_leaderboard_keeps_best_rank_per_platform(self, variant_db_path: Path) -> None:
        """Regression: platform_agg must not clobber the better rank with a worse one.

        The tuned variant ranks 1; notuning ranks 2. The Home meta-leaderboard
        summarises a platform with its BEST variant's rank, not its worst.
        """
        with _connect(variant_db_path) as con:
            row = con.execute(
                "SELECT avg_rank, n_cohorts FROM meta_leaderboard WHERE platform_id = 'duckdb'"
            ).fetchone()
        assert row is not None
        avg_rank, n_cohorts = row
        assert math.isclose(avg_rank, 1.0), (
            f"avg_rank must be 1.0 (best variant wins), got {avg_rank} - platform_agg last-write-wins regression"
        )
        assert n_cohorts == 1


class TestBenchmarkRankingTieHandling:
    def test_benchmark_rankings_use_competition_ranking_for_ties(self, tie_db_path: Path) -> None:
        with _connect(tie_db_path) as con:
            rows = con.execute(
                "SELECT platform, rank FROM benchmark_rankings WHERE benchmark = 'tpch' ORDER BY rank, platform"
            ).fetchall()

        assert rows == [("duckdb", 1), ("sqlite", 1), ("polars", 3)]


class TestBenchmarkRankingEligibility:
    def test_benchmark_rankings_exclude_ineligible_rows_from_rank_math(self, eligibility_db_path: Path) -> None:
        with _connect(eligibility_db_path) as con:
            rows = con.execute(
                "SELECT platform, is_ranking_eligible, power_score, rank, total_in_cohort, speedup_vs_best"
                " FROM benchmark_rankings WHERE benchmark = 'tpch'"
                " ORDER BY rank NULLS LAST, platform"
            ).fetchall()

        assert rows == [
            ("duckdb", True, 5000.0, 1, 2, 1.0),
            ("sqlite", True, 1000.0, 2, 2, 0.2),
            ("community", False, 10000.0, None, 2, None),
        ]

    def test_cohort_metadata_uses_ranked_count_but_preserves_ineligible_variant(
        self,
        eligibility_db_path: Path,
    ) -> None:
        with _connect(eligibility_db_path) as con:
            rows = con.execute(
                "SELECT platform, rank, platform_count, metric_value, speedup_vs_best"
                " FROM cohort_metadata WHERE benchmark = 'tpch'"
                " ORDER BY rank NULLS LAST, platform"
            ).fetchall()

        assert rows == [
            ("duckdb", 1, 2, 5000.0, 1.0),
            ("sqlite", 2, 2, 1000.0, 0.2),
            ("community", None, 2, 10000.0, None),
        ]

    def test_meta_leaderboard_omits_platforms_with_no_ranked_cohorts(self, eligibility_db_path: Path) -> None:
        with _connect(eligibility_db_path) as con:
            rows = con.execute("SELECT platform_id, avg_rank, n_cohorts FROM meta_leaderboard").fetchall()

        assert rows == [("duckdb", 1.0, 1), ("sqlite", 2.0, 1)]


# ---------------------------------------------------------------------------
# Speedup-column parity - invokes the canonical Python `compare_math` helpers
# cited in `_project/planning/visible_metrics.yaml` and asserts DuckDB values
# equal the reference within 1e-9 (the tolerance declared in the registry).
# Runs on the variant fixture so best != slowest is exercised.
# ---------------------------------------------------------------------------


class TestBenchmarkRankingSpeedupParity:
    def test_speedup_vs_best_matches_canonical(self, variant_db_path: Path) -> None:
        from benchbox.core.explorer_pipeline.compare_math import speedup_vs_best

        with _connect(variant_db_path) as con:
            rows = con.execute(
                "SELECT tuning_mode, power_score, speedup_vs_best"
                " FROM benchmark_rankings WHERE benchmark = 'tpch'"
                " ORDER BY rank"
            ).fetchall()
        by_tuning = {r[0]: (r[1], r[2]) for r in rows}
        best_val = max(v[0] for v in by_tuning.values())
        for tuning, (power, stored) in by_tuning.items():
            expected = speedup_vs_best(power, best_val, higher_is_better=True)
            assert stored == pytest.approx(expected, abs=1e-9), f"{tuning}: stored={stored} != canonical={expected}"

    def test_speedup_vs_slowest_matches_canonical(self, variant_db_path: Path) -> None:
        from benchbox.core.explorer_pipeline.compare_math import speedup_vs_slowest

        with _connect(variant_db_path) as con:
            rows = con.execute(
                "SELECT tuning_mode, power_score, speedup_vs_slowest_in_cohort"
                " FROM benchmark_rankings WHERE benchmark = 'tpch'"
                " ORDER BY rank"
            ).fetchall()
        by_tuning = {r[0]: (r[1], r[2]) for r in rows}
        slowest_val = min(v[0] for v in by_tuning.values())
        for tuning, (power, stored) in by_tuning.items():
            expected = speedup_vs_slowest(power, slowest_val, higher_is_better=True)
            assert stored == pytest.approx(expected, abs=1e-9), f"{tuning}: stored={stored} != canonical={expected}"

    def test_speedup_vs_best_rank1_equals_one(self, variant_db_path: Path) -> None:
        with _connect(variant_db_path) as con:
            row = con.execute(
                "SELECT speedup_vs_best FROM benchmark_rankings WHERE benchmark = 'tpch' AND rank = 1"
            ).fetchone()
        assert row is not None
        assert row[0] == pytest.approx(1.0, abs=1e-12)

    def test_speedup_vs_slowest_last_rank_equals_one(self, variant_db_path: Path) -> None:
        with _connect(variant_db_path) as con:
            rows = con.execute(
                "SELECT speedup_vs_slowest_in_cohort FROM benchmark_rankings"
                " WHERE benchmark = 'tpch' ORDER BY rank DESC LIMIT 1"
            ).fetchone()
        assert rows is not None
        assert rows[0] == pytest.approx(1.0, abs=1e-12)
