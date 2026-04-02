"""Tests for NYC Taxi benchmark implementation.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import tempfile
from pathlib import Path

import pytest

from benchbox.core.nyctaxi.benchmark import NYCTaxiBenchmark
from benchbox.core.nyctaxi.schema import NYC_TAXI_SCHEMA

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]


class TestBenchmarkInitialization:
    """Tests for benchmark initialization."""

    def test_default_init(self):
        """Should initialize with default values."""
        bm = NYCTaxiBenchmark()
        assert bm.scale_factor == 1.0
        assert bm.year == 2019
        assert bm.months is None

    def test_custom_scale_factor(self):
        """Should accept custom scale factor."""
        bm = NYCTaxiBenchmark(scale_factor=0.5)
        assert bm.scale_factor == 0.5

    def test_invalid_scale_factor(self):
        """Should raise for non-positive scale factor."""
        with pytest.raises(ValueError, match="must be positive"):
            NYCTaxiBenchmark(scale_factor=0)

        with pytest.raises(ValueError, match="must be positive"):
            NYCTaxiBenchmark(scale_factor=-1.0)

    def test_custom_year(self):
        """Should accept custom year."""
        bm = NYCTaxiBenchmark(year=2020)
        assert bm.year == 2020

    def test_custom_months(self):
        """Should accept custom months."""
        bm = NYCTaxiBenchmark(months=[1, 2, 3])
        assert bm.months == [1, 2, 3]

    def test_custom_output_dir(self):
        """Should accept custom output directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bm = NYCTaxiBenchmark(output_dir=tmpdir)
            assert bm.output_dir == Path(tmpdir)

    def test_seed_for_reproducibility(self, seed):
        """Should accept seed for reproducibility."""
        bm = NYCTaxiBenchmark(seed=seed)
        assert bm.seed == seed


class TestGenerateData:
    """Tests for data generation."""

    @pytest.fixture(scope="class")
    def nyc_benchmark_with_data(self):
        """Create benchmark with minimal settings and pre-generated data.

        Class-scoped to avoid redundant data generation (4-5s per call).
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            benchmark = NYCTaxiBenchmark(
                scale_factor=0.01,
                output_dir=tmpdir,
                year=2019,
                months=[1],  # Single month for fast tests
                seed=42,
            )
            paths = benchmark.generate_data()
            yield benchmark, paths

    def test_generate_returns_paths(self, nyc_benchmark_with_data):
        """generate_data should return list of paths."""
        benchmark, paths = nyc_benchmark_with_data
        assert isinstance(paths, list)
        assert len(paths) == 2  # taxi_zones, trips

    def test_generate_creates_files(self, nyc_benchmark_with_data):
        """generate_data should create actual files."""
        benchmark, paths = nyc_benchmark_with_data
        for path in paths:
            assert Path(path).exists()

    def test_tables_populated_after_generate(self, nyc_benchmark_with_data):
        """tables property should be populated after generation."""
        benchmark, paths = nyc_benchmark_with_data
        assert len(benchmark.tables) == 2
        assert "taxi_zones" in benchmark.tables
        assert "trips" in benchmark.tables


class TestGetQueries:
    """Tests for query retrieval."""

    @pytest.fixture
    def nyc_benchmark(self, seed):
        """Create benchmark for query tests."""
        return NYCTaxiBenchmark(
            scale_factor=0.01,
            year=2019,
            seed=seed,
        )

    def test_get_queries_returns_dict(self, nyc_benchmark):
        """get_queries should return dict of queries."""
        queries = nyc_benchmark.get_queries()
        assert isinstance(queries, dict)
        assert len(queries) == 25

    def test_get_queries_accepts_dialect(self, nyc_benchmark):
        """get_queries should accept dialect parameter."""
        queries = nyc_benchmark.get_queries(dialect="duckdb")
        assert isinstance(queries, dict)

    def test_get_query_by_id(self, nyc_benchmark):
        """get_query should return specific query."""
        query = nyc_benchmark.get_query("trips-per-hour")
        assert isinstance(query, str)
        assert "SELECT" in query
        assert "trips" in query

    def test_get_query_with_params(self, nyc_benchmark):
        """get_query should accept parameter overrides."""
        query = nyc_benchmark.get_query("zone-detail", params={"zone_id": 161})
        assert "161" in query

    def test_get_query_unknown_raises(self, nyc_benchmark):
        """get_query should raise for unknown query."""
        with pytest.raises(ValueError):
            nyc_benchmark.get_query("nonexistent")


class TestGetSchema:
    """Tests for schema retrieval."""

    def test_get_schema_returns_dict(self):
        """get_schema should return schema dictionary."""
        bm = NYCTaxiBenchmark()
        schema = bm.get_schema()
        assert schema == NYC_TAXI_SCHEMA

    def test_get_schema_has_all_tables(self):
        """Schema should have all tables."""
        bm = NYCTaxiBenchmark()
        schema = bm.get_schema()
        assert set(schema.keys()) == {"trips", "taxi_zones"}


class TestGetCreateTablesSql:
    """Tests for CREATE TABLE SQL generation."""

    def test_generates_standard_sql(self):
        """Should generate standard SQL."""
        bm = NYCTaxiBenchmark()
        sql = bm.get_create_tables_sql(dialect="standard")
        assert "CREATE TABLE" in sql
        assert "trips" in sql
        assert "taxi_zones" in sql

    def test_generates_duckdb_sql(self):
        """Should generate DuckDB SQL."""
        bm = NYCTaxiBenchmark()
        sql = bm.get_create_tables_sql(dialect="duckdb")
        assert "CREATE TABLE" in sql

    def test_generates_clickhouse_sql(self):
        """Should generate ClickHouse SQL."""
        bm = NYCTaxiBenchmark()
        sql = bm.get_create_tables_sql(dialect="clickhouse")
        assert "ENGINE = MergeTree()" in sql

    def test_generates_postgres_sql(self):
        """Should generate PostgreSQL SQL."""
        bm = NYCTaxiBenchmark()
        sql = bm.get_create_tables_sql(dialect="postgres")
        assert "TIMESTAMPTZ" in sql


class TestGetBenchmarkInfo:
    """Tests for benchmark metadata."""

    def test_info_has_required_fields(self):
        """Info should have required fields."""
        bm = NYCTaxiBenchmark()
        info = bm.get_benchmark_info()

        assert info["name"] == "NYC Taxi OLAP"
        assert "description" in info
        assert "reference" in info
        assert "version" in info

    def test_info_has_scale_info(self):
        """Info should include scale information."""
        bm = NYCTaxiBenchmark(scale_factor=2.0, year=2020, months=[1, 2, 3])
        info = bm.get_benchmark_info()

        assert info["scale_factor"] == 2.0
        assert info["year"] == 2020
        assert info["months"] == [1, 2, 3]

    def test_info_has_query_count(self):
        """Info should include query count."""
        bm = NYCTaxiBenchmark()
        info = bm.get_benchmark_info()

        assert info["num_queries"] == 25
        assert "query_categories" in info
        assert len(info["query_categories"]) > 0

    def test_info_has_tables_list(self):
        """Info should include list of tables."""
        bm = NYCTaxiBenchmark()
        info = bm.get_benchmark_info()

        assert info["tables"] == ["taxi_zones", "trips"]

    def test_info_indicates_real_data(self):
        """Info should indicate real data type."""
        bm = NYCTaxiBenchmark()
        info = bm.get_benchmark_info()

        assert info["data_type"] == "real"


class TestQueryInfo:
    """Tests for query metadata retrieval."""

    def test_get_query_info(self):
        """get_query_info should return query metadata."""
        bm = NYCTaxiBenchmark()
        info = bm.get_query_info("trips-per-hour")

        assert info["id"] == "1"
        assert info["category"] == "temporal"
        assert "description" in info

    def test_get_queries_by_category(self):
        """get_queries_by_category should filter queries."""
        bm = NYCTaxiBenchmark()
        temporal_queries = bm.get_queries_by_category("temporal")

        assert len(temporal_queries) > 0
        for qid in temporal_queries:
            info = bm.get_query_info(qid)
            assert info["category"] == "temporal"


class TestDownloadStats:
    """Tests for download statistics."""

    def test_get_download_stats(self):
        """get_download_stats should return statistics."""
        bm = NYCTaxiBenchmark(
            scale_factor=1.0,
            year=2019,
            months=[1, 2],
        )
        stats = bm.get_download_stats()

        assert stats["scale_factor"] == 1.0
        assert stats["year"] == 2019
        assert stats["months"] == [1, 2]


class TestTopLevelInterface:
    """Tests for the top-level NYCTaxi interface."""

    def test_import_from_benchbox(self):
        """Should be importable from benchbox."""
        from benchbox import NYCTaxi

        assert callable(NYCTaxi)

    def test_nyctaxi_interface(self, seed):
        """NYCTaxi interface should work correctly."""
        from benchbox import NYCTaxi

        with tempfile.TemporaryDirectory() as tmpdir:
            bm = NYCTaxi(
                scale_factor=0.01,
                year=2019,
                months=[1],
                output_dir=tmpdir,
                seed=seed,
            )

            assert bm.year == 2019
            assert bm.get_benchmark_info()["name"] == "NYC Taxi OLAP"

            queries = bm.get_queries()
            assert len(queries) == 25


class TestBenchmarkLoader:
    """Tests for benchmark loader integration."""

    def test_loader_can_load_nyctaxi(self):
        """Benchmark loader should support nyctaxi."""
        from benchbox.core.benchmark_loader import get_benchmark_class

        cls = get_benchmark_class("nyctaxi")
        assert cls.__name__ == "NYCTaxiBenchmark"

    def test_loader_creates_instance(self):
        """Benchmark loader should create working instance."""
        from benchbox.core.benchmark_loader import get_benchmark_instance
        from benchbox.core.schemas import BenchmarkConfig

        config = BenchmarkConfig(
            name="nyctaxi",
            display_name="NYC Taxi",
            scale_factor=0.01,
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
