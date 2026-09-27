"""Unit tests for TPCHavoc wrapper class.

Tests for:
- TPCHavoc initialization and validation
- Query ID validation
- Variant ID validation
- Parameter validation
- Method delegation to implementation

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from benchbox.sql_compat.rules.execution_filter.cloud_tpchavoc import CLOUD_TPCHAVOC_SKIPS
from benchbox.tpchavoc import TPCHavoc

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestTPCHavocInit:
    """Tests for TPCHavoc initialization."""

    def test_default_initialization(self, tmp_path):
        """Test TPCHavoc initializes with defaults."""
        with patch("benchbox.tpchavoc.TPCHavocBenchmark") as mock_impl:
            havoc = TPCHavoc(scale_factor=1.0, output_dir=tmp_path)

            assert havoc.scale_factor == 1.0
            mock_impl.assert_called_once()

    def test_custom_scale_factor(self, tmp_path):
        """Test TPCHavoc with custom scale factor."""
        with patch("benchbox.tpchavoc.TPCHavocBenchmark"):
            havoc = TPCHavoc(scale_factor=10.0, output_dir=tmp_path)

            assert havoc.scale_factor == 10.0

    def test_invalid_scale_factor_type(self, tmp_path):
        """Test that non-numeric scale_factor raises TypeError."""
        with pytest.raises(TypeError, match="scale_factor must be a number"):
            TPCHavoc(scale_factor="invalid", output_dir=tmp_path)

    def test_invalid_scale_factor_zero(self, tmp_path):
        """Test that zero scale_factor raises ValueError."""
        with pytest.raises(ValueError, match="scale_factor must be positive"):
            TPCHavoc(scale_factor=0, output_dir=tmp_path)

    def test_invalid_scale_factor_negative(self, tmp_path):
        """Test that negative scale_factor raises ValueError."""
        with pytest.raises(ValueError, match="scale_factor must be positive"):
            TPCHavoc(scale_factor=-1.0, output_dir=tmp_path)


class TestGetQuery:
    """Tests for get_query method."""

    @pytest.fixture
    def havoc(self, tmp_path):
        """Create a TPCHavoc instance for testing."""
        with patch("benchbox.tpchavoc.TPCHavocBenchmark"):
            return TPCHavoc(scale_factor=1.0, output_dir=tmp_path)

    def test_get_query_valid_int(self, havoc):
        """Test get_query with valid integer ID."""
        havoc._impl.get_query.return_value = "SELECT * FROM orders"

        result = havoc.get_query(1)

        assert result == "SELECT * FROM orders"
        havoc._impl.get_query.assert_called_once()

    def test_get_query_valid_string(self, havoc):
        """Test get_query with valid variant string ID."""
        havoc._impl.get_query.return_value = "SELECT * FROM orders"

        result = havoc.get_query("1_v1")

        assert result == "SELECT * FROM orders"

    def test_get_query_invalid_int_low(self, havoc):
        """Test get_query rejects query ID below 1."""
        with pytest.raises(ValueError, match="Query ID must be 1-22"):
            havoc.get_query(0)

    def test_get_query_invalid_int_high(self, havoc):
        """Test get_query rejects query ID above 22."""
        with pytest.raises(ValueError, match="Query ID must be 1-22"):
            havoc.get_query(23)

    def test_get_query_invalid_string_format(self, havoc):
        """Test get_query rejects invalid string format."""
        with pytest.raises(ValueError, match="must be in format"):
            havoc.get_query("invalid")

    def test_get_query_invalid_type(self, havoc):
        """Test get_query rejects invalid types."""
        with pytest.raises(TypeError, match="query_id must be an integer or string"):
            havoc.get_query([1])

    def test_get_query_with_invalid_scale_factor_type(self, havoc):
        """Test get_query validates scale_factor type."""
        with pytest.raises(TypeError, match="scale_factor must be a number"):
            havoc.get_query(1, scale_factor="invalid")

    def test_get_query_with_invalid_scale_factor_value(self, havoc):
        """Test get_query validates scale_factor value."""
        with pytest.raises(ValueError, match="scale_factor must be positive"):
            havoc.get_query(1, scale_factor=-1.0)

    def test_get_query_with_invalid_seed_type(self, havoc):
        """Test get_query validates seed type."""
        with pytest.raises(TypeError, match="seed must be an integer"):
            havoc.get_query(1, seed="invalid")

    def test_get_query_forwards_dialect(self, havoc):
        """Test get_query forwards dialect and base_dialect to implementation."""
        havoc._impl.get_query.return_value = "SELECT"

        havoc.get_query(1, dialect="bigquery", base_dialect="netezza")

        havoc._impl.get_query.assert_called_once_with(
            1, seed=None, scale_factor=None, dialect="bigquery", base_dialect="netezza"
        )

    def test_get_query_dialect_defaults_to_none(self, havoc):
        """Test get_query forwards None dialects without breaking existing callers."""
        havoc._impl.get_query.return_value = "SELECT"

        havoc.get_query(1)

        havoc._impl.get_query.assert_called_once_with(1, seed=None, scale_factor=None, dialect=None, base_dialect=None)


class TestGetPlatformSkipQueries:
    """Tests for get_platform_skip_queries delegation."""

    @pytest.fixture
    def havoc(self, tmp_path):
        """Create a TPCHavoc instance for testing."""
        with patch("benchbox.tpchavoc.TPCHavocBenchmark"):
            return TPCHavoc(scale_factor=1.0, output_dir=tmp_path)

    def test_delegates_to_impl(self, havoc):
        """Test platform skips delegate to the implementation."""
        havoc._impl.get_platform_skip_queries.return_value = ["1_v6"]

        result = havoc.get_platform_skip_queries("bigquery")

        assert result == ["1_v6"]
        havoc._impl.get_platform_skip_queries.assert_called_once_with("bigquery")

    def test_cloud_and_unknown_platforms_through_facade(self, tmp_path):
        """Test the facade exposes real cloud skips and [] for unknown platforms."""
        havoc = TPCHavoc(scale_factor=0.1, output_dir=tmp_path)

        assert set(havoc.get_platform_skip_queries("bigquery")) == set(CLOUD_TPCHAVOC_SKIPS["bigquery"])
        assert havoc.get_platform_skip_queries("unknown-platform") == []


class TestGetQueryVariant:
    """Tests for get_query_variant method."""

    @pytest.fixture
    def havoc(self, tmp_path):
        """Create a TPCHavoc instance for testing."""
        with patch("benchbox.tpchavoc.TPCHavocBenchmark"):
            return TPCHavoc(scale_factor=1.0, output_dir=tmp_path)

    def test_get_query_variant_valid(self, havoc):
        """Test get_query_variant with valid IDs."""
        havoc._impl.get_query_variant.return_value = "SELECT variant FROM orders"

        result = havoc.get_query_variant(1, 1)

        assert result == "SELECT variant FROM orders"
        havoc._impl.get_query_variant.assert_called_once_with(1, 1, None)

    def test_get_query_variant_with_params(self, havoc):
        """Test get_query_variant with params."""
        havoc._impl.get_query_variant.return_value = "SELECT * FROM orders"
        params = {"date": "1998-01-01"}

        havoc.get_query_variant(1, 1, params=params)

        havoc._impl.get_query_variant.assert_called_once_with(1, 1, params)

    def test_get_query_variant_invalid_query_id_type(self, havoc):
        """Test get_query_variant rejects non-integer query_id."""
        with pytest.raises(TypeError, match="query_id must be an integer"):
            havoc.get_query_variant("1", 1)

    def test_get_query_variant_invalid_variant_id_type(self, havoc):
        """Test get_query_variant rejects non-integer variant_id."""
        with pytest.raises(TypeError, match="variant_id must be an integer"):
            havoc.get_query_variant(1, "1")

    def test_get_query_variant_query_id_low(self, havoc):
        """Test get_query_variant rejects query_id below 1."""
        with pytest.raises(ValueError, match="Query ID must be 1-22"):
            havoc.get_query_variant(0, 1)

    def test_get_query_variant_query_id_high(self, havoc):
        """Test get_query_variant rejects query_id above 22."""
        with pytest.raises(ValueError, match="Query ID must be 1-22"):
            havoc.get_query_variant(23, 1)

    def test_get_query_variant_variant_id_low(self, havoc):
        """Test get_query_variant rejects variant_id below 1."""
        with pytest.raises(ValueError, match="Variant ID must be 1-10"):
            havoc.get_query_variant(1, 0)

    def test_get_query_variant_variant_id_high(self, havoc):
        """Test get_query_variant rejects variant_id above 10."""
        with pytest.raises(ValueError, match="Variant ID must be 1-10"):
            havoc.get_query_variant(1, 11)


class TestGetAllVariants:
    """Tests for get_all_variants method."""

    @pytest.fixture
    def havoc(self, tmp_path):
        """Create a TPCHavoc instance for testing."""
        with patch("benchbox.tpchavoc.TPCHavocBenchmark"):
            return TPCHavoc(scale_factor=1.0, output_dir=tmp_path)

    def test_get_all_variants_valid(self, havoc):
        """Test get_all_variants with valid query_id."""
        havoc._impl.get_all_variants.return_value = {1: "SQL1", 2: "SQL2"}

        result = havoc.get_all_variants(1)

        assert result == {1: "SQL1", 2: "SQL2"}
        havoc._impl.get_all_variants.assert_called_once_with(1)

    def test_get_all_variants_invalid_type(self, havoc):
        """Test get_all_variants rejects non-integer query_id."""
        with pytest.raises(TypeError, match="query_id must be an integer"):
            havoc.get_all_variants("1")

    def test_get_all_variants_query_id_low(self, havoc):
        """Test get_all_variants rejects query_id below 1."""
        with pytest.raises(ValueError, match="Query ID must be 1-22"):
            havoc.get_all_variants(0)

    def test_get_all_variants_query_id_high(self, havoc):
        """Test get_all_variants rejects query_id above 22."""
        with pytest.raises(ValueError, match="Query ID must be 1-22"):
            havoc.get_all_variants(23)


class TestGetVariantDescription:
    """Tests for get_variant_description method."""

    @pytest.fixture
    def havoc(self, tmp_path):
        """Create a TPCHavoc instance for testing."""
        with patch("benchbox.tpchavoc.TPCHavocBenchmark"):
            return TPCHavoc(scale_factor=1.0, output_dir=tmp_path)

    def test_get_variant_description_valid(self, havoc):
        """Test get_variant_description with valid IDs."""
        havoc._impl.get_variant_description.return_value = "Join order permutation"

        result = havoc.get_variant_description(1, 1)

        assert result == "Join order permutation"
        havoc._impl.get_variant_description.assert_called_once_with(1, 1)

    def test_get_variant_description_invalid_query_id_type(self, havoc):
        """Test get_variant_description rejects non-integer query_id."""
        with pytest.raises(TypeError, match="query_id must be an integer"):
            havoc.get_variant_description("1", 1)

    def test_get_variant_description_invalid_variant_id_type(self, havoc):
        """Test get_variant_description rejects non-integer variant_id."""
        with pytest.raises(TypeError, match="variant_id must be an integer"):
            havoc.get_variant_description(1, "1")

    def test_get_variant_description_query_id_low(self, havoc):
        """Test get_variant_description rejects query_id below 1."""
        with pytest.raises(ValueError, match="Query ID must be 1-22"):
            havoc.get_variant_description(0, 1)

    def test_get_variant_description_variant_id_low(self, havoc):
        """Test get_variant_description rejects variant_id below 1."""
        with pytest.raises(ValueError, match="Variant ID must be 1-10"):
            havoc.get_variant_description(1, 0)


class TestGetAllVariantsInfo:
    """Tests for get_all_variants_info method."""

    @pytest.fixture
    def havoc(self, tmp_path):
        """Create a TPCHavoc instance for testing."""
        with patch("benchbox.tpchavoc.TPCHavocBenchmark"):
            return TPCHavoc(scale_factor=1.0, output_dir=tmp_path)

    def test_get_all_variants_info_valid(self, havoc):
        """Test get_all_variants_info with valid query_id."""
        havoc._impl.get_all_variants_info.return_value = {1: {"sql": "SELECT", "desc": "Test"}}

        result = havoc.get_all_variants_info(1)

        assert result == {1: {"sql": "SELECT", "desc": "Test"}}
        havoc._impl.get_all_variants_info.assert_called_once_with(1)

    def test_get_all_variants_info_invalid_type(self, havoc):
        """Test get_all_variants_info rejects non-integer query_id."""
        with pytest.raises(TypeError, match="query_id must be an integer"):
            havoc.get_all_variants_info("1")

    def test_get_all_variants_info_query_id_low(self, havoc):
        """Test get_all_variants_info rejects query_id below 1."""
        with pytest.raises(ValueError, match="Query ID must be 1-22"):
            havoc.get_all_variants_info(0)


class TestRunQuery:
    """Tests for run_query method."""

    @pytest.fixture
    def havoc(self, tmp_path):
        """Create a TPCHavoc instance for testing."""
        with patch("benchbox.tpchavoc.TPCHavocBenchmark"):
            return TPCHavoc(scale_factor=1.0, output_dir=tmp_path)

    def test_run_query_valid(self, havoc):
        """Test run_query with valid parameters."""
        havoc._impl.run_query.return_value = {"rows": 100, "time": 0.5}

        result = havoc.run_query(1, "duckdb:///:memory:")

        assert result == {"rows": 100, "time": 0.5}

    def test_run_query_invalid_query_id_type(self, havoc):
        """Test run_query rejects non-integer query_id."""
        with pytest.raises(TypeError, match="query_id must be an integer"):
            havoc.run_query("1", "duckdb:///:memory:")

    def test_run_query_invalid_query_id_range(self, havoc):
        """Test run_query rejects query_id out of range."""
        with pytest.raises(ValueError, match="Query ID must be 1-22"):
            havoc.run_query(0, "duckdb:///:memory:")

    def test_run_query_invalid_connection_string_empty(self, havoc):
        """Test run_query rejects empty connection string."""
        with pytest.raises(ValueError, match="connection_string must be a non-empty string"):
            havoc.run_query(1, "")

    def test_run_query_invalid_connection_string_whitespace(self, havoc):
        """Test run_query rejects whitespace-only connection string."""
        with pytest.raises(ValueError, match="connection_string must be a non-empty string"):
            havoc.run_query(1, "   ")


class TestRunBenchmark:
    """Tests for run_benchmark method."""

    @pytest.fixture
    def havoc(self, tmp_path):
        """Create a TPCHavoc instance for testing."""
        with patch("benchbox.tpchavoc.TPCHavocBenchmark"):
            return TPCHavoc(scale_factor=1.0, output_dir=tmp_path)

    def test_run_benchmark_valid(self, havoc):
        """Test run_benchmark with valid parameters."""
        havoc._impl.run_benchmark.return_value = {"total_time": 10.0}

        result = havoc.run_benchmark("duckdb:///:memory:")

        assert result == {"total_time": 10.0}

    def test_run_benchmark_invalid_connection_string(self, havoc):
        """Test run_benchmark rejects empty connection string."""
        with pytest.raises(ValueError, match="connection_string must be a non-empty string"):
            havoc.run_benchmark("")

    def test_run_benchmark_invalid_iterations_type(self, havoc):
        """Test run_benchmark rejects non-integer iterations."""
        with pytest.raises(TypeError, match="iterations must be an integer"):
            havoc.run_benchmark("duckdb:///:memory:", iterations="5")

    def test_run_benchmark_invalid_iterations_value(self, havoc):
        """Test run_benchmark rejects non-positive iterations."""
        with pytest.raises(ValueError, match="iterations must be positive"):
            havoc.run_benchmark("duckdb:///:memory:", iterations=0)

    def test_run_benchmark_invalid_queries_type(self, havoc):
        """Test run_benchmark rejects non-list queries."""
        with pytest.raises(TypeError, match="queries must be a list"):
            havoc.run_benchmark("duckdb:///:memory:", queries=1)

    def test_run_benchmark_invalid_query_id_in_list(self, havoc):
        """Test run_benchmark rejects invalid query IDs in list."""
        with pytest.raises(TypeError, match="query_id must be an integer"):
            havoc.run_benchmark("duckdb:///:memory:", queries=["1"])

    def test_run_benchmark_invalid_query_id_range_in_list(self, havoc):
        """Test run_benchmark rejects out-of-range query IDs."""
        with pytest.raises(ValueError, match="Query ID must be 1-22"):
            havoc.run_benchmark("duckdb:///:memory:", queries=[23])


class TestDelegationMethods:
    """Tests for methods that simply delegate to implementation."""

    @pytest.fixture
    def havoc(self, tmp_path):
        """Create a TPCHavoc instance for testing."""
        with patch("benchbox.tpchavoc.TPCHavocBenchmark"):
            return TPCHavoc(scale_factor=1.0, output_dir=tmp_path)

    def test_generate_data(self, havoc):
        """Test generate_data delegates to implementation."""
        havoc._impl.generate_data.return_value = [Path("data.csv")]

        result = havoc.generate_data()

        assert result == [Path("data.csv")]
        havoc._impl.generate_data.assert_called_once()

    def test_get_queries(self, havoc):
        """Test get_queries delegates to implementation."""
        havoc._impl.get_queries.return_value = {"1": "SELECT"}

        result = havoc.get_queries()

        assert result == {"1": "SELECT"}
        havoc._impl.get_queries.assert_called_once_with(dialect=None)

    def test_get_queries_with_dialect(self, havoc):
        """Test get_queries passes dialect to implementation."""
        havoc._impl.get_queries.return_value = {"1": "SELECT"}

        havoc.get_queries(dialect="duckdb")

        havoc._impl.get_queries.assert_called_once_with(dialect="duckdb")

    def test_get_implemented_queries(self, havoc):
        """Test get_implemented_queries delegates to implementation."""
        havoc._impl.get_implemented_queries.return_value = [1, 3, 6]

        result = havoc.get_implemented_queries()

        assert result == [1, 3, 6]
        havoc._impl.get_implemented_queries.assert_called_once()

    def test_get_schema(self, havoc):
        """Test get_schema delegates to implementation."""
        havoc._impl.get_schema.return_value = {"orders": {"columns": []}}

        result = havoc.get_schema()

        assert result == {"orders": {"columns": []}}
        havoc._impl.get_schema.assert_called_once()

    def test_get_create_tables_sql(self, havoc):
        """Test get_create_tables_sql delegates to implementation."""
        havoc._impl.get_create_tables_sql.return_value = "CREATE TABLE orders"

        result = havoc.get_create_tables_sql()

        assert result == "CREATE TABLE orders"
        havoc._impl.get_create_tables_sql.assert_called_once()

    def test_get_benchmark_info(self, havoc):
        """Test get_benchmark_info delegates to implementation."""
        havoc._impl.get_benchmark_info.return_value = {"name": "TPC-Havoc"}

        result = havoc.get_benchmark_info()

        assert result == {"name": "TPC-Havoc"}
        havoc._impl.get_benchmark_info.assert_called_once()

    def test_export_variant_queries(self, havoc):
        """Test export_variant_queries delegates to implementation."""
        havoc._impl.export_variant_queries.return_value = {"1_v1": Path("q1_v1.sql")}

        result = havoc.export_variant_queries()

        assert result == {"1_v1": Path("q1_v1.sql")}
        havoc._impl.export_variant_queries.assert_called_once()

    def test_load_data_to_database(self, havoc):
        """Test load_data_to_database delegates to implementation."""
        havoc.load_data_to_database("duckdb:///:memory:")

        havoc._impl.load_data_to_database.assert_called_once()
