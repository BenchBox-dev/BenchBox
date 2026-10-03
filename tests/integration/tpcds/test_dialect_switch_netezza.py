"""Test TPC-DS dialect switch from ANSI to Netezza default

Verifies that TPC-DS now uses Netezza dialect by default (LIMIT syntax)
while maintaining compatibility with explicit dialect specification.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from unittest.mock import Mock, patch

import pytest

from benchbox.core.tpcds.c_tools import DSQGenBinary
from benchbox.core.tpcds.queries import TPCDSQueryManager
from benchbox.platforms.base import PlatformAdapter

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fast,
]


class TestTPCDSDialectSwitch:
    """Test TPC-DS dialect switch to Netezza default."""

    def test_tpcds_query_manager_default_dialect_netezza(self):

        # Create a mock DSQGenBinary that tracks dialect calls
        mock_dsqgen = Mock(spec=DSQGenBinary)
        mock_dsqgen.generate.return_value = "SELECT * FROM test LIMIT 100"

        with patch("benchbox.core.tpcds.queries.DSQGenBinary", return_value=mock_dsqgen):
            manager = TPCDSQueryManager()

            # Call get_query without specifying dialect (should use default)
            sql = manager.get_query(1, seed=12345, scale_factor=1.0)

            # Verify DSQGenBinary.generate was called with netezza dialect
            mock_dsqgen.generate.assert_called_once_with(
                1, seed=12345, scale_factor=1.0, stream_id=None, dialect="netezza"
            )
            assert sql == "SELECT * FROM test LIMIT 100"

    def test_tpcds_query_manager_explicit_ansi_dialect(self):

        mock_dsqgen = Mock(spec=DSQGenBinary)
        mock_dsqgen.generate.return_value = "SELECT TOP 100 * FROM test"

        with patch("benchbox.core.tpcds.queries.DSQGenBinary", return_value=mock_dsqgen):
            manager = TPCDSQueryManager()

            # Call get_query with explicit ansi dialect
            sql = manager.get_query(1, seed=12345, scale_factor=1.0, dialect="ansi")

            # Verify DSQGenBinary.generate was called with ansi dialect
            mock_dsqgen.generate.assert_called_once_with(
                1, seed=12345, scale_factor=1.0, stream_id=None, dialect="ansi"
            )
            assert sql == "SELECT TOP 100 * FROM test"

    # Note: Tests for DSQGenBinary and TPCDSBenchmark at the binary level
    # are covered by integration tests since they depend on the actual dsqgen binary
    # and file system setup. Unit tests focus on the API layer changes.

    def test_platform_adapter_tpcds_base_dialect(self):

        # Create a concrete mock adapter since PlatformAdapter is abstract
        class MockAdapter(PlatformAdapter):
            @staticmethod
            def add_cli_arguments(parser):
                """Add CLI arguments (required abstract method)."""

            @classmethod
            def from_config(cls, config):
                """Create adapter from config (required abstract method)."""
                return cls()

            @property
            def platform_name(self):
                return "Mock"

            def get_target_dialect(self):
                """Return target SQL dialect for mock adapter."""
                return "mock"

            def create_connection(self):
                pass

            def create_schema(self, benchmark):
                pass

            def load_data(self, benchmark, file_path, table_name):
                pass

            def execute_query(self, query):
                pass

            def configure_for_benchmark(self, benchmark):
                pass

            def apply_platform_optimizations(self, benchmark):
                pass

            def apply_constraint_configuration(self, benchmark):
                pass

        adapter = MockAdapter()

        # Test TPC-DS returns netezza by default
        base_dialect = adapter.get_tpc_base_dialect("tpcds")
        assert base_dialect == "netezza"

        # Test TPC-DS (uppercase) returns netezza
        base_dialect = adapter.get_tpc_base_dialect("TPCDS")
        assert base_dialect == "netezza"

        # Test TPC-H also returns netezza (for consistency)
        base_dialect = adapter.get_tpc_base_dialect("tpch")
        assert base_dialect == "netezza"

        # Test other benchmarks also return netezza
        base_dialect = adapter.get_tpc_base_dialect("ssb")
        assert base_dialect == "netezza"

    def test_all_supported_dialects_work(self):
        """Test that all TPC-DS dialects (netezza, ansi, etc.) are supported."""
        mock_dsqgen = Mock(spec=DSQGenBinary)

        test_cases = [
            ("netezza", "SELECT * FROM test LIMIT 100"),
            ("ansi", "SELECT TOP 100 * FROM test"),
            ("oracle", "SELECT * FROM test WHERE ROWNUM <= 100"),
            ("db2", "SELECT * FROM test FETCH FIRST 100 ROWS ONLY"),
            ("sqlserver", "SELECT TOP 100 * FROM test"),
        ]

        with patch("benchbox.core.tpcds.queries.DSQGenBinary", return_value=mock_dsqgen):
            manager = TPCDSQueryManager()

            for dialect, expected_sql in test_cases:
                mock_dsqgen.generate.return_value = expected_sql
                sql = manager.get_query(1, dialect=dialect)

                # Verify correct dialect was passed and SQL returned
                mock_dsqgen.generate.assert_called_with(1, seed=None, scale_factor=1.0, stream_id=None, dialect=dialect)
                assert sql == expected_sql

    def test_generate_with_parameters_uses_netezza_default(self):

        mock_dsqgen = Mock(spec=DSQGenBinary)
        mock_dsqgen.generate_with_parameters.return_value = "SELECT * FROM test WHERE x = 5 LIMIT 10"

        with patch("benchbox.core.tpcds.queries.DSQGenBinary", return_value=mock_dsqgen):
            manager = TPCDSQueryManager()

            # Call generate_with_parameters without specifying dialect
            sql = manager.generate_with_parameters(1, {"x": 5}, scale_factor=1.0)

            # Verify netezza dialect was used by default
            mock_dsqgen.generate_with_parameters.assert_called_once_with(
                1, {"x": 5}, scale_factor=1.0, dialect="netezza"
            )
            assert sql == "SELECT * FROM test WHERE x = 5 LIMIT 10"

    def test_backward_compatibility_maintained(self):

        # This test ensures that any existing code that explicitly specifies
        # dialect='ansi' will continue to work unchanged
        mock_dsqgen = Mock(spec=DSQGenBinary)
        mock_dsqgen.generate.return_value = "SELECT TOP 100 * FROM test"

        with patch("benchbox.core.tpcds.queries.DSQGenBinary", return_value=mock_dsqgen):
            manager = TPCDSQueryManager()

            # This represents existing code that explicitly uses ansi
            sql = manager.get_query(1, seed=42, scale_factor=0.1, dialect="ansi")

            mock_dsqgen.generate.assert_called_once_with(1, seed=42, scale_factor=0.1, stream_id=None, dialect="ansi")
            assert sql == "SELECT TOP 100 * FROM test"
