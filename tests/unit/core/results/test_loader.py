"""Unit tests for result file loading and reconstruction (schema v2.0)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from benchbox.core.results.loader import (
    ResultLoadError,
    UnsupportedSchemaError,
    find_latest_result,
    load_result_file,
    reconstruct_benchmark_results,
)
from benchbox.core.results.models import BenchmarkResults
from benchbox.core.results.schema import build_result_payload
from tests.fixtures.result_dict_fixtures import make_v2_result_dict, write_v2_result_file

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestFindLatestResult:
    """Tests for find_latest_result() function."""

    def test_find_latest_result_empty_directory(self, tmp_path):
        """Test finding latest result in empty directory returns None."""
        result = find_latest_result(tmp_path)
        assert result is None

    def test_find_latest_result_nonexistent_directory(self):
        """Test finding latest result in nonexistent directory returns None."""
        result = find_latest_result(Path("/nonexistent/directory"))
        assert result is None

    def test_find_latest_result_returns_most_recent(self, tmp_path):
        """Test that find_latest_result returns the most recent file."""
        older_result = tmp_path / "result1.json"
        newer_result = tmp_path / "result2.json"

        write_v2_result_file(older_result, version="2.0", timestamp="2025-01-01T10:00:00")
        write_v2_result_file(newer_result, version="2.0", timestamp="2025-01-02T10:00:00")

        result = find_latest_result(tmp_path)
        assert result == newer_result

    def test_find_latest_result_with_benchmark_filter(self, tmp_path):
        """Test filtering by benchmark name."""
        tpch_result = tmp_path / "tpch.json"
        tpcds_result = tmp_path / "tpcds.json"

        write_v2_result_file(tpch_result, version="2.0", timestamp="2025-01-02T10:00:00")
        write_v2_result_file(
            tpcds_result,
            version="2.0",
            benchmark_id="tpcds",
            timestamp="2025-01-01T10:00:00",
        )

        result = find_latest_result(tmp_path, benchmark="tpch")
        assert result == tpch_result

        result = find_latest_result(tmp_path, benchmark="tpcds")
        assert result == tpcds_result

    def test_find_latest_result_with_platform_filter(self, tmp_path):
        """Test filtering by platform name."""
        duckdb_result = tmp_path / "duckdb.json"
        databricks_result = tmp_path / "databricks.json"

        write_v2_result_file(
            duckdb_result,
            version="2.0",
            platform="DuckDB",
            timestamp="2025-01-02T10:00:00",
        )
        write_v2_result_file(
            databricks_result,
            version="2.0",
            platform="Databricks",
            timestamp="2025-01-01T10:00:00",
        )

        result = find_latest_result(tmp_path, platform="duckdb")
        assert result == duckdb_result

        result = find_latest_result(tmp_path, platform="databricks")
        assert result == databricks_result

    def test_find_latest_result_with_both_filters(self, tmp_path):
        """Test filtering by both benchmark and platform."""
        matching_result = tmp_path / "match.json"
        non_matching_result = tmp_path / "nomatch.json"

        write_v2_result_file(
            matching_result,
            version="2.0",
            platform="DuckDB",
            timestamp="2025-01-02T10:00:00",
        )
        write_v2_result_file(
            non_matching_result,
            version="2.0",
            benchmark_id="tpcds",
            platform="Databricks",
            timestamp="2025-01-03T10:00:00",
        )

        result = find_latest_result(tmp_path, benchmark="tpch", platform="duckdb")
        assert result == matching_result

    def test_find_latest_result_skips_corrupted_files(self, tmp_path):
        """Test that corrupted JSON files are skipped gracefully."""
        good_result = tmp_path / "good.json"
        bad_result = tmp_path / "bad.json"

        write_v2_result_file(good_result, version="2.0", timestamp="2025-01-01T10:00:00")

        with open(bad_result, "w", encoding="utf-8") as f:
            f.write("{ invalid json")

        result = find_latest_result(tmp_path)
        assert result == good_result

    def test_find_latest_result_no_matching_filters(self, tmp_path):
        """Test that no match returns None when filters don't match."""
        result_file = tmp_path / "result.json"
        write_v2_result_file(result_file, version="2.0")

        result = find_latest_result(tmp_path, benchmark="nonexistent")
        assert result is None

    def test_find_latest_result_skips_companion_files(self, tmp_path):
        """Test that companion files (.plans.json, .tuning.json) are skipped."""
        result_file = tmp_path / "result.json"
        plans_file = tmp_path / "result.plans.json"
        tuning_file = tmp_path / "result.tuning.json"

        write_v2_result_file(result_file, version="2.0")

        # Write companion files (shouldn't be returned)
        with open(plans_file, "w", encoding="utf-8") as f:
            json.dump({"version": "2.0", "plans_captured": 1}, f)
        with open(tuning_file, "w", encoding="utf-8") as f:
            json.dump({"version": "2.0", "clauses": {}}, f)

        result = find_latest_result(tmp_path)
        assert result == result_file

    def test_find_latest_result_skips_v1_files(self, tmp_path):
        """Test that v1.x schema files are skipped."""
        v2_result = tmp_path / "v2_result.json"
        v1_result = tmp_path / "v1_result.json"

        write_v2_result_file(v2_result, version="2.0", timestamp="2025-01-01T10:00:00")

        # Create a v1.x file (should be skipped)
        v1_data = {
            "schema_version": "1.0",
            "benchmark": {"id": "tpch", "name": "TPC-H"},
            "execution": {"platform": "DuckDB", "timestamp": "2025-01-02T10:00:00"},
        }
        with open(v1_result, "w", encoding="utf-8") as f:
            json.dump(v1_data, f)

        result = find_latest_result(tmp_path)
        assert result == v2_result


class TestLoadResultFile:
    """Tests for load_result_file() function."""

    def test_load_result_file_success(self, tmp_path):
        """Test successfully loading a valid v2.0 result file."""
        result_file = tmp_path / "result.json"
        write_v2_result_file(
            result_file,
            version="2.0",
            platform="DuckDB",
            scale_factor=1.0,
        )

        result, raw_data = load_result_file(result_file)

        assert isinstance(result, BenchmarkResults)
        assert result.benchmark_name == "TPC-H"
        assert result.platform == "DuckDB"
        assert result.scale_factor == 1.0
        assert result.total_queries == 22
        assert raw_data["version"] == "2.0"

    def test_load_result_file_not_found(self):
        """Test loading nonexistent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_result_file(Path("/nonexistent/file.json"))

    def test_load_result_file_invalid_json(self, tmp_path):
        """Test loading invalid JSON raises ResultLoadError."""
        result_file = tmp_path / "invalid.json"

        with open(result_file, "w", encoding="utf-8") as f:
            f.write("{ invalid json")

        with pytest.raises(ResultLoadError, match="Invalid JSON"):
            load_result_file(result_file)

    def test_load_result_file_unsupported_schema_v1(self, tmp_path):
        """Test loading v1.x schema version raises UnsupportedSchemaError."""
        result_file = tmp_path / "old_schema.json"

        data = {
            "schema_version": "1.0",
            "benchmark": {"id": "tpch", "name": "TPC-H"},
            "execution": {"platform": "DuckDB"},
        }

        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(data, f)

        with pytest.raises(UnsupportedSchemaError, match="Unsupported schema version"):
            load_result_file(result_file)

    def test_load_result_file_unsupported_schema_unknown(self, tmp_path):
        """Test loading unknown schema version raises UnsupportedSchemaError."""
        result_file = tmp_path / "future_schema.json"

        data = {
            "version": "3.0",
            "benchmark": {"id": "tpch", "name": "TPC-H"},
        }

        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(data, f)

        with pytest.raises(UnsupportedSchemaError, match="Unsupported schema version"):
            load_result_file(result_file)

    @pytest.mark.parametrize(
        ("version", "message"),
        [
            ("2.99", "runtime loader schema policy"),
            ("2.x", "runtime loader schema policy"),
            (None, "<missing>"),
        ],
    )
    def test_load_result_file_reports_loader_policy_for_unsupported_versions(
        self,
        tmp_path,
        version,
        message,
    ):
        """Unsupported versions should name the strict runtime loader policy."""
        result_file = tmp_path / "unsupported_schema.json"
        data = {
            "benchmark": {"id": "tpch", "name": "TPC-H"},
            "run": {"id": "test", "timestamp": "2026-05-21T00:00:00", "total_duration_ms": 1},
        }
        if version is not None:
            data["version"] = version

        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(data, f)

        with pytest.raises(UnsupportedSchemaError) as exc_info:
            load_result_file(result_file)

        assert message in str(exc_info.value)
        assert "schema versions 2.0 and 2.1" in str(exc_info.value)


class TestReconstructBenchmarkResults:
    """Tests for reconstruct_benchmark_results() function."""

    def test_reconstruct_minimal_result(self):
        """Test reconstructing result with minimal required fields."""
        data = make_v2_result_dict(
            version="2.0",
            benchmark_name="TPC-H Benchmark",
            platform="DuckDB",
            scale_factor=1.0,
            execution_id="test123",
            timestamp="2025-01-01T10:00:00",
            query_time_ms=800,
            total_queries=0,
            passed_queries=0,
            failed_queries=0,
            total_ms=0,
        )

        result = reconstruct_benchmark_results(data)

        assert isinstance(result, BenchmarkResults)
        assert result.benchmark_name == "TPC-H Benchmark"
        assert result.platform == "DuckDB"
        assert result.execution_id == "test123"
        assert result.scale_factor == 1.0

    def test_reconstruct_complete_result(self):
        """Test reconstructing result with all fields populated."""
        data = make_v2_result_dict(
            version="2.0",
            benchmark_name="TPC-H Benchmark",
            platform="DuckDB",
            platform_version="1.0.0",
            scale_factor=10.0,
            execution_id="test123",
            timestamp="2025-01-01T10:00:00",
            total_duration_ms=5000,
            query_time_ms=4000,
            iterations=3,
            total_ms=5000,
            queries=[
                {"id": "1", "ms": 100.0, "rows": 4},
                {"id": "2", "ms": 50.0, "rows": 100},
            ],
        )
        # Add fields not covered by the shared factory
        data["benchmark"]["mode"] = "power_test"
        data["platform"]["variant"] = "in-memory"
        data["summary"]["timing"].update(
            {
                "avg_ms": 227.27,
                "min_ms": 50,
                "max_ms": 500,
                "geometric_mean_ms": 150.5,
            }
        )
        data["summary"]["data"] = {"rows_loaded": 1000000, "load_time_ms": 1000}
        data["summary"]["validation"] = "passed"
        data["summary"]["tpc_metrics"] = {
            "power_at_size": 1234.5,
            "throughput_at_size": 5678.9,
            "qphh_at_size": 9012.3,
        }
        data["environment"] = {
            "os": "Darwin 24.0.0",
            "arch": "arm64",
            "cpu_count": 16,
            "memory_gb": 64,
            "python": "3.12.0",
        }
        data["tables"] = {
            "lineitem": {"rows": 600000, "load_ms": 500},
            "orders": {"rows": 150000, "load_ms": 200},
        }

        result = reconstruct_benchmark_results(data)

        # Core fields
        assert result.benchmark_name == "TPC-H Benchmark"
        assert result.platform == "DuckDB"
        assert result.scale_factor == 10.0
        assert result.execution_id == "test123"

        # Query metrics
        assert result.total_queries == 22
        assert result.successful_queries == 22
        assert result.failed_queries == 0
        assert len(result.query_results) == 2

        # Timing metrics (converted from ms to seconds)
        assert result.total_execution_time == 5.0
        assert abs(result.average_query_time - 0.22727) < 0.0001
        assert result.data_loading_time == 1.0

        # TPC metrics
        assert result.power_at_size == 1234.5
        assert result.throughput_at_size == 5678.9
        assert result.qph_at_size == 9012.3
        # Note: geometric_mean_ms is now in summary.timing, not tpc_metrics
        # The loader extracts it from summary.timing

        # Metadata
        assert result.validation_status == "passed"
        assert result.test_execution_type == "power_test"

    def test_reconstruct_handles_missing_optional_fields(self):
        """Test that reconstruction handles missing optional fields gracefully."""
        data = make_v2_result_dict(
            version="2.0",
            benchmark_id="test",
            benchmark_name="Test Benchmark",
            platform="Test Platform",
            scale_factor=1.0,
            execution_id="",
            timestamp="2025-01-01T10:00:00",
            total_duration_ms=0,
            query_time_ms=0,
            total_queries=0,
            passed_queries=0,
            failed_queries=0,
            total_ms=0,
        )

        result = reconstruct_benchmark_results(data)

        assert result.benchmark_name == "Test Benchmark"
        assert result.platform == "Test Platform"
        assert result.scale_factor == 1.0
        assert result.execution_id == ""
        assert result.total_queries == 0
        assert result.total_execution_time == 0.0

    def test_reconstruct_timestamp_parsing(self):
        """Test that timestamp is properly parsed."""
        data = make_v2_result_dict(
            version="2.0",
            benchmark_id="test",
            benchmark_name="Test",
            platform="Test",
            scale_factor=1.0,
            execution_id="test",
            timestamp="2025-10-28T15:30:45.123456",
            query_time_ms=800,
            total_queries=0,
            passed_queries=0,
            failed_queries=0,
            total_ms=0,
        )

        result = reconstruct_benchmark_results(data)

        assert isinstance(result.timestamp, datetime)
        assert result.timestamp.year == 2025
        assert result.timestamp.month == 10
        assert result.timestamp.day == 28

    def test_round_trip_preserves_values(self):
        """Test that values survive export→import without corruption.

        Note: In v2.0, timing statistics are COMPUTED from query results,
        not stored separately. This test verifies:
        1. Non-computed values (data_loading_time) round-trip correctly
        2. Computed values (total_execution_time, average_query_time) are
           correctly derived from queries in both export and import
        """
        # Create query results that will produce known timing statistics
        # Total: 100 + 200 + 300 + 400 = 1000ms = 1.0s
        # Average: 1000 / 4 = 250ms = 0.25s
        query_results = [
            {"query_id": "1", "execution_time_ms": 100, "rows_returned": 4, "status": "SUCCESS"},
            {"query_id": "2", "execution_time_ms": 200, "rows_returned": 8, "status": "SUCCESS"},
            {"query_id": "3", "execution_time_ms": 300, "rows_returned": 12, "status": "SUCCESS"},
            {"query_id": "4", "execution_time_ms": 400, "rows_returned": 16, "status": "SUCCESS"},
        ]

        original = BenchmarkResults(
            benchmark_name="Test",
            _benchmark_id_override="test",
            platform="Test",
            scale_factor=1.0,
            execution_id="test123",
            timestamp=datetime(2025, 11, 1, 12, 0, 0),
            duration_seconds=10.0,
            total_queries=4,
            successful_queries=4,
            failed_queries=0,
            data_loading_time=1.456,
            query_results=query_results,
        )

        exported = build_result_payload(original)
        reimported = reconstruct_benchmark_results(exported)

        # Verify computed values derived from queries
        # total_ms should be 1000 (sum of query times)
        assert abs(reimported.total_execution_time - 1.0) < 0.01
        # average should be 250ms = 0.25s
        assert abs(reimported.average_query_time - 0.25) < 0.01

        # Verify non-computed values round-trip correctly
        assert abs(reimported.data_loading_time - 1.456) < 0.01

        # Verify geometric mean is computed correctly
        # geometric_mean(100, 200, 300, 400) ≈ 213.4ms
        assert reimported.geometric_mean_execution_time is not None
        assert abs(reimported.geometric_mean_execution_time - 0.2134) < 0.01

    def test_reconstruct_query_results_with_iteration(self):
        """Test that iteration field is properly reconstructed."""
        data = make_v2_result_dict(
            version="2.0",
            benchmark_id="test",
            benchmark_name="Test",
            platform="Test",
            scale_factor=1.0,
            execution_id="test",
            timestamp="2025-01-01T10:00:00",
            query_time_ms=800,
            iterations=3,
            total_queries=3,
            passed_queries=3,
            failed_queries=0,
            total_ms=300,
            queries=[
                {"id": "1", "ms": 100.0, "rows": 4, "iter": 1},
                {"id": "1", "ms": 90.0, "rows": 4, "iter": 2},
                {"id": "1", "ms": 110.0, "rows": 4, "iter": 3},
            ],
        )

        result = reconstruct_benchmark_results(data)

        assert len(result.query_results) == 3
        assert result.query_results[0]["iteration"] == 1
        assert result.query_results[1]["iteration"] == 2
        assert result.query_results[2]["iteration"] == 3

    def test_reconstruct_query_results_with_stream(self):
        """Test that stream field is properly reconstructed."""
        data = make_v2_result_dict(
            version="2.0",
            benchmark_id="test",
            benchmark_name="Test",
            platform="Test",
            scale_factor=1.0,
            execution_id="test",
            timestamp="2025-01-01T10:00:00",
            query_time_ms=800,
            streams=2,
            total_queries=2,
            passed_queries=2,
            failed_queries=0,
            total_ms=200,
            queries=[
                {"id": "1", "ms": 100.0, "rows": 4, "stream": 1},
                {"id": "1", "ms": 90.0, "rows": 4, "stream": 2},
            ],
        )

        result = reconstruct_benchmark_results(data)

        assert len(result.query_results) == 2
        assert result.query_results[0]["stream_id"] == 1
        assert result.query_results[1]["stream_id"] == 2

    def test_reconstruct_query_results_multi_stream_plans_reattach_per_stream(self):
        """A query_id captured in multiple streams is keyed in .plans.json as
        "{query_id}#{test_type}#{stream_id}" (build_plans_payload); the loader
        must resolve each row to its OWN stream's plan, not the other stream's
        or none at all.
        """
        data = make_v2_result_dict(
            version="2.0",
            benchmark_id="test",
            benchmark_name="Test",
            platform="Test",
            scale_factor=1.0,
            execution_id="test",
            timestamp="2025-01-01T10:00:00",
            query_time_ms=200,
            streams=2,
            total_queries=2,
            passed_queries=2,
            failed_queries=0,
            total_ms=200,
            queries=[
                {"id": "1", "ms": 100.0, "rows": 4, "stream": 1, "test_type": "throughput"},
                {"id": "1", "ms": 90.0, "rows": 4, "stream": 2, "test_type": "throughput"},
            ],
        )
        plans_data = {
            "queries": {
                "1#throughput#1": {
                    "fingerprint": "a" * 64,
                    "plan": {"query_id": "1", "platform": "duckdb", "logical_root": None},
                },
                "1#throughput#2": {
                    "fingerprint": "b" * 64,
                    "plan": {"query_id": "1", "platform": "duckdb", "logical_root": None},
                },
            }
        }

        result = reconstruct_benchmark_results(data, plans_data=plans_data)

        assert len(result.query_results) == 2
        assert result.query_results[0]["stream_id"] == 1
        assert result.query_results[0]["plan_fingerprint"] == "a" * 64
        assert result.query_results[1]["stream_id"] == 2
        assert result.query_results[1]["plan_fingerprint"] == "b" * 64

    def test_reconstruct_query_results_power_and_throughput_same_stream_id_not_confused(self):
        """P1 regression: a power row and a throughput row for the same query_id
        can share stream_id (independent counters that legitimately collide).
        test_type must disambiguate them; without it, one phase's plan would
        silently resolve to the other phase's entry.
        """
        data = make_v2_result_dict(
            version="2.0",
            benchmark_id="test",
            benchmark_name="Test",
            platform="Test",
            scale_factor=1.0,
            execution_id="test",
            timestamp="2025-01-01T10:00:00",
            query_time_ms=200,
            total_queries=2,
            passed_queries=2,
            failed_queries=0,
            total_ms=200,
            queries=[
                {"id": "1", "ms": 100.0, "rows": 4, "stream": 0, "test_type": "power"},
                {"id": "1", "ms": 90.0, "rows": 4, "stream": 0, "test_type": "throughput"},
            ],
        )
        plans_data = {
            "queries": {
                "1#power#0": {
                    "fingerprint": "a" * 64,
                    "plan": {"query_id": "1", "platform": "duckdb", "logical_root": None},
                },
                "1#throughput#0": {
                    "fingerprint": "b" * 64,
                    "plan": {"query_id": "1", "platform": "duckdb", "logical_root": None},
                },
            }
        }

        result = reconstruct_benchmark_results(data, plans_data=plans_data)

        assert len(result.query_results) == 2
        power_row, throughput_row = result.query_results
        assert power_row["test_type"] == "power"
        assert power_row["plan_fingerprint"] == "a" * 64
        assert throughput_row["test_type"] == "throughput"
        assert throughput_row["plan_fingerprint"] == "b" * 64

    def test_reconstruct_query_results_single_stream_bare_key_still_works(self):
        """A query_id captured in exactly one stream is keyed bare (no "#stream"
        suffix); this must keep working unchanged (the common case)."""
        data = make_v2_result_dict(
            version="2.0",
            benchmark_id="test",
            benchmark_name="Test",
            platform="Test",
            scale_factor=1.0,
            execution_id="test",
            timestamp="2025-01-01T10:00:00",
            query_time_ms=100,
            total_queries=1,
            passed_queries=1,
            failed_queries=0,
            total_ms=100,
            queries=[{"id": "1", "ms": 100.0, "rows": 4}],
        )
        plans_data = {
            "queries": {
                "1": {"fingerprint": "c" * 64, "plan": {"query_id": "1", "platform": "duckdb", "logical_root": None}},
            }
        }

        result = reconstruct_benchmark_results(data, plans_data=plans_data)

        assert len(result.query_results) == 1
        assert result.query_results[0]["plan_fingerprint"] == "c" * 64

    def test_reconstruct_with_errors(self):
        """Test that errors array is properly reconstructed."""
        data = make_v2_result_dict(
            version="2.0",
            benchmark_id="test",
            benchmark_name="Test",
            platform="Test",
            scale_factor=1.0,
            execution_id="test",
            timestamp="2025-01-01T10:00:00",
            query_time_ms=500,
            total_queries=2,
            passed_queries=1,
            failed_queries=1,
            total_ms=500,
            queries=[
                {"id": "1", "ms": 500.0, "rows": 4},
            ],
            errors=[
                {"phase": "query", "query_id": "2", "type": "QueryError", "message": "Syntax error"},
            ],
        )

        result = reconstruct_benchmark_results(data)

        assert len(result.query_results) == 2
        failed_query = [q for q in result.query_results if q.get("status") == "FAILED"]
        assert len(failed_query) == 1
        assert failed_query[0]["query_id"] == "2"
        assert failed_query[0]["error_type"] == "QueryError"
