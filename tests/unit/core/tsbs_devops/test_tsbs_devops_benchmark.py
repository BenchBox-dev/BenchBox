"""Tests for TSBS DevOps benchmark implementation.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import tempfile
from pathlib import Path

import pytest

from benchbox.core.tsbs_devops.benchmark import TSBSDevOpsBenchmark
from benchbox.core.tsbs_devops.schema import TSBS_DEVOPS_SCHEMA

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestBenchmarkInitialization:
    """Tests for benchmark initialization."""

    def test_default_init(self):
        """Should initialize with default values."""
        benchmark = TSBSDevOpsBenchmark()
        assert benchmark.scale_factor == 1.0
        assert benchmark.num_hosts == 100
        assert benchmark.duration_days == 1
        assert benchmark.interval_seconds == 10

    def test_custom_scale_factor(self):
        """Should accept custom scale factor."""
        benchmark = TSBSDevOpsBenchmark(scale_factor=0.5)
        assert benchmark.scale_factor == 0.5
        assert benchmark.num_hosts == 50

    def test_invalid_scale_factor(self):
        """Should raise for non-positive scale factor."""
        with pytest.raises(ValueError, match="must be positive"):
            TSBSDevOpsBenchmark(scale_factor=0)

        with pytest.raises(ValueError, match="must be positive"):
            TSBSDevOpsBenchmark(scale_factor=-1.0)

    def test_custom_num_hosts(self):
        """Should accept custom number of hosts."""
        benchmark = TSBSDevOpsBenchmark(num_hosts=50)
        assert benchmark.num_hosts == 50

    def test_custom_duration(self):
        """Should accept custom duration."""
        benchmark = TSBSDevOpsBenchmark(duration_days=7)
        assert benchmark.duration_days == 7

    def test_custom_interval(self):
        """Should accept custom interval."""
        benchmark = TSBSDevOpsBenchmark(interval_seconds=60)
        assert benchmark.interval_seconds == 60

    def test_custom_output_dir(self):
        """Should accept custom output directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            benchmark = TSBSDevOpsBenchmark(output_dir=tmpdir)
            assert benchmark.output_dir == Path(tmpdir)

    def test_seed_for_reproducibility(self, seed):
        """Should accept seed for reproducibility."""
        benchmark = TSBSDevOpsBenchmark(seed=seed)
        assert benchmark.seed == seed


class TestGenerateData:
    """Tests for data generation."""

    @pytest.fixture
    def tsbs_benchmark(self, seed, start_time):
        """Create benchmark with minimal settings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield TSBSDevOpsBenchmark(
                num_hosts=3,
                duration_days=1,
                interval_seconds=3600,
                output_dir=tmpdir,
                start_time=start_time,
                seed=seed,
            )

    def test_generate_returns_paths(self, tsbs_benchmark):
        """generate_data should return list of paths."""
        paths = tsbs_benchmark.generate_data()
        assert isinstance(paths, list)
        assert len(paths) == 5  # tags, cpu, mem, disk, net

    def test_generate_creates_files(self, tsbs_benchmark):
        """generate_data should create actual files."""
        paths = tsbs_benchmark.generate_data()
        for path in paths:
            assert Path(path).exists()

    def test_tables_populated_after_generate(self, tsbs_benchmark):
        """tables property should be populated after generation."""
        tsbs_benchmark.generate_data()
        assert len(tsbs_benchmark.tables) == 5
        assert "cpu" in tsbs_benchmark.tables
        assert "mem" in tsbs_benchmark.tables


class TestGetQueries:
    """Tests for query retrieval."""

    @pytest.fixture
    def tsbs_benchmark(self, seed, start_time):
        """Create benchmark for query tests."""
        return TSBSDevOpsBenchmark(
            num_hosts=100,
            start_time=start_time,
            seed=seed,
        )

    def test_get_queries_returns_dict(self, tsbs_benchmark):
        """get_queries should return dict of queries."""
        queries = tsbs_benchmark.get_queries()
        assert isinstance(queries, dict)
        assert len(queries) == 18

    def test_get_queries_accepts_dialect(self, tsbs_benchmark):
        """get_queries should accept dialect parameter."""
        queries = tsbs_benchmark.get_queries(dialect="duckdb")
        assert isinstance(queries, dict)

    def test_get_query_by_id(self, tsbs_benchmark):
        """get_query should return specific query."""
        query = tsbs_benchmark.get_query("single-host-12-hr")
        assert isinstance(query, str)
        assert "SELECT" in query
        assert "cpu" in query

    def test_get_query_with_params(self, tsbs_benchmark):
        """get_query should accept parameter overrides."""
        query = tsbs_benchmark.get_query("single-host-12-hr", params={"hostname": "test_host"})
        assert "test_host" in query

    def test_get_query_unknown_raises(self, tsbs_benchmark):
        """get_query should raise for unknown query."""
        with pytest.raises(ValueError):
            tsbs_benchmark.get_query("nonexistent")


class TestGetSchema:
    """Tests for schema retrieval."""

    def test_get_schema_returns_dict(self):
        """get_schema should return schema dictionary."""
        benchmark = TSBSDevOpsBenchmark()
        schema = benchmark.get_schema()
        assert schema == TSBS_DEVOPS_SCHEMA

    def test_get_schema_has_all_tables(self):
        """Schema should have all tables."""
        benchmark = TSBSDevOpsBenchmark()
        schema = benchmark.get_schema()
        assert set(schema.keys()) == {"tags", "cpu", "mem", "disk", "net"}


class TestGetCreateTablesSql:
    """Tests for CREATE TABLE SQL generation."""

    def test_generates_standard_sql(self):
        """Should generate standard SQL."""
        benchmark = TSBSDevOpsBenchmark()
        sql = benchmark.get_create_tables_sql(dialect="standard")
        assert "CREATE TABLE" in sql
        assert "tags" in sql
        assert "cpu" in sql

    def test_generates_duckdb_sql(self):
        """Should generate DuckDB SQL."""
        benchmark = TSBSDevOpsBenchmark()
        sql = benchmark.get_create_tables_sql(dialect="duckdb")
        assert "CREATE TABLE" in sql

    def test_generates_clickhouse_sql(self):
        """Should generate ClickHouse SQL."""
        benchmark = TSBSDevOpsBenchmark()
        sql = benchmark.get_create_tables_sql(dialect="clickhouse")
        assert "ENGINE = MergeTree()" in sql

    def test_generates_timescale_sql(self):
        """Should generate TimescaleDB SQL."""
        benchmark = TSBSDevOpsBenchmark()
        sql = benchmark.get_create_tables_sql(dialect="timescale")
        assert "create_hypertable" in sql


class TestGetBenchmarkInfo:
    """Tests for benchmark metadata."""

    def test_info_has_required_fields(self):
        """Info should have required fields."""
        benchmark = TSBSDevOpsBenchmark()
        info = benchmark.get_benchmark_info()

        assert info["name"] == "TSBS DevOps"
        assert "description" in info
        assert "reference" in info
        assert "version" in info

    def test_info_has_scale_info(self):
        """Info should include scale information."""
        benchmark = TSBSDevOpsBenchmark(scale_factor=2.0, num_hosts=50, duration_days=3)
        info = benchmark.get_benchmark_info()

        assert info["scale_factor"] == 2.0
        assert info["num_hosts"] == 50
        assert info["duration_days"] == 3

    def test_info_has_query_count(self):
        """Info should include query count."""
        benchmark = TSBSDevOpsBenchmark()
        info = benchmark.get_benchmark_info()

        assert info["num_queries"] == 18
        assert "query_categories" in info
        assert len(info["query_categories"]) > 0

    def test_info_has_tables_list(self):
        """Info should include list of tables."""
        benchmark = TSBSDevOpsBenchmark()
        info = benchmark.get_benchmark_info()

        assert info["tables"] == ["tags", "cpu", "mem", "disk", "net"]

    def test_info_has_metric_descriptions(self):
        """Info should describe metrics."""
        benchmark = TSBSDevOpsBenchmark()
        info = benchmark.get_benchmark_info()

        assert "metrics" in info
        assert "cpu" in info["metrics"]
        assert "mem" in info["metrics"]


class TestQueryInfo:
    """Tests for query metadata retrieval."""

    def test_get_query_info(self):
        """get_query_info should return query metadata."""
        benchmark = TSBSDevOpsBenchmark()
        info = benchmark.get_query_info("single-host-12-hr")

        assert info["id"] == "1"
        assert info["category"] == "single-host"
        assert "description" in info

    def test_get_queries_by_category(self):
        """get_queries_by_category should filter queries."""
        benchmark = TSBSDevOpsBenchmark()
        threshold_queries = benchmark.get_queries_by_category("threshold")

        assert len(threshold_queries) > 0
        for qid in threshold_queries:
            info = benchmark.get_query_info(qid)
            assert info["category"] == "threshold"


class TestGenerationStats:
    """Tests for generation statistics."""

    def test_get_generation_stats(self):
        """get_generation_stats should return statistics."""
        benchmark = TSBSDevOpsBenchmark(
            num_hosts=10,
            duration_days=1,
            interval_seconds=3600,
        )
        stats = benchmark.get_generation_stats()

        assert stats["num_hosts"] == 10
        assert stats["duration_days"] == 1
        assert stats["interval_seconds"] == 3600
        assert "rows" in stats
        assert "total_rows" in stats


class TestTopLevelInterface:
    """Tests for the top-level TSBSDevOps interface."""

    def test_import_from_benchbox(self):
        """Should be importable from benchbox."""
        from benchbox import TSBSDevOps

        assert callable(TSBSDevOps)

    def test_tsbs_devops_interface(self, seed, start_time):
        """TSBSDevOps interface should work correctly."""
        from benchbox import TSBSDevOps

        with tempfile.TemporaryDirectory() as tmpdir:
            benchmark = TSBSDevOps(
                scale_factor=0.1,
                num_hosts=5,
                output_dir=tmpdir,
                start_time=start_time,
                seed=seed,
            )

            assert benchmark.num_hosts == 5
            assert benchmark.get_benchmark_info()["name"] == "TSBS DevOps"

            queries = benchmark.get_queries()
            assert len(queries) == 18

    def test_tsbs_devops_data_generation(self, seed, start_time):
        """TSBSDevOps should generate data correctly."""
        from benchbox import TSBSDevOps

        with tempfile.TemporaryDirectory() as tmpdir:
            benchmark = TSBSDevOps(
                num_hosts=3,
                duration_days=1,
                interval_seconds=3600,
                output_dir=tmpdir,
                start_time=start_time,
                seed=seed,
            )

            paths = benchmark.generate_data()
            assert len(paths) == 5

            # Check tables property
            assert "cpu" in benchmark.tables
            assert "mem" in benchmark.tables


class TestBenchmarkLoader:
    """Tests for benchmark loader integration."""

    def test_loader_can_load_tsbs_devops(self):
        """Benchmark loader should support tsbs_devops."""
        from benchbox.core.benchmark_loader import get_benchmark_class

        cls = get_benchmark_class("tsbs_devops")
        assert cls.__name__ == "TSBSDevOpsBenchmark"

    def test_loader_creates_instance(self):
        """Benchmark loader should create working instance."""
        from benchbox.core.benchmark_loader import get_benchmark_instance
        from benchbox.core.schemas import BenchmarkConfig

        config = BenchmarkConfig(
            name="tsbs_devops",
            display_name="TSBS DevOps",
            scale_factor=0.1,
        )
        instance = get_benchmark_instance(config, system_profile=None)

        assert instance is not None
        assert hasattr(instance, "generate_data")
        assert hasattr(instance, "get_queries")
        assert hasattr(instance, "create_enhanced_benchmark_result")
        assert hasattr(instance, "create_minimal_benchmark_result")
        assert hasattr(instance, "validate_preflight")
        assert hasattr(instance, "validate_manifest")
        assert hasattr(instance, "validate_loaded_data")
