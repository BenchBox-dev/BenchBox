"""Shared test mixin for benchmark test classes.

Provides common test methods for execute_query, load_data_to_database, and
error handling paths that are duplicated across SSB, H2ODB, AMPLab, and
ClickBench test suites.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest


class BenchmarkTestMixin:
    """Mixin providing shared test methods for benchmark 'Directly' test classes.

    Subclasses MUST define:
        benchmark_class: The benchmark class under test (e.g., SSBBenchmark)
        sample_query_id: A valid query ID for the benchmark (e.g., "Q1.1")
        sample_table: A table name from the benchmark schema (e.g., "lineorder")
        sample_sql: SQL string returned by mocked get_query (e.g., "SELECT COUNT(*) FROM lineorder")
        sample_csv_filename: CSV filename for load_data tests (e.g., "lineorder.csv")
        sample_csv_content: A single CSV row for load_data tests

    Subclasses MUST provide a ``benchmark_instance`` pytest fixture that returns
    an instance of ``benchmark_class``.

    Optional class attributes:
        get_query_passes_params: If True (default), execute_query passes params=
            to get_query. Set to False for benchmarks like H2ODB where execute_query
            calls get_query(query_id) without params.
    """

    benchmark_class: type
    sample_query_id: str
    sample_table: str
    sample_sql: str
    sample_csv_filename: str
    sample_csv_content: str
    get_query_passes_params: bool = True

    def _expected_get_query_call_args(self, query_id: str, params: Any = None) -> tuple:
        """Return the expected positional/keyword args for get_query assertion.

        Returns (args, kwargs) tuples suitable for assert_called_once_with.
        """
        if self.get_query_passes_params:
            return (query_id,), {"params": params}
        return (query_id,), {}

    # ------------------------------------------------------------------
    # execute_query tests
    # ------------------------------------------------------------------

    def test_execute_query_direct_connection(self, benchmark_instance: Any) -> None:
        """Test execute_query with direct database connection (connection.execute path)."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = [("result1",), ("result2",)]
        mock_connection.execute.return_value = mock_cursor

        with patch.object(benchmark_instance, "get_query") as mock_get_query:
            mock_get_query.return_value = self.sample_sql

            result = benchmark_instance.execute_query(self.sample_query_id, mock_connection)

            args, kwargs = self._expected_get_query_call_args(self.sample_query_id)
            mock_get_query.assert_called_once_with(*args, **kwargs)
            mock_connection.execute.assert_called_once_with(self.sample_sql)
            mock_cursor.fetchall.assert_called_once()
            assert result == [("result1",), ("result2",)]

    def test_execute_query_cursor_connection(self, benchmark_instance: Any) -> None:
        """Test execute_query with cursor-based connection (connection.cursor path)."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = [("result1",), ("result2",)]
        mock_connection.cursor.return_value = mock_cursor
        del mock_connection.execute  # Remove execute method to force cursor path

        with patch.object(benchmark_instance, "get_query") as mock_get_query:
            mock_get_query.return_value = self.sample_sql

            result = benchmark_instance.execute_query(self.sample_query_id, mock_connection)

            args, kwargs = self._expected_get_query_call_args(self.sample_query_id)
            mock_get_query.assert_called_once_with(*args, **kwargs)
            mock_connection.cursor.assert_called_once()
            mock_cursor.execute.assert_called_once_with(self.sample_sql)
            mock_cursor.fetchall.assert_called_once()
            assert result == [("result1",), ("result2",)]

    def test_execute_query_unsupported_connection(self, benchmark_instance: Any) -> None:
        """Test execute_query with unsupported connection type raises ValueError."""
        mock_connection = Mock()
        del mock_connection.execute
        del mock_connection.cursor

        with patch.object(benchmark_instance, "get_query") as mock_get_query:
            mock_get_query.return_value = self.sample_sql

            with pytest.raises(ValueError, match="Unsupported connection type"):
                benchmark_instance.execute_query(self.sample_query_id, mock_connection)

    # ------------------------------------------------------------------
    # load_data_to_database tests
    # ------------------------------------------------------------------

    def test_load_data_to_database_no_data(self, benchmark_instance: Any) -> None:
        """Test load_data_to_database raises ValueError when no data has been generated."""
        mock_connection = Mock()

        with pytest.raises(ValueError, match="No data generated"):
            benchmark_instance.load_data_to_database(mock_connection)

    def test_load_data_to_database_executescript(self, benchmark_instance: Any) -> None:
        """Test load_data_to_database with executescript/executemany/commit support."""
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_file = Path(temp_dir) / self.sample_csv_filename
            csv_file.write_text(self.sample_csv_content)

            benchmark_instance.tables = {self.sample_table: str(csv_file)}

            mock_connection = Mock()
            mock_connection.executescript = Mock()
            mock_connection.executemany = Mock()
            mock_connection.commit = Mock()

            with patch.object(benchmark_instance, "get_create_tables_sql") as mock_get_sql:
                mock_get_sql.return_value = f"CREATE TABLE {self.sample_table} (...);"

                benchmark_instance.load_data_to_database(mock_connection)

                mock_connection.executescript.assert_called_once()
                mock_connection.executemany.assert_called()
                mock_connection.commit.assert_called_once()
