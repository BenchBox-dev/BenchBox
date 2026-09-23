"""
Tests for database reuse optimization in Primitives and TPCHavoc benchmarks.

This test module verifies that both benchmarks can properly detect and reuse
existing compatible TPC-H databases to avoid redundant data generation and loading.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License.
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from benchbox.core.connection import DatabaseConnection
from benchbox.core.read_primitives.benchmark import ReadPrimitivesBenchmark
from benchbox.core.tpchavoc.benchmark import TPCHavocBenchmark

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestPrimitivesDatabaseReuse:
    """Test database reuse optimization for Primitives benchmark."""

    @pytest.fixture
    def primitives_benchmark(self):
        """Create a Primitives benchmark for testing."""
        return ReadPrimitivesBenchmark(scale_factor=0.01, verbose=False)

    @pytest.fixture
    def mock_connection(self):
        """Create a mock database connection."""
        connection = Mock(spec=DatabaseConnection)
        return connection

    def test_check_compatible_tpch_database_success(self, primitives_benchmark, mock_connection):
        """Test successful detection of compatible TPC-H database."""
        # Mock successful table existence checks
        mock_connection.execute.return_value = [(1,)]  # Non-empty result for table checks

        # For lineitem count check, return a count compatible with scale factor 0.01
        def mock_execute(query):
            if "COUNT(*) FROM lineitem" in query:
                # Return count compatible with scale factor 0.01 (~60,000 rows)
                return [(60000,)]
            else:
                # Return non-empty result for table existence checks
                return [(1,)]

        mock_connection.execute.side_effect = mock_execute

        # Test compatibility check
        result = primitives_benchmark._check_compatible_tpch_database(mock_connection)

        assert result is True
        # Verify all required tables were checked
        expected_tables = [
            "region",
            "nation",
            "customer",
            "supplier",
            "part",
            "partsupp",
            "orders",
            "lineitem",
        ]
        table_queries = [call.args[0] for call in mock_connection.execute.call_args_list if "COUNT(*)" in call.args[0]]

        # Should check all tables plus lineitem count
        assert len(table_queries) >= len(expected_tables)

    def test_check_compatible_tpch_database_missing_table(self, primitives_benchmark, mock_connection):
        """Test detection when required tables are missing."""
        # Mock missing table (exception when querying)
        mock_connection.execute.side_effect = Exception("Table doesn't exist")

        result = primitives_benchmark._check_compatible_tpch_database(mock_connection)

        assert result is False

    def test_check_compatible_tpch_database_wrong_scale(self, primitives_benchmark, mock_connection):
        """Test detection when database has wrong scale factor."""

        # Mock successful table existence checks
        def mock_execute(query):
            if "COUNT(*) FROM lineitem" in query:
                # Return count for scale factor 1.0, not 0.01
                return [(6000000,)]  # Too many rows for scale factor 0.01
            else:
                return [(1,)]

        mock_connection.execute.side_effect = mock_execute

        result = primitives_benchmark._check_compatible_tpch_database(mock_connection)

        assert result is False

    def test_load_data_with_compatible_database(self, primitives_benchmark, mock_connection):
        """Test that _load_data reuses compatible database."""
        # Mock compatible database check to return True
        with patch.object(primitives_benchmark, "_check_compatible_tpch_database", return_value=True):
            primitives_benchmark._load_data(mock_connection)

        # Should not attempt to load data since compatible database exists
        # Connection should not be used for data loading operations
        assert mock_connection.execute.call_count == 0

    def test_load_data_without_compatible_database(self, primitives_benchmark, mock_connection):
        """Test that _load_data falls back to normal data loading when no compatible database."""
        # Setup mock data for normal loading
        primitives_benchmark.tables = {
            "region": Path("/tmp/region.tbl"),
            "nation": Path("/tmp/nation.tbl"),
        }

        # Mock compatible database check to return False
        with patch.object(primitives_benchmark, "_check_compatible_tpch_database", return_value=False):
            # Mock file operations
            with (
                patch("pathlib.Path.exists", return_value=True),
                patch("builtins.open", mock_open_csv_data()),
                patch.object(
                    primitives_benchmark,
                    "get_create_tables_sql",
                    return_value="CREATE TABLE test (id INT)",
                ),
            ):
                primitives_benchmark._load_data(mock_connection)

        # Should attempt to create schema and load data
        assert mock_connection.execute.call_count > 0

    def test_validate_database_configuration_compatibility(self, primitives_benchmark):
        """Test database configuration compatibility validation."""
        # Compatible TPC-H configuration
        tpch_config = {"benchmark_type": "tpch", "scale_factor": 0.01}

        result = primitives_benchmark._validate_database_configuration_compatibility(tpch_config)
        assert result is True

        # Incompatible benchmark type
        other_config = {"benchmark_type": "tpcds", "scale_factor": 0.01}

        result = primitives_benchmark._validate_database_configuration_compatibility(other_config)
        assert result is False

        # Incompatible scale factor
        scale_config = {
            "benchmark_type": "tpch",
            "scale_factor": 1.0,  # Different from benchmark's 0.01
        }

        result = primitives_benchmark._validate_database_configuration_compatibility(scale_config)
        assert result is False


class TestTPCHavocDatabaseReuse:
    """Test database reuse optimization for TPCHavoc benchmark."""

    @pytest.fixture
    def tpchavoc_benchmark(self):
        """Create a TPCHavoc benchmark for testing."""
        return TPCHavocBenchmark(scale_factor=0.01, verbose=False)

    @pytest.fixture
    def mock_connection(self):
        """Create a mock database connection."""
        connection = Mock()
        return connection

    def test_check_compatible_tpch_database_success(self, tpchavoc_benchmark, mock_connection):
        """Test successful detection of compatible TPC-H database."""

        # Mock successful table existence checks directly on the passed connection
        def mock_execute(query):
            if "COUNT(*) FROM lineitem" in query:
                # Return count compatible with scale factor 0.01
                return [(60000,)]
            else:
                return [(1,)]

        mock_connection.execute = Mock(side_effect=mock_execute)
        # Include required methods to make the connection look valid
        mock_connection.commit = Mock()

        result = tpchavoc_benchmark._check_compatible_tpch_database(mock_connection)

        assert result is True

    def test_check_compatible_tpch_database_missing_table(self, tpchavoc_benchmark, mock_connection):
        """Test detection when required tables are missing."""
        # Mock table existence checks to fail
        mock_connection.execute = Mock(side_effect=Exception("Table doesn't exist"))
        mock_connection.commit = Mock()

        result = tpchavoc_benchmark._check_compatible_tpch_database(mock_connection)

        assert result is False

    def test_load_data_with_compatible_database(self, tpchavoc_benchmark, mock_connection):
        """Test that _load_data reuses compatible database."""
        with (
            patch.object(tpchavoc_benchmark, "_check_compatible_tpch_database", return_value=True),
            patch("benchbox.core.tpch.benchmark.TPCHBenchmark._load_data") as mock_parent_load,
        ):
            tpchavoc_benchmark._load_data(mock_connection)

        mock_parent_load.assert_not_called()

    def test_load_data_without_compatible_database(self, tpchavoc_benchmark, mock_connection):
        """Test that _load_data falls back to parent implementation when no compatible database."""
        # Mock compatible database check to return False
        with patch.object(tpchavoc_benchmark, "_check_compatible_tpch_database", return_value=False):
            # Mock parent's _load_data method
            with patch("benchbox.core.tpch.benchmark.TPCHBenchmark._load_data") as mock_parent_load:
                tpchavoc_benchmark._load_data(mock_connection)

                # Should call parent's _load_data method
                mock_parent_load.assert_called_once()

    def test_validate_database_configuration_compatibility(self, tpchavoc_benchmark):
        """Test database configuration compatibility validation."""
        # Compatible TPC-H configuration
        tpch_config = {"benchmark_type": "tpch", "scale_factor": 0.01}

        result = tpchavoc_benchmark._validate_database_configuration_compatibility(tpch_config)
        assert result is True

        # Compatible TPC-Havoc configuration
        havoc_config = {"benchmark_type": "tpchavoc", "scale_factor": 0.01}

        result = tpchavoc_benchmark._validate_database_configuration_compatibility(havoc_config)
        assert result is True

        # Incompatible benchmark type
        other_config = {"benchmark_type": "tpcds", "scale_factor": 0.01}

        result = tpchavoc_benchmark._validate_database_configuration_compatibility(other_config)
        assert result is False


class TestDatabaseReuseIntegration:
    """Integration tests for database reuse functionality."""

    def test_primitives_inherits_tpch_compatibility(self):
        """Test that Primitives can use databases created by TPC-H benchmark."""
        primitives = ReadPrimitivesBenchmark(scale_factor=0.01)

        # Simulate TPC-H database configuration
        tpch_config = {
            "benchmark_type": "tpch",
            "scale_factor": 0.01,
            "tuning_enabled": False,
        }

        result = primitives._validate_database_configuration_compatibility(tpch_config)
        assert result is True

    def test_tpchavoc_inherits_tpch_compatibility(self):
        """Test that TPCHavoc can use databases created by TPC-H benchmark."""
        tpchavoc = TPCHavocBenchmark(scale_factor=0.01)

        # Simulate TPC-H database configuration
        tpch_config = {
            "benchmark_type": "tpch",
            "scale_factor": 0.01,
            "tuning_enabled": False,
        }

        result = tpchavoc._validate_database_configuration_compatibility(tpch_config)
        assert result is True

    def test_cross_benchmark_compatibility(self):
        """Test that Primitives and TPCHavoc are compatible with each other."""
        ReadPrimitivesBenchmark(scale_factor=0.01)
        tpchavoc = TPCHavocBenchmark(scale_factor=0.01)

        # Primitives config should be compatible with TPC-Havoc
        primitives_config = {"benchmark_type": "read_primitives", "scale_factor": 0.01}

        # Note: This would work if we extended the compatibility check
        # For now, we focus on TPC-H compatibility
        result = tpchavoc._validate_database_configuration_compatibility(primitives_config)
        assert result is False  # Currently only accepts TPC-H/TPC-Havoc types

    def test_scale_factor_mismatch_prevents_reuse(self):
        """Test that different scale factors prevent database reuse."""
        primitives_small = ReadPrimitivesBenchmark(scale_factor=0.01)

        large_config = {
            "benchmark_type": "tpch",
            "scale_factor": 1.0,  # Different scale factor
        }

        result = primitives_small._validate_database_configuration_compatibility(large_config)
        assert result is False


def mock_open_csv_data():
    """Mock file opening for CSV data."""
    from unittest.mock import mock_open

    # Mock CSV content
    csv_content = "1|REGION1|\n2|REGION2|\n"
    return mock_open(read_data=csv_content)


@pytest.mark.integration
class TestDatabaseReuseEndToEnd:
    """End-to-end tests for database reuse optimization."""

    def test_primitives_database_reuse_workflow(self):
        """Test complete workflow of database reuse for Primitives."""
        with tempfile.TemporaryDirectory() as temp_dir:
            primitives = ReadPrimitivesBenchmark(scale_factor=0.01, output_dir=temp_dir, verbose=True)

            # Mock connection that represents existing TPC-H database
            mock_connection = Mock(spec=DatabaseConnection)

            # Mock successful compatibility check
            def mock_execute(query):
                if "COUNT(*) FROM lineitem" in query:
                    return [(60000,)]  # Compatible row count
                else:
                    return [(1,)]  # Table exists

            mock_connection.execute.side_effect = mock_execute

            # Test that database reuse is detected
            result = primitives._check_compatible_tpch_database(mock_connection)
            assert result is True

            # Test that _load_data uses the reuse optimization
            with patch.object(primitives, "_check_compatible_tpch_database", return_value=True):
                primitives._load_data(mock_connection)
                # Should complete without errors and without data loading

    def test_tpchavoc_database_reuse_workflow(self):
        """Test complete workflow of database reuse for TPCHavoc."""
        with tempfile.TemporaryDirectory() as temp_dir:
            tpchavoc = TPCHavocBenchmark(scale_factor=0.01, output_dir=temp_dir, verbose=True)

            # Mock connection that represents existing TPC-H database
            mock_connection = Mock()
            mock_db_connection = Mock(spec=DatabaseConnection)

            def mock_execute(query):
                if "COUNT(*) FROM lineitem" in query:
                    return [(60000,)]
                else:
                    return [(1,)]

            mock_db_connection.execute.side_effect = mock_execute

            # Setup mock connection properly
            mock_connection.execute = Mock(side_effect=mock_execute)
            mock_connection.commit = Mock()

            result = tpchavoc._check_compatible_tpch_database(mock_connection)
            assert result is True

            # Test that _load_data uses reuse optimization
            with patch.object(tpchavoc, "_check_compatible_tpch_database", return_value=True):
                tpchavoc._load_data(mock_connection)
                # Should complete without errors and without calling parent _load_data
