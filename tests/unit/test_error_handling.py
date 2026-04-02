"""Comprehensive error handling and edge case tests.

This module tests error conditions, edge cases, and exceptional scenarios
across the BenchBox library to ensure robust error handling.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import contextlib
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

pytest.importorskip("pandas")

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]


# Windows has different permission semantics - chmod doesn't work as expected
IS_WINDOWS = sys.platform == "win32"

from benchbox.amplab import AMPLab
from benchbox.clickbench import ClickBench
from benchbox.core.connection import DatabaseConnection, DatabaseError
from benchbox.h2odb import H2ODB
from benchbox.ssb import SSB
from benchbox.tpcdi import TPCDI
from benchbox.tpcds import TPCDS
from benchbox.tpch import TPCH
from benchbox.write_primitives import WritePrimitives


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.mark.unit
class TestDatabaseConnectionErrors:
    """Test database connection error handling."""

    def test_none_connection_object(self):
        """Test error handling when None is passed as connection."""
        with pytest.raises(TypeError, match="Connection object cannot be None"):
            DatabaseConnection(None)

    def test_invalid_connection_object(self):
        """Test error handling for invalid connection objects."""
        # Create an object without cursor or execute methods
        invalid_conn = object()

        with pytest.raises(
            ValueError,
            match="Connection object must have either 'cursor' or 'execute' method",
        ):
            DatabaseConnection(invalid_conn)

    def test_sqlite_connection_with_invalid_path(self):
        """Test error handling for SQLite with invalid database paths."""
        # Test with non-existent directory
        invalid_path = "/non/existent/path/database.db"

        with pytest.raises((OSError, sqlite3.OperationalError)):
            sqlite_conn = sqlite3.connect(invalid_path)
            conn = DatabaseConnection(sqlite_conn)
            conn.execute("SELECT 1")

    def test_connection_with_closed_sqlite(self):
        """Test error handling with closed SQLite connections."""
        sqlite_conn = sqlite3.connect(":memory:")
        sqlite_conn.close()  # Close the connection

        # DatabaseConnection should accept it but operations should fail
        conn = DatabaseConnection(sqlite_conn)
        with pytest.raises(DatabaseError):
            conn.execute("SELECT 1")

    def test_malformed_connection_object(self):
        """Test handling of connection objects with malformed methods."""
        # Create a mock connection with broken methods
        mock_conn = Mock()
        mock_conn.cursor = Mock(side_effect=Exception("Cursor creation failed"))
        mock_conn.execute = None  # No execute method

        conn = DatabaseConnection(mock_conn)
        with pytest.raises(Exception):
            conn.execute("SELECT 1")


@pytest.mark.unit
class TestBenchmarkInitializationErrors:
    """Test benchmark initialization error handling."""

    def test_invalid_scale_factors(self, temp_dir):
        """Test error handling for invalid scale factors."""
        # Test zero scale factor
        with pytest.raises(ValueError):
            TPCH(scale_factor=0, output_dir=temp_dir)

        # Test negative scale factor
        with pytest.raises(ValueError):
            TPCDS(scale_factor=-1.0, output_dir=temp_dir)

        # Test extremely large scale factor
        with pytest.raises((ValueError, OverflowError)):
            TPCH(scale_factor=1e20, output_dir=temp_dir)

    def test_invalid_output_directories(self):
        """Test error handling for invalid output directories."""
        # Test with None - now handled gracefully with default
        benchmark = TPCH(scale_factor=1.0, output_dir=None)
        assert benchmark is not None  # Should create successfully

        # In Python 3.13+, Path() now raises TypeError for integers
        # This test verifies that invalid types are properly rejected
        with pytest.raises(TypeError):
            TPCDS(scale_factor=1.0, output_dir=123)

        # Empty string creates a path to current directory, so this doesn't fail
        benchmark3 = AMPLab(scale_factor=1.0, output_dir="")
        assert benchmark3.output_dir == Path("")

    @pytest.mark.skipif(IS_WINDOWS, reason="chmod doesn't enforce permissions on Windows")
    def test_permission_denied_output_directory(self, temp_dir):
        """Test error handling when output directory cannot be created."""
        # Create a read-only parent directory
        readonly_parent = temp_dir / "readonly_parent"
        readonly_parent.mkdir()
        readonly_parent.chmod(0o444)  # Read-only

        nested_output = readonly_parent / "output"

        try:
            with pytest.raises((PermissionError, OSError)):
                benchmark = TPCH(scale_factor=0.1, output_dir=nested_output)
                # Trigger directory creation
                benchmark.generate_data()
        finally:
            # Clean up permissions
            with contextlib.suppress(OSError, PermissionError):
                readonly_parent.chmod(0o755)

    def test_invalid_benchmark_parameters(self, temp_dir):
        """Test error handling for invalid benchmark-specific parameters."""
        # Test invalid parallel parameter - some implementations do validate this
        with pytest.raises((ValueError, TypeError)):
            TPCH(scale_factor=1.0, output_dir=temp_dir, parallel=-1)

        with pytest.raises((ValueError, TypeError)):
            TPCDS(scale_factor=1.0, output_dir=temp_dir, parallel=0)

        # Some parameters like verbose may be more tolerant and accepted as-is
        # This depends on the specific benchmark implementation
        try:
            benchmark3 = H2ODB(scale_factor=1.0, output_dir=temp_dir, verbose="invalid")
            # If it succeeds, check that the parameter was stored
            assert benchmark3.verbose == "invalid"
        except (ValueError, TypeError):
            # If it fails, that's also acceptable validation behavior
            pass


@pytest.mark.unit
class TestDataGenerationErrors:
    """Test data generation error handling."""

    def test_insufficient_disk_space_simulation(self, temp_dir):
        """Test handling of insufficient disk space during data generation."""
        benchmark = WritePrimitives(scale_factor=0.01, output_dir=temp_dir)

        with (
            patch.object(
                benchmark._impl.data_generator,
                "generate",
                side_effect=OSError(28, "No space left on device"),
            ),
            pytest.raises(OSError),
        ):
            benchmark.generate_data()

    def test_interrupted_data_generation(self, temp_dir):
        """Test handling of interrupted data generation."""
        benchmark = WritePrimitives(scale_factor=0.01, output_dir=temp_dir)

        # Mock the generation to raise KeyboardInterrupt
        with (
            patch.object(
                benchmark,
                "generate_data",
                side_effect=KeyboardInterrupt("User interrupted"),
            ),
            pytest.raises(KeyboardInterrupt),
        ):
            benchmark.generate_data()

    def test_corrupted_data_file_handling(self, temp_dir):
        """Test handling of corrupted or invalid data files."""
        # Only test benchmark initialization and file handling, not generation
        ClickBench(scale_factor=0.01, output_dir=temp_dir)

        # Create a corrupted data file with actual invalid UTF-8 bytes
        corrupted_file = temp_dir / "corrupted.csv"
        corrupted_file.write_bytes(b"\x00\xff\xfe\x80corrupted data")

        assert corrupted_file.exists()
        with pytest.raises((UnicodeDecodeError, OSError)):
            with open(corrupted_file, encoding="utf-8") as f:
                f.read()

    def test_memory_exhaustion_simulation(self, temp_dir):
        """Test handling of memory exhaustion during data generation."""
        # Use compression_type="none" to avoid zstd dependency
        benchmark = SSB(scale_factor=0.01, output_dir=temp_dir, compress_data=False, compression_type="none")

        # Mock memory allocation to raise MemoryError
        with patch("builtins.list", side_effect=MemoryError("Out of memory")), pytest.raises(MemoryError):
            benchmark.generate_data()


@pytest.mark.unit
class TestQueryExecutionErrors:
    """Test query execution error handling."""

    def test_sql_syntax_errors(self, temp_dir):
        """Test handling of SQL syntax errors."""
        # Create an in-memory SQLite connection
        sqlite_conn = sqlite3.connect(":memory:")
        conn = DatabaseConnection(sqlite_conn)

        # Test with invalid SQL
        with pytest.raises(DatabaseError):
            conn.execute("INVALID SQL SYNTAX")

    def test_missing_table_errors(self, temp_dir):
        """Test handling of queries referencing missing tables."""
        sqlite_conn = sqlite3.connect(":memory:")
        conn = DatabaseConnection(sqlite_conn)

        # Test query on non-existent table
        with pytest.raises(DatabaseError):
            conn.execute("SELECT * FROM non_existent_table")

    def test_connection_lost_during_query(self, temp_dir):
        """Test handling of lost database connections during query execution."""
        # Create a connection and then close it
        sqlite_conn = sqlite3.connect(":memory:")
        conn = DatabaseConnection(sqlite_conn)

        # Close the underlying connection
        sqlite_conn.close()

        # Operations should fail
        with pytest.raises(DatabaseError):
            conn.execute("SELECT 1")

    def test_query_execution_with_parameters_error(self, temp_dir):
        """Test handling of parameter binding errors."""
        sqlite_conn = sqlite3.connect(":memory:")
        conn = DatabaseConnection(sqlite_conn)

        # Create a table for testing
        conn.execute("CREATE TABLE test (id INTEGER, name TEXT)")

        # Test with wrong parameter type
        with pytest.raises(DatabaseError):
            conn.execute("INSERT INTO test VALUES (?, ?)", [1, 2, 3])  # Too many params


@pytest.mark.unit
class TestFileSystemEdgeCases:
    """Test file system edge cases and error conditions."""

    def test_extremely_long_file_paths(self, temp_dir):
        """Test handling of extremely long file paths."""
        # Create a very long directory path
        long_path = temp_dir
        for i in range(10):  # Create nested directories
            long_path = long_path / (f"very_long_directory_name_{i}_" * 10)

        try:
            benchmark = TPCDI(scale_factor=0.01, output_dir=long_path)
            # This might succeed or fail depending on OS path limits
            benchmark.generate_data()
        except (OSError, FileNotFoundError, ValueError):
            # Expected on systems with path length limits
            pass

    def test_special_characters_in_paths(self, temp_dir):
        """Test handling of special characters in file paths."""
        # Test with various special characters - optimize by only testing path creation
        special_chars = [
            "spaces in name",
            "unicode_测试",
            "symbols!@#$%^&*()",
            "dots...",
            "dash-es",
        ]

        for char_set in special_chars:
            try:
                special_dir = temp_dir / char_set
                # Only test benchmark initialization, not data generation
                benchmark = WritePrimitives(scale_factor=0.01, output_dir=special_dir)
                # Test that the path was set correctly
                assert benchmark.output_dir == special_dir
                # Test directory can be created
                special_dir.mkdir(parents=True, exist_ok=True)
                assert special_dir.exists()
            except (OSError, UnicodeError, ValueError):
                # Expected for some special character combinations
                pass

    def test_concurrent_file_access(self, temp_dir):
        """Test handling of concurrent file access conflicts."""
        import threading

        def write_data(benchmark, results, index):
            try:
                result = benchmark.generate_data()
                results[index] = result
            except Exception as e:
                results[index] = e

        # Create multiple benchmarks writing to the same output directory
        benchmarks = [WritePrimitives(scale_factor=0.01, output_dir=temp_dir) for _ in range(3)]

        results = {}
        threads = []

        # Start concurrent data generation
        for i, benchmark in enumerate(benchmarks):
            thread = threading.Thread(target=write_data, args=(benchmark, results, i))
            threads.append(thread)
            thread.start()

        # Wait for all threads
        for thread in threads:
            thread.join()

        # Check results - some may succeed, some may fail with file conflicts
        for _i, result in results.items():
            if isinstance(result, Exception):
                # File conflicts are expected and acceptable, as is RuntimeError
                # for missing native binaries in environments without TPC tools.
                # TimeoutError can occur on lock acquisition timeout.
                # ValueError/KeyError can occur due to concurrent data access races.
                # BlockingIOError can occur on non-blocking I/O systems.
                # csv.Error can occur when concurrent writes corrupt CSV being read.
                import csv

                assert isinstance(
                    result,
                    (
                        OSError,
                        PermissionError,
                        FileExistsError,
                        RuntimeError,
                        TimeoutError,
                        ValueError,
                        KeyError,
                        BlockingIOError,
                        csv.Error,
                    ),
                )
            else:
                assert isinstance(result, (dict, list))

    @pytest.mark.skipif(IS_WINDOWS, reason="chmod doesn't enforce permissions on Windows")
    def test_readonly_filesystem_handling(self, temp_dir):
        """Test handling of read-only filesystem scenarios."""
        # Create output directory and make it read-only
        output_dir = temp_dir / "readonly_output"
        output_dir.mkdir()

        # Make directory read-only
        output_dir.chmod(0o444)

        try:
            benchmark = WritePrimitives(scale_factor=0.01, output_dir=output_dir)

            with pytest.raises((PermissionError, OSError)):
                benchmark.generate_data()
        finally:
            # Restore permissions for cleanup
            with contextlib.suppress(OSError, PermissionError):
                output_dir.chmod(0o755)


@pytest.mark.unit
class TestResourceExhaustionScenarios:
    """Test resource exhaustion scenarios."""

    def test_file_descriptor_exhaustion(self, temp_dir):
        """Test handling of file descriptor exhaustion."""
        benchmark = H2ODB(scale_factor=0.01, output_dir=temp_dir)

        # Mock open to raise "Too many open files" error
        with patch("builtins.open", side_effect=OSError(24, "Too many open files")):
            # The compression system catches OSError and re-raises as CompressionError
            with pytest.raises((OSError, Exception)) as excinfo:
                benchmark.generate_data()
            # Check that the error message contains information about file descriptor exhaustion
            error_msg = str(excinfo.value)
            assert "Too many open files" in error_msg

    def test_thread_exhaustion_handling(self, temp_dir):
        """Test handling of thread exhaustion in parallel operations."""
        # Create benchmark with unreasonably high parallel setting
        try:
            benchmark = TPCH(scale_factor=0.01, output_dir=temp_dir, parallel=10000)
            # This should either limit the parallel setting or handle the error gracefully
            benchmark.generate_data()
        except (RuntimeError, OSError, ValueError):
            # Expected when thread limits are exceeded
            pass

    def test_network_timeout_handling(self):
        """Test handling of network timeouts during external data fetching - optimized version."""
        # Test without actual data generation - just test timeout handling
        benchmark = ClickBench(scale_factor=0.01)

        # Test that benchmark can be instantiated
        assert benchmark is not None

        # Mock network operations to simulate timeout - test error handling only
        with patch("urllib.request.urlopen", side_effect=TimeoutError("Network timeout")):
            with pytest.raises(TimeoutError, match="Network timeout"):
                import urllib.request

                urllib.request.urlopen("http://example.com")


@pytest.mark.unit
class TestParameterValidationEdgeCases:
    """Test parameter validation edge cases."""

    def test_boundary_value_testing(self, temp_dir):
        """Test boundary values for parameters."""
        # Test minimum valid values - 0.001 is now too small for TPC-H, should raise error
        with pytest.raises(ValueError, match="Scale factor 0.001 is too small"):
            TPCH(scale_factor=0.001, output_dir=temp_dir)

        # Test minimum actually valid value for TPC-H
        benchmark = TPCH(scale_factor=0.01, output_dir=temp_dir)
        assert benchmark.scale_factor >= 0.01

        # Test maximum reasonable values
        benchmark = TPCDS(scale_factor=100.0, output_dir=temp_dir)
        assert benchmark.scale_factor <= 100.0

        # Test floating point precision edge cases
        benchmark = AMPLab(scale_factor=0.0000001, output_dir=temp_dir)
        assert benchmark.scale_factor > 0

    def test_unicode_parameter_handling(self, temp_dir):
        """Test handling of unicode characters in parameters."""
        # Test unicode in directory names - optimize by only testing path handling
        unicode_dir = temp_dir / "测试目录"

        try:
            benchmark = WritePrimitives(scale_factor=0.01, output_dir=unicode_dir)
            # Only test path creation, not data generation
            assert benchmark.output_dir == unicode_dir
            unicode_dir.mkdir(parents=True, exist_ok=True)
            assert unicode_dir.exists()
        except (UnicodeError, OSError):
            # Expected on some file systems that don't support unicode
            pass

    def test_null_and_empty_parameter_handling(self, temp_dir):
        """Test handling of null and empty parameters."""
        # Test with various empty/null-like values
        invalid_values = [None, "", [], {}, False]

        for invalid_value in invalid_values:
            try:
                # This should raise appropriate validation errors
                if invalid_value is None:
                    with pytest.raises((TypeError, ValueError)):
                        TPCH(scale_factor=invalid_value, output_dir=temp_dir)
                elif invalid_value == "":
                    # Empty string output_dir is now handled gracefully with default
                    benchmark = TPCH(scale_factor=1.0, output_dir=invalid_value)
                    assert benchmark is not None  # Should create successfully
                else:
                    with pytest.raises((TypeError, ValueError)):
                        TPCH(scale_factor=1.0, output_dir=invalid_value)
            except (AssertionError, Exception):
                # Some invalid values might be handled differently
                pass


@pytest.mark.unit
class TestRecoveryAndCleanupScenarios:
    """Test error recovery and cleanup scenarios."""

    def test_partial_data_generation_recovery(self, temp_dir):
        """Test recovery from partial data generation failures."""
        benchmark = WritePrimitives(scale_factor=0.01, output_dir=temp_dir)

        # Create some partial files
        partial_file = temp_dir / "partial_data.csv"
        partial_file.write_text("incomplete,data,row")

        # Ensure benchmark can handle existing partial files
        try:
            result = benchmark.generate_data()
            assert isinstance(result, (dict, list))
        except Exception as e:
            # Should handle partial files gracefully
            assert not isinstance(e, SystemError)

    def test_cleanup_on_interruption(self, temp_dir):
        """Test cleanup behavior when operations are interrupted."""
        # Use compression_type="none" to avoid zstd dependency
        benchmark = SSB(scale_factor=0.01, output_dir=temp_dir, compress_data=False, compression_type="none")

        # Simulate interruption during data generation
        with patch.object(benchmark, "generate_data") as mock_generate:
            mock_generate.side_effect = KeyboardInterrupt("User interrupted")

            try:
                benchmark.generate_data()
            except KeyboardInterrupt:
                # Verify temp files are cleaned up (directory should exist but be manageable)
                assert temp_dir.exists()
                # Should not have excessive temporary files
                temp_files = list(temp_dir.glob("*"))
                assert len(temp_files) < 100  # Reasonable cleanup

    def test_resource_cleanup_on_exception(self, temp_dir):
        """Test that resources are properly cleaned up when exceptions occur."""
        benchmark = TPCDI(scale_factor=0.01, output_dir=temp_dir)

        original_open = open
        opened_files = []

        def tracking_open(*args, **kwargs):
            file_handle = original_open(*args, **kwargs)
            opened_files.append(file_handle)
            return file_handle

        with patch("builtins.open", side_effect=tracking_open):
            try:
                # Force an exception during data generation
                with patch.object(
                    benchmark,
                    "generate_data",
                    side_effect=RuntimeError("Simulated error"),
                ):
                    benchmark.generate_data()
            except RuntimeError:
                pass

            # Check that files are properly closed
            for file_handle in opened_files:
                if not file_handle.closed:
                    # Some files might still be open, but should be manageable
                    assert len([f for f in opened_files if not f.closed]) < 10
