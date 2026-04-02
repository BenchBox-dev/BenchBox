"""Tests for AI/ML SQL Function benchmark implementation.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.experimental.aiml_functions import AIMLFunctionsBenchmark
from benchbox.experimental.aiml_functions.benchmark import (
    AIMLBenchmarkResults,
    AIMLQueryResult,
)
from benchbox.experimental.aiml_functions.functions import AIMLFunctionCategory

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestAIMLQueryResult:
    """Tests for AIMLQueryResult dataclass."""

    def test_basic_creation(self):
        """Should create query result."""
        result = AIMLQueryResult(
            query_id="sentiment_single",
            function_id="sentiment_analysis",
            platform="snowflake",
            success=True,
            execution_time_ms=150.5,
        )
        assert result.query_id == "sentiment_single"
        assert result.function_id == "sentiment_analysis"
        assert result.platform == "snowflake"
        assert result.success is True
        assert result.execution_time_ms == 150.5

    def test_failed_result(self):
        """Should create failed result."""
        result = AIMLQueryResult(
            query_id="test",
            function_id="test",
            platform="snowflake",
            success=False,
            execution_time_ms=50.0,
            error_message="Function not available",
        )
        assert result.success is False
        assert result.error_message == "Function not available"

    def test_with_metrics(self):
        """Should include token and cost estimates."""
        result = AIMLQueryResult(
            query_id="test",
            function_id="test",
            platform="snowflake",
            success=True,
            execution_time_ms=100.0,
            row_count=50,
            tokens_estimated=5000,
            cost_estimated=0.05,
        )
        assert result.row_count == 50
        assert result.tokens_estimated == 5000
        assert result.cost_estimated == 0.05

    def test_to_dict(self):
        """Should convert to dictionary."""
        result = AIMLQueryResult(
            query_id="test",
            function_id="sentiment",
            platform="snowflake",
            success=True,
            execution_time_ms=100.0,
            row_count=10,
        )
        d = result.to_dict()
        assert d["query_id"] == "test"
        assert d["function_id"] == "sentiment"
        assert d["platform"] == "snowflake"
        assert d["success"] is True
        assert d["execution_time_ms"] == 100.0
        assert d["row_count"] == 10
        assert "timestamp" in d


class TestAIMLBenchmarkResults:
    """Tests for AIMLBenchmarkResults dataclass."""

    def test_basic_creation(self):
        """Should create benchmark results."""
        from datetime import datetime, timezone

        results = AIMLBenchmarkResults(
            platform="snowflake",
            started_at=datetime.now(timezone.utc),
        )
        assert results.platform == "snowflake"
        assert results.total_queries == 0
        assert results.successful_queries == 0
        assert results.failed_queries == 0

    def test_add_successful_result(self):
        """Should track successful results."""
        from datetime import datetime, timezone

        results = AIMLBenchmarkResults(
            platform="snowflake",
            started_at=datetime.now(timezone.utc),
        )
        results.add_result(
            AIMLQueryResult(
                query_id="q1",
                function_id="f1",
                platform="snowflake",
                success=True,
                execution_time_ms=100.0,
            )
        )
        assert results.total_queries == 1
        assert results.successful_queries == 1
        assert results.failed_queries == 0
        assert results.total_execution_time_ms == 100.0

    def test_add_failed_result(self):
        """Should track failed results."""
        from datetime import datetime, timezone

        results = AIMLBenchmarkResults(
            platform="snowflake",
            started_at=datetime.now(timezone.utc),
        )
        results.add_result(
            AIMLQueryResult(
                query_id="q1",
                function_id="f1",
                platform="snowflake",
                success=False,
                execution_time_ms=50.0,
            )
        )
        assert results.total_queries == 1
        assert results.successful_queries == 0
        assert results.failed_queries == 1

    def test_add_multiple_results(self):
        """Should aggregate multiple results."""
        from datetime import datetime, timezone

        results = AIMLBenchmarkResults(
            platform="snowflake",
            started_at=datetime.now(timezone.utc),
        )
        for i in range(5):
            results.add_result(
                AIMLQueryResult(
                    query_id=f"q{i}",
                    function_id="f",
                    platform="snowflake",
                    success=i % 2 == 0,
                    execution_time_ms=100.0,
                    cost_estimated=0.01,
                )
            )
        assert results.total_queries == 5
        assert results.successful_queries == 3
        assert results.failed_queries == 2
        assert results.total_execution_time_ms == 500.0
        assert results.total_cost_estimated == pytest.approx(0.05)

    def test_complete(self):
        """Should mark results as complete."""
        from datetime import datetime, timezone

        results = AIMLBenchmarkResults(
            platform="snowflake",
            started_at=datetime.now(timezone.utc),
        )
        assert results.completed_at is None
        results.complete()
        assert results.completed_at is not None

    def test_to_dict(self):
        """Should convert to dictionary."""
        from datetime import datetime, timezone

        results = AIMLBenchmarkResults(
            platform="snowflake",
            started_at=datetime.now(timezone.utc),
        )
        results.add_result(
            AIMLQueryResult(
                query_id="q1",
                function_id="f1",
                platform="snowflake",
                success=True,
                execution_time_ms=100.0,
            )
        )
        results.complete()
        d = results.to_dict()
        assert d["platform"] == "snowflake"
        assert d["total_queries"] == 1
        assert d["successful_queries"] == 1
        assert d["success_rate"] == 1.0
        assert d["avg_execution_time_ms"] == 100.0
        assert len(d["query_results"]) == 1


class TestAIMLFunctionsBenchmark:
    """Tests for AIMLFunctionsBenchmark class."""

    @pytest.fixture
    def aiml_benchmark(self):
        """Create benchmark instance."""
        return AIMLFunctionsBenchmark(scale_factor=1.0, seed=42)

    def test_basic_creation(self, aiml_benchmark):
        """Should create benchmark."""
        assert aiml_benchmark.name == "AI/ML SQL Function Performance Testing"
        assert aiml_benchmark.version == "1.0"
        assert aiml_benchmark.scale_factor == 1.0

    def test_supported_platforms(self, aiml_benchmark):
        """Should have supported platforms."""
        platforms = aiml_benchmark.get_supported_platforms()
        assert "snowflake" in platforms
        assert "bigquery" in platforms
        assert "databricks" in platforms

    def test_get_functions(self, aiml_benchmark):
        """Should get all functions."""
        functions = aiml_benchmark.get_functions()
        assert len(functions) > 0
        assert "sentiment_analysis" in functions

    def test_get_functions_for_platform(self, aiml_benchmark):
        """Should get functions for a platform."""
        functions = aiml_benchmark.get_functions_for_platform("snowflake")
        assert len(functions) > 0
        assert any(f["function_id"] == "sentiment_analysis" for f in functions)

    def test_get_queries_for_platform(self, aiml_benchmark):
        """Should get query IDs for a platform."""
        queries = aiml_benchmark.get_queries_for_platform("snowflake")
        assert len(queries) > 0
        assert "sentiment_single" in queries

    def test_get_query(self, aiml_benchmark):
        """Should get query SQL."""
        sql = aiml_benchmark.get_query("sentiment_single", platform="snowflake")
        assert sql is not None
        assert "SNOWFLAKE.CORTEX.SENTIMENT" in sql

    def test_get_query_unknown(self, aiml_benchmark):
        """Should raise for unknown query."""
        with pytest.raises(ValueError, match="Unknown query ID"):
            aiml_benchmark.get_query("unknown_query", platform="snowflake")

    def test_get_query_missing_platform(self, aiml_benchmark):
        """Should raise for missing platform."""
        with pytest.raises(ValueError, match="Platform must be specified"):
            aiml_benchmark.get_query("sentiment_single")

    def test_get_query_unsupported_platform(self, aiml_benchmark):
        """Should raise for unsupported platform."""
        with pytest.raises(ValueError, match="not available for platform"):
            aiml_benchmark.get_query("sentiment_single", platform="mysql")

    def test_get_all_queries(self, aiml_benchmark):
        """Should get all queries."""
        queries = aiml_benchmark.get_all_queries()
        assert len(queries) > 0

    def test_get_all_queries_for_platform(self, aiml_benchmark):
        """Should get all queries for a platform."""
        queries = aiml_benchmark.get_all_queries(platform="snowflake")
        assert len(queries) > 0
        assert all(isinstance(q, str) for q in queries.values())

    def test_get_categories(self, aiml_benchmark):
        """Should get all categories."""
        categories = aiml_benchmark.get_categories()
        assert AIMLFunctionCategory.SENTIMENT in categories
        assert AIMLFunctionCategory.COMPLETION in categories

    def test_export_benchmark_spec(self, aiml_benchmark):
        """Should export benchmark specification."""
        spec = aiml_benchmark.export_benchmark_spec()
        assert spec["name"] == "AI/ML SQL Function Performance Testing"
        assert "supported_platforms" in spec
        assert "categories" in spec
        assert "functions" in spec
        assert "queries" in spec
        assert "data_manifest" in spec


class TestAIMLBenchmarkDataGeneration:
    """Tests for data generation functionality."""

    @pytest.fixture
    def aiml_benchmark(self):
        """Create benchmark instance."""
        return AIMLFunctionsBenchmark(scale_factor=1.0, seed=42)

    def test_generate_data(self, aiml_benchmark, tmp_path):
        """Should generate sample data files."""
        aiml_benchmark.output_dir = tmp_path
        files = aiml_benchmark.generate_data()
        assert "aiml_sample_data" in files
        assert "aiml_long_texts" in files

    def test_generate_data_subset(self, aiml_benchmark, tmp_path):
        """Should generate subset of tables."""
        aiml_benchmark.output_dir = tmp_path
        files = aiml_benchmark.generate_data(tables=["aiml_sample_data"])
        assert "aiml_sample_data" in files
        assert "aiml_long_texts" not in files

    def test_generate_data_invalid_format(self, aiml_benchmark, tmp_path):
        """Should raise for invalid format."""
        aiml_benchmark.output_dir = tmp_path
        with pytest.raises(ValueError, match="Unsupported output format"):
            aiml_benchmark.generate_data(output_format="parquet")


class TestAIMLBenchmarkScaling:
    """Tests for scale factor handling."""

    def test_scale_factor_1(self):
        """Should have 100 samples at SF1."""
        bm = AIMLFunctionsBenchmark(scale_factor=1.0)
        assert bm.data_generator.num_samples == 100

    def test_scale_factor_0_1(self):
        """Should scale down samples."""
        bm = AIMLFunctionsBenchmark(scale_factor=0.1)
        assert bm.data_generator.num_samples == 10

    def test_scale_factor_minimum(self):
        """Should have minimum samples."""
        bm = AIMLFunctionsBenchmark(scale_factor=0.01)
        assert bm.data_generator.num_samples >= 10

    def test_scale_factor_10(self):
        """Should scale up samples."""
        bm = AIMLFunctionsBenchmark(scale_factor=10)
        assert bm.data_generator.num_samples == 1000


class TestAIMLBenchmarkQueryCoverage:
    """Tests for query coverage across platforms."""

    @pytest.fixture
    def aiml_benchmark(self):
        """Create benchmark instance."""
        return AIMLFunctionsBenchmark()

    def test_snowflake_query_coverage(self, aiml_benchmark):
        """Should have comprehensive Snowflake queries."""
        queries = aiml_benchmark.get_queries_for_platform("snowflake")
        assert len(queries) >= 10
        assert "sentiment_single" in queries
        assert "completion_simple" in queries
        assert "embedding_single" in queries

    def test_databricks_query_coverage(self, aiml_benchmark):
        """Should have Databricks queries."""
        queries = aiml_benchmark.get_queries_for_platform("databricks")
        assert len(queries) >= 5
        assert "sentiment_single" in queries

    def test_bigquery_query_coverage(self, aiml_benchmark):
        """Should have BigQuery queries."""
        queries = aiml_benchmark.get_queries_for_platform("bigquery")
        assert len(queries) >= 2

    def test_query_sql_validity(self, aiml_benchmark):
        """All queries should produce valid SQL strings."""
        for platform in ["snowflake", "databricks", "bigquery"]:
            queries = aiml_benchmark.get_queries_for_platform(platform)
            for query_id in queries:
                sql = aiml_benchmark.get_query(query_id, platform=platform)
                assert isinstance(sql, str)
                assert len(sql) > 0
                assert "SELECT" in sql.upper() or "WITH" in sql.upper()


class TestAIMLBenchmarkIntegration:
    """Integration tests for the benchmark (no actual DB connection)."""

    @pytest.fixture
    def aiml_benchmark(self):
        """Create benchmark instance."""
        return AIMLFunctionsBenchmark(scale_factor=1.0, seed=42)

    def test_full_spec_export(self, aiml_benchmark):
        """Should export complete benchmark spec."""
        spec = aiml_benchmark.export_benchmark_spec()

        # Verify structure
        assert "name" in spec
        assert "version" in spec
        assert "supported_platforms" in spec
        assert "categories" in spec
        assert "functions" in spec
        assert "queries" in spec
        assert "data_manifest" in spec

        # Verify content
        assert len(spec["supported_platforms"]) >= 3
        assert len(spec["categories"]) >= 5
        assert len(spec["functions"]["functions"]) >= 7
        assert len(spec["queries"]) >= 10
        assert spec["data_manifest"]["tables"]["aiml_sample_data"]["row_count"] >= 100
