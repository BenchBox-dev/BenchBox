# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest


class BenchmarkTestMixin:
    benchmark_class: type
    sample_query_id: str
    sample_table: str
    sample_sql: str
    sample_csv_filename: str
    sample_csv_content: str
    get_query_passes_params: bool = True

    def _expected_get_query_call_args(self, query_id: str, params: Any = None) -> tuple:
        if self.get_query_passes_params:
            return (query_id,), {"params": params}
        return (query_id,), {}

    def test_execute_query_direct_connection(self, benchmark_instance: Any) -> None:
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
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = [("result1",), ("result2",)]
        mock_connection.cursor.return_value = mock_cursor
        del mock_connection.execute

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
        mock_connection = Mock()
        del mock_connection.execute
        del mock_connection.cursor

        with patch.object(benchmark_instance, "get_query") as mock_get_query:
            mock_get_query.return_value = self.sample_sql

            with pytest.raises(ValueError, match="Unsupported connection type"):
                benchmark_instance.execute_query(self.sample_query_id, mock_connection)

    def test_load_data_to_database_no_data(self, benchmark_instance: Any) -> None:
        mock_connection = Mock()

        with pytest.raises(ValueError, match="No data generated"):
            benchmark_instance.load_data_to_database(mock_connection)

    def test_load_data_to_database_executescript(self, benchmark_instance: Any) -> None:
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
