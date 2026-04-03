"""Additional coverage tests for QuestDB platform adapter.

Targets uncovered branches in benchbox/platforms/questdb.py to reach ≥80% coverage.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import pytest

import benchbox.platforms.questdb as questdb_module
from benchbox.platforms.questdb import (
    QuestDBAdapter,
    _date_to_epoch_ns,
    _ilp_escape_field,
    _ilp_escape_measurement,
    _ilp_escape_tag_key,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture()
def questdb_stubs(monkeypatch):
    """Patch psycopg2 so tests don't require the real driver."""
    mock_psycopg2 = Mock()
    mock_psycopg2.__version__ = "2.9.9"
    mock_psycopg2.extras = Mock()
    monkeypatch.setattr(questdb_module, "psycopg2", mock_psycopg2)
    return mock_psycopg2


class TestMissingPsycopg2:
    """Test ImportError raised when psycopg2 is unavailable."""

    def test_init_raises_when_psycopg2_none(self, monkeypatch):
        """__init__ should raise ImportError when psycopg2 is None and dep check fails."""
        monkeypatch.setattr(questdb_module, "psycopg2", None)
        with (
            patch(
                "benchbox.platforms.questdb.check_platform_dependencies",
                return_value=(False, ["psycopg2"]),
            ),
            patch(
                "benchbox.platforms.questdb.get_dependency_error_message",
                return_value="psycopg2 is required for QuestDB",
            ),
            pytest.raises(ImportError, match="psycopg2"),
        ):
            QuestDBAdapter()


class TestAddCliArguments:
    """Test CLI argument registration."""

    def test_add_cli_arguments_with_valid_parser(self):
        """add_cli_arguments should register all expected arguments."""
        mock_parser = Mock()
        QuestDBAdapter.add_cli_arguments(mock_parser)

        added_args = [c[1].get("dest") for c in mock_parser.add_argument.call_args_list if c[1].get("dest")]
        assert "host" in added_args
        assert "pg_port" in added_args
        assert "http_port" in added_args
        assert "ilp_port" in added_args
        assert "username" in added_args
        assert "password" in added_args
        assert "loading_method" in added_args
        assert "partition_by" in added_args

    def test_add_cli_arguments_swallows_exception(self):
        """add_cli_arguments should silently swallow exceptions from add_argument."""
        mock_parser = Mock()
        mock_parser.add_argument.side_effect = Exception("arg conflict")
        # Should not raise
        QuestDBAdapter.add_cli_arguments(mock_parser)

    def test_add_cli_arguments_no_op_without_add_argument(self):
        """add_cli_arguments should return early when parser has no add_argument attr."""

        class FakeParser:
            pass

        QuestDBAdapter.add_cli_arguments(FakeParser())


class TestFromConfigAdvanced:
    """Test from_config edge cases."""

    def test_from_config_ilp_host_override(self, questdb_stubs):
        """from_config should allow explicit ilp_host override."""
        config = {"host": "dbhost", "ilp_host": "ilphost"}
        adapter = QuestDBAdapter.from_config(config)
        assert adapter.ilp_host == "ilphost"

    def test_from_config_ilp_host_fallback_to_host(self, questdb_stubs):
        """from_config ilp_host should fall back to host when not specified."""
        config = {"host": "myhost"}
        adapter = QuestDBAdapter.from_config(config)
        assert adapter.ilp_host == "myhost"

    def test_from_config_partition_by_set(self, questdb_stubs):
        """from_config should pass partition_by through."""
        config = {"partition_by": "DAY"}
        adapter = QuestDBAdapter.from_config(config)
        assert adapter.partition_by == "DAY"

    def test_from_config_loading_method_ilp(self, questdb_stubs):
        """from_config should accept ilp loading method."""
        config = {"loading_method": "ilp"}
        adapter = QuestDBAdapter.from_config(config)
        assert adapter.loading_method == "ilp"

    def test_from_config_force_recreate(self, questdb_stubs):
        """from_config should map 'force' to force_recreate."""
        config = {"force": True}
        adapter = QuestDBAdapter.from_config(config)
        assert adapter.config.get("force_recreate") is True


class TestCreateSchemaBranches:
    """Test schema creation statement handling branches."""

    def test_create_schema_adapts_drop_table(self, questdb_stubs):
        """create_schema should adapt DROP TABLE by adding IF EXISTS."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        adapter = QuestDBAdapter()

        with patch.object(adapter, "_create_schema_with_tuning") as mock_schema:
            mock_schema.return_value = "DROP TABLE lineitem; CREATE TABLE lineitem (id INT)"
            adapter.create_schema(Mock(), mock_conn)

        executed_calls = [str(c) for c in mock_cursor.execute.call_args_list]
        executed_text = " ".join(executed_calls)
        assert "IF EXISTS" in executed_text

    def test_create_schema_applies_questdb_enhancements(self, questdb_stubs):
        """create_schema should apply QuestDB-specific enhancements for known tables."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value = mock_cursor

        adapter = QuestDBAdapter()

        with patch.object(adapter, "_create_schema_with_tuning") as mock_schema:
            mock_schema.return_value = "CREATE TABLE lineitem (l_shipdate DATE, l_returnflag VARCHAR(1))"
            adapter.create_schema(Mock(), mock_conn)

        executed_sql = mock_cursor.execute.call_args[0][0]
        # symbol and timestamp enhancements should be applied
        assert "TIMESTAMP" in executed_sql or "SYMBOL" in executed_sql

    def test_create_schema_non_create_table_stmt_failure_does_not_raise(self, questdb_stubs):
        """Non-CREATE-TABLE statement failures should only warn, not raise."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.execute.side_effect = Exception("Some non-critical error")
        mock_conn.cursor.return_value = mock_cursor

        adapter = QuestDBAdapter()

        with patch.object(adapter, "_create_schema_with_tuning") as mock_schema:
            mock_schema.return_value = "SELECT 1"
            adapter.create_schema(Mock(), mock_conn)

    def test_extract_table_name_with_if_not_exists(self, questdb_stubs):
        """_extract_table_name should handle IF NOT EXISTS syntax."""
        adapter = QuestDBAdapter()
        name = adapter._extract_table_name("CREATE TABLE IF NOT EXISTS my_table (id INT)")
        assert name == "my_table"

    def test_extract_table_name_returns_none_for_non_create(self, questdb_stubs):
        """_extract_table_name returns None for non-CREATE statements."""
        adapter = QuestDBAdapter()
        assert adapter._extract_table_name("SELECT * FROM t") is None

    def test_apply_schema_enhancements_unknown_table(self, questdb_stubs):
        """_apply_questdb_schema_enhancements should return stmt unchanged for unknown tables."""
        adapter = QuestDBAdapter()
        stmt = "CREATE TABLE unknown_table (col1 INT, col2 TEXT)"
        result = adapter._apply_questdb_schema_enhancements(stmt)
        # No crash, stmt returned (may or may not be modified for unknown table)
        assert "CREATE TABLE" in result

    def test_apply_schema_enhancements_no_table_name(self, questdb_stubs):
        """_apply_questdb_schema_enhancements returns stmt when table name not found."""
        adapter = QuestDBAdapter()
        stmt = "SELECT 1"
        result = adapter._apply_questdb_schema_enhancements(stmt)
        assert result == stmt

    def test_get_partition_for_table_with_override(self, questdb_stubs):
        """_get_partition_for_table should use adapter-level override when set."""
        adapter = QuestDBAdapter(partition_by="YEAR")
        assert adapter._get_partition_for_table("lineitem") == "YEAR"
        assert adapter._get_partition_for_table("orders") == "YEAR"

    def test_get_partition_for_table_none_returns_none(self, questdb_stubs):
        """_get_partition_for_table should return NONE for tables without default."""
        adapter = QuestDBAdapter()
        result = adapter._get_partition_for_table("customer")
        assert result == "NONE"

    def test_add_timestamp_and_partition_none_partition(self, questdb_stubs):
        """_add_timestamp_and_partition should omit PARTITION BY when partition is NONE."""
        adapter = QuestDBAdapter()
        stmt = "CREATE TABLE t (ts TIMESTAMP)"
        result = adapter._add_timestamp_and_partition(stmt, "ts", "NONE")
        assert "timestamp(ts)" in result
        assert "PARTITION BY" not in result

    def test_add_timestamp_and_partition_with_partition(self, questdb_stubs):
        """_add_timestamp_and_partition should add PARTITION BY clause."""
        adapter = QuestDBAdapter()
        stmt = "CREATE TABLE t (ts TIMESTAMP)"
        result = adapter._add_timestamp_and_partition(stmt, "ts", "MONTH")
        assert "timestamp(ts)" in result
        assert "PARTITION BY MONTH" in result

    def test_map_column_to_symbol_varchar(self, questdb_stubs):
        """_map_column_to_symbol should replace VARCHAR with SYMBOL."""
        adapter = QuestDBAdapter()
        stmt = "CREATE TABLE t (l_returnflag VARCHAR(1))"
        result = adapter._map_column_to_symbol(stmt, "l_returnflag")
        assert "SYMBOL" in result
        assert "VARCHAR" not in result

    def test_map_column_to_timestamp(self, questdb_stubs):
        """_map_column_to_timestamp should replace DATE with TIMESTAMP."""
        adapter = QuestDBAdapter()
        stmt = "CREATE TABLE t (l_shipdate DATE)"
        result = adapter._map_column_to_timestamp(stmt, "l_shipdate")
        assert "TIMESTAMP" in result
        assert "DATE" not in result

    def test_strip_fk_constraints_inline_references(self, questdb_stubs):
        """_strip_fk_constraints should remove inline REFERENCES clauses."""
        adapter = QuestDBAdapter()
        stmt = "CREATE TABLE t (id INT, cust_id INT REFERENCES customer(id))"
        result = adapter._strip_fk_constraints(stmt)
        assert "REFERENCES" not in result
        assert "cust_id INT" in result


class TestLoadDataBranches:
    """Test load_data method branching logic."""

    def test_load_data_invalid_identifier_skipped(self, questdb_stubs, tmp_path):
        """load_data should skip tables with invalid identifiers."""
        data_file = tmp_path / "bad;name.csv"
        data_file.write_text("col1\n1\n", encoding="utf-8")

        adapter = QuestDBAdapter()
        mock_benchmark = Mock()
        mock_benchmark.tables = {"bad;name": str(data_file)}

        stats, duration, _ = adapter.load_data(mock_benchmark, Mock(), tmp_path)
        assert stats.get("bad;name") == 0

    def test_load_data_missing_file_skipped(self, questdb_stubs, tmp_path):
        """load_data should skip tables whose data files don't exist."""
        adapter = QuestDBAdapter()
        mock_benchmark = Mock()
        mock_benchmark.tables = {"lineitem": str(tmp_path / "nonexistent.csv")}

        stats, duration, _ = adapter.load_data(mock_benchmark, Mock(), tmp_path)
        assert stats.get("lineitem") == 0

    def test_load_data_rest_method_success(self, questdb_stubs, tmp_path):
        """load_data with rest method should call _load_table_via_rest_api."""
        data_file = tmp_path / "lineitem.csv"
        data_file.write_text("col1\n1\n", encoding="utf-8")

        adapter = QuestDBAdapter(loading_method="rest")
        mock_benchmark = Mock()
        mock_benchmark.tables = {"lineitem": str(data_file)}

        with patch.object(adapter, "_load_table_via_rest_api", return_value=100) as mock_rest:
            stats, duration, _ = adapter.load_data(mock_benchmark, Mock(), tmp_path)

        mock_rest.assert_called_once_with("lineitem", data_file)
        assert stats["lineitem"] == 100

    def test_load_data_ilp_method_success(self, questdb_stubs, tmp_path):
        """load_data with ilp method should call _load_table_via_ilp."""
        data_file = tmp_path / "lineitem.csv"
        data_file.write_text("col1\n1\n", encoding="utf-8")

        adapter = QuestDBAdapter(loading_method="ilp")
        mock_benchmark = Mock()
        mock_benchmark.tables = {"lineitem": str(data_file)}

        with patch.object(adapter, "_load_table_via_ilp", return_value=50) as mock_ilp:
            stats, duration, _ = adapter.load_data(mock_benchmark, Mock(), tmp_path)

        mock_ilp.assert_called_once_with("lineitem", data_file)
        assert stats["lineitem"] == 50

    def test_load_data_rest_fails_falls_back_to_copy(self, questdb_stubs, tmp_path):
        """load_data should fall back to COPY when rest API fails."""
        data_file = tmp_path / "lineitem.csv"
        data_file.write_text("col1\n1\n", encoding="utf-8")

        adapter = QuestDBAdapter(loading_method="rest")
        mock_benchmark = Mock()
        mock_benchmark.tables = {"lineitem": str(data_file)}
        mock_conn = Mock()

        with (
            patch.object(adapter, "_load_table_via_rest_api", side_effect=Exception("HTTP 500")),
            patch.object(adapter, "_load_table_via_copy", return_value=99) as mock_copy,
        ):
            stats, duration, _ = adapter.load_data(mock_benchmark, mock_conn, tmp_path)

        mock_copy.assert_called_once_with(mock_conn, "lineitem", data_file)
        assert stats["lineitem"] == 99

    def test_load_data_rest_fails_copy_also_fails(self, questdb_stubs, tmp_path):
        """load_data should record 0 rows when both REST and COPY fail."""
        data_file = tmp_path / "lineitem.csv"
        data_file.write_text("col1\n1\n", encoding="utf-8")

        adapter = QuestDBAdapter(loading_method="rest")
        mock_benchmark = Mock()
        mock_benchmark.tables = {"lineitem": str(data_file)}

        with (
            patch.object(adapter, "_load_table_via_rest_api", side_effect=Exception("HTTP 500")),
            patch.object(adapter, "_load_table_via_copy", side_effect=Exception("COPY failed")),
        ):
            stats, duration, _ = adapter.load_data(mock_benchmark, Mock(), tmp_path)

        assert stats["lineitem"] == 0


class TestLoadTableViaRestApi:
    """Test REST API data loading helper."""

    def test_rest_api_rows_imported_from_json(self, questdb_stubs, tmp_path):
        """_load_table_via_rest_api should parse rowsImported from JSON response."""
        data_file = tmp_path / "test.csv"
        data_file.write_text("col1\n1\n2\n", encoding="utf-8")

        adapter = QuestDBAdapter(host="myhost", http_port=9000)

        mock_response = Mock()
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {"rowsImported": 42}
        mock_requests = Mock()
        mock_requests.post.return_value = mock_response

        with (
            patch.dict("sys.modules", {"requests": mock_requests}),
            patch.object(adapter, "_open_normalized_csv_stream", return_value=MagicMock()),
        ):
            count = adapter._load_table_via_rest_api("test_table", data_file)

        assert count == 42

    def test_rest_api_zero_rows_falls_back_to_count(self, questdb_stubs, tmp_path):
        """_load_table_via_rest_api should call _count_table_rows_via_http when rowsImported=0."""
        data_file = tmp_path / "test.csv"
        data_file.write_text("col1\n1\n", encoding="utf-8")

        adapter = QuestDBAdapter(host="myhost", http_port=9000)

        mock_response = Mock()
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {"rowsImported": 0}
        mock_requests = Mock()
        mock_requests.post.return_value = mock_response

        with (
            patch.dict("sys.modules", {"requests": mock_requests}),
            patch.object(adapter, "_open_normalized_csv_stream", return_value=MagicMock()),
            patch.object(adapter, "_count_table_rows_via_http", return_value=5) as mock_count,
        ):
            count = adapter._load_table_via_rest_api("test_table", data_file)

        mock_count.assert_called_once_with("test_table")
        assert count == 5

    def test_rest_api_non_json_response(self, questdb_stubs, tmp_path):
        """_load_table_via_rest_api handles non-JSON response by falling back to count."""
        data_file = tmp_path / "test.csv"
        data_file.write_text("col1\n1\n", encoding="utf-8")

        adapter = QuestDBAdapter(host="myhost", http_port=9000)

        mock_response = Mock()
        mock_response.headers = {"content-type": "text/plain"}
        mock_requests = Mock()
        mock_requests.post.return_value = mock_response

        with (
            patch.dict("sys.modules", {"requests": mock_requests}),
            patch.object(adapter, "_open_normalized_csv_stream", return_value=MagicMock()),
            patch.object(adapter, "_count_table_rows_via_http", return_value=10),
        ):
            count = adapter._load_table_via_rest_api("test_table", data_file)

        assert count == 10


class TestCountTableRowsViaHttp:
    """Test row count via HTTP helper."""

    def test_count_rows_success(self, questdb_stubs):
        """_count_table_rows_via_http should parse dataset response."""
        adapter = QuestDBAdapter(host="myhost", http_port=9000)

        mock_response = Mock()
        mock_response.json.return_value = {"dataset": [[123]]}
        mock_requests = Mock()
        mock_requests.get.return_value = mock_response

        with patch.dict("sys.modules", {"requests": mock_requests}):
            count = adapter._count_table_rows_via_http("lineitem")

        assert count == 123

    def test_count_rows_empty_dataset(self, questdb_stubs):
        """_count_table_rows_via_http should return 0 for empty dataset."""
        adapter = QuestDBAdapter(host="myhost", http_port=9000)

        mock_response = Mock()
        mock_response.json.return_value = {"dataset": []}
        mock_requests = Mock()
        mock_requests.get.return_value = mock_response

        with patch.dict("sys.modules", {"requests": mock_requests}):
            count = adapter._count_table_rows_via_http("lineitem")

        assert count == 0

    def test_count_rows_invalid_identifier(self, questdb_stubs):
        """_count_table_rows_via_http should return 0 for invalid identifier."""
        adapter = QuestDBAdapter(host="myhost", http_port=9000)
        count = adapter._count_table_rows_via_http("bad;name")
        assert count == 0

    def test_count_rows_request_exception(self, questdb_stubs):
        """_count_table_rows_via_http should return 0 on exception."""
        adapter = QuestDBAdapter(host="myhost", http_port=9000)

        mock_requests = Mock()
        mock_requests.get.side_effect = Exception("Connection refused")

        with patch.dict("sys.modules", {"requests": mock_requests}):
            count = adapter._count_table_rows_via_http("lineitem")

        assert count == 0


class TestGetTableColumns:
    """Test column fetching helper."""

    def test_get_table_columns_success(self, questdb_stubs):
        """_get_table_columns should return column names from SHOW COLUMNS response."""
        adapter = QuestDBAdapter(host="myhost", http_port=9000)

        mock_response = Mock()
        mock_response.json.return_value = {"dataset": [["col1", "INT"], ["col2", "VARCHAR"]]}
        mock_requests = Mock()
        mock_requests.get.return_value = mock_response

        with patch.dict("sys.modules", {"requests": mock_requests}):
            cols = adapter._get_table_columns("lineitem")

        assert cols == ["col1", "col2"]

    def test_get_table_columns_invalid_identifier(self, questdb_stubs):
        """_get_table_columns should return empty list for invalid identifier."""
        adapter = QuestDBAdapter(host="myhost", http_port=9000)
        cols = adapter._get_table_columns("bad;name")
        assert cols == []

    def test_get_table_columns_request_failure(self, questdb_stubs):
        """_get_table_columns should return empty list on exception."""
        adapter = QuestDBAdapter(host="myhost", http_port=9000)

        mock_requests = Mock()
        mock_requests.get.side_effect = Exception("Connection refused")

        with patch.dict("sys.modules", {"requests": mock_requests}):
            cols = adapter._get_table_columns("lineitem")

        assert cols == []

    def test_get_table_columns_uses_https_when_tls(self, questdb_stubs):
        """_get_table_columns should use HTTPS URL when use_tls=True."""
        adapter = QuestDBAdapter(host="myhost", http_port=9000, use_tls=True)

        mock_response = Mock()
        mock_response.json.return_value = {"dataset": []}
        mock_requests = Mock()
        mock_requests.get.return_value = mock_response

        with patch.dict("sys.modules", {"requests": mock_requests}):
            adapter._get_table_columns("test_table")

        url = mock_requests.get.call_args[0][0]
        assert url.startswith("https://")


class TestLoadTableViaIlp:
    """Test ILP data loading helper."""

    def test_ilp_raises_when_no_columns(self, questdb_stubs, tmp_path):
        """_load_table_via_ilp should raise RuntimeError when columns cannot be determined."""
        data_file = tmp_path / "test.csv"
        data_file.write_text("1|2|3\n", encoding="utf-8")

        adapter = QuestDBAdapter(ilp_host="localhost", ilp_port=9009)

        with patch.object(adapter, "_get_table_columns", return_value=[]):
            with pytest.raises(RuntimeError, match="Cannot determine column names"):
                adapter._load_table_via_ilp("unknown_table", data_file)

    def test_ilp_sends_rows_via_socket(self, questdb_stubs, tmp_path):
        """_load_table_via_ilp should send ILP lines over TCP socket."""
        data_file = tmp_path / "test.csv"
        data_file.write_text("1,hello,3.14\n2,world,2.71\n", encoding="utf-8")

        adapter = QuestDBAdapter(ilp_host="localhost", ilp_port=9009)

        mock_socket = Mock()
        with (
            patch.object(adapter, "_get_table_columns", return_value=["id", "name", "val"]),
            patch("benchbox.platforms.questdb.socket.socket", return_value=mock_socket),
        ):
            rows = adapter._load_table_via_ilp("test_table", data_file)

        assert rows == 2
        assert mock_socket.connect.called
        assert mock_socket.sendall.called

    def test_ilp_skips_rows_with_wrong_column_count(self, questdb_stubs, tmp_path):
        """_load_table_via_ilp should skip rows where column count doesn't match."""
        data_file = tmp_path / "test.csv"
        # 3 columns but data has 2 fields per row
        data_file.write_text("1,hello\n2,world\n", encoding="utf-8")

        adapter = QuestDBAdapter(ilp_host="localhost", ilp_port=9009)

        mock_socket = Mock()
        with (
            patch.object(adapter, "_get_table_columns", return_value=["id", "name", "extra"]),
            patch("benchbox.platforms.questdb.socket.socket", return_value=mock_socket),
        ):
            rows = adapter._load_table_via_ilp("test_table", data_file)

        assert rows == 0

    def test_ilp_flushes_in_batches(self, questdb_stubs, tmp_path):
        """_load_table_via_ilp should flush every 1000 rows."""
        # Create 1001 rows
        lines = "\n".join(f"{i},val" for i in range(1001)) + "\n"
        data_file = tmp_path / "test.csv"
        data_file.write_text(lines, encoding="utf-8")

        adapter = QuestDBAdapter(ilp_host="localhost", ilp_port=9009)

        mock_socket = Mock()
        with (
            patch.object(adapter, "_get_table_columns", return_value=["id", "name"]),
            patch("benchbox.platforms.questdb.socket.socket", return_value=mock_socket),
        ):
            rows = adapter._load_table_via_ilp("test_table", data_file)

        assert rows == 1001
        # Should have flushed at least once at the 1000 batch boundary
        assert mock_socket.sendall.call_count >= 2

    def test_ilp_socket_closed_on_error(self, questdb_stubs, tmp_path):
        """_load_table_via_ilp should close socket even when an error occurs."""
        data_file = tmp_path / "test.csv"
        data_file.write_text("1,hello\n", encoding="utf-8")

        adapter = QuestDBAdapter(ilp_host="localhost", ilp_port=9009)

        mock_socket = Mock()
        mock_socket.connect.side_effect = Exception("Connection refused")

        with (
            patch.object(adapter, "_get_table_columns", return_value=["id", "name"]),
            patch("benchbox.platforms.questdb.socket.socket", return_value=mock_socket),
            pytest.raises(Exception, match="Connection refused"),
        ):
            adapter._load_table_via_ilp("test_table", data_file)

        mock_socket.close.assert_called_once()


class TestRowToIlpLine:
    """Test ILP row conversion helper."""

    def test_row_to_ilp_line_basic(self):
        """_row_to_ilp_line should produce valid ILP format."""
        line = QuestDBAdapter._row_to_ilp_line(
            "test_table",
            ["id", "name", "val"],
            ["42", "hello", "3.14"],
            None,
        )
        assert line is not None
        assert "test_table" in line
        assert "id=42i" in line
        assert 'name="hello"' in line
        assert "val=3.14" in line

    def test_row_to_ilp_line_with_timestamp(self):
        """_row_to_ilp_line should handle designated timestamp column."""
        line = QuestDBAdapter._row_to_ilp_line(
            "orders",
            ["order_id", "o_orderdate"],
            ["1", "1994-01-01"],
            "o_orderdate",
        )
        assert line is not None
        # Timestamp should appear as epoch nanoseconds at end
        parts = line.split(" ")
        assert len(parts) >= 2
        # The last part should be a numeric timestamp
        assert parts[-1].isdigit()

    def test_row_to_ilp_line_empty_fields_returns_none(self):
        """_row_to_ilp_line should return None when all fields are empty."""
        line = QuestDBAdapter._row_to_ilp_line(
            "test",
            ["col1", "col2"],
            ["", ""],
            None,
        )
        assert line is None

    def test_row_to_ilp_line_skips_empty_values(self):
        """_row_to_ilp_line should skip individual empty values."""
        line = QuestDBAdapter._row_to_ilp_line(
            "test",
            ["col1", "col2", "col3"],
            ["42", "", "hello"],
            None,
        )
        assert line is not None
        assert "col1=42i" in line
        assert "col2" not in line

    def test_row_to_ilp_line_measurement_escape(self):
        """_row_to_ilp_line should escape the measurement name."""
        line = QuestDBAdapter._row_to_ilp_line(
            "my table",
            ["val"],
            ["1"],
            None,
        )
        assert line is not None
        assert r"my\ table" in line


class TestLoadTableViaCopy:
    """Test COPY-based loading fallback."""

    def test_load_via_copy_success(self, questdb_stubs, tmp_path):
        """_load_table_via_copy should use copy_expert and return row count."""
        data_file = tmp_path / "test.csv"
        data_file.write_text("col1\n1\n2\n3\n", encoding="utf-8")

        adapter = QuestDBAdapter()

        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = (3,)
        mock_conn = Mock()
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(adapter, "_open_normalized_csv_stream", return_value=MagicMock()):
            count = adapter._load_table_via_copy(mock_conn, "test_table", data_file)

        assert count == 3
        assert mock_cursor.copy_expert.called
        executed_sql = mock_cursor.execute.call_args[0][0]
        assert 'SELECT count() FROM "test_table"' in executed_sql


class TestOpenNormalizedCsvStream:
    """Test CSV stream normalization."""

    def test_non_tpc_file_text_mode_returns_open_file(self, questdb_stubs, tmp_path):
        """Non-TPC files in text mode should be returned as regular open file."""
        data_file = tmp_path / "data.csv"
        data_file.write_text("col1,col2\n1,hello\n", encoding="utf-8")

        adapter = QuestDBAdapter()
        with adapter._open_normalized_csv_stream(data_file, text_mode=True) as stream:
            content = stream.read()

        assert "col1,col2" in content

    def test_non_tpc_file_binary_mode(self, questdb_stubs, tmp_path):
        """Non-TPC files in binary mode should be returned as binary open file."""
        data_file = tmp_path / "data.csv"
        data_file.write_bytes(b"col1,col2\n1,hello\n")

        adapter = QuestDBAdapter()
        with adapter._open_normalized_csv_stream(data_file) as stream:
            content = stream.read()

        assert isinstance(content, bytes)

    def test_tpc_file_binary_strips_trailing_pipe(self, questdb_stubs, tmp_path):
        """TPC .tbl files in binary mode should strip trailing pipe characters."""
        data_file = tmp_path / "orders.tbl"
        data_file.write_bytes(b"1|2|3|\n4|5|6|\n")

        adapter = QuestDBAdapter()
        with adapter._open_normalized_csv_stream(data_file) as stream:
            content = stream.read()

        assert content == b"1|2|3\n4|5|6\n"

    def test_tpc_file_text_strips_trailing_pipe(self, questdb_stubs, tmp_path):
        """TPC .tbl files in text mode should strip trailing pipe characters."""
        data_file = tmp_path / "lineitem.tbl"
        data_file.write_text("1|2|3|\n4|5|6|\n", encoding="utf-8")

        adapter = QuestDBAdapter()
        with adapter._open_normalized_csv_stream(data_file, text_mode=True) as stream:
            content = stream.read()

        assert content == "1|2|3\n4|5|6\n"


class TestConfigureForBenchmarkBranches:
    """Test configure_for_benchmark branches."""

    @pytest.mark.parametrize("benchmark_type", ["tpch", "tpcds", "olap", "timeseries"])
    def test_configure_for_benchmark_sets_parallel_filter(self, questdb_stubs, benchmark_type):
        """configure_for_benchmark should enable parallel filter for all supported types."""
        adapter = QuestDBAdapter()
        mock_cursor = Mock()
        mock_conn = Mock()
        mock_conn.cursor.return_value = mock_cursor

        adapter.configure_for_benchmark(mock_conn, benchmark_type)

        executed = [c[0][0] for c in mock_cursor.execute.call_args_list]
        assert any("parallel.filter" in s for s in executed)

    def test_configure_for_benchmark_olap_sets_page_frame(self, questdb_stubs):
        """configure_for_benchmark with olap types should also set page frame max rows."""
        adapter = QuestDBAdapter()
        mock_cursor = Mock()
        mock_conn = Mock()
        mock_conn.cursor.return_value = mock_cursor

        adapter.configure_for_benchmark(mock_conn, "tpch")

        executed = [c[0][0] for c in mock_cursor.execute.call_args_list]
        assert any("page.frame.max.rows" in s for s in executed)

    def test_configure_for_benchmark_swallows_set_errors(self, questdb_stubs):
        """configure_for_benchmark should not raise when SET commands fail."""
        adapter = QuestDBAdapter()
        mock_cursor = Mock()
        mock_cursor.execute.side_effect = Exception("SET not supported")
        mock_conn = Mock()
        mock_conn.cursor.return_value = mock_cursor

        adapter.configure_for_benchmark(mock_conn, "tpch")
        mock_cursor.close.assert_called_once()

    def test_configure_for_benchmark_cursor_closed_always(self, questdb_stubs):
        """configure_for_benchmark should always close cursor."""
        adapter = QuestDBAdapter()
        mock_cursor = Mock()
        mock_conn = Mock()
        mock_conn.cursor.return_value = mock_cursor

        adapter.configure_for_benchmark(mock_conn, "unknown_type")

        mock_cursor.close.assert_called_once()


class TestApplyPlatformOptimizations:
    """Test platform optimization application."""

    def test_apply_platform_optimizations_sets_jit_and_parallel(self, questdb_stubs):
        """apply_platform_optimizations should configure parallel filter and JIT."""
        adapter = QuestDBAdapter()
        mock_cursor = Mock()
        mock_conn = Mock()
        mock_conn.cursor.return_value = mock_cursor

        adapter.apply_platform_optimizations(Mock(), mock_conn)

        executed = [c[0][0] for c in mock_cursor.execute.call_args_list]
        assert any("parallel.filter" in s for s in executed)
        assert any("jit" in s.lower() for s in executed)
        assert any("page.frame.max.rows" in s for s in executed)

    def test_apply_platform_optimizations_swallows_errors(self, questdb_stubs):
        """apply_platform_optimizations should not raise when SET commands fail."""
        adapter = QuestDBAdapter()
        mock_cursor = Mock()
        mock_cursor.execute.side_effect = Exception("SET not supported")
        mock_conn = Mock()
        mock_conn.cursor.return_value = mock_cursor

        adapter.apply_platform_optimizations(Mock(), mock_conn)
        mock_cursor.close.assert_called_once()


class TestApplyConstraintConfiguration:
    """Test that constraint configuration is a no-op for QuestDB."""

    def test_apply_constraint_configuration_is_noop(self, questdb_stubs):
        """apply_constraint_configuration should silently do nothing."""
        adapter = QuestDBAdapter()
        mock_conn = Mock()
        adapter.apply_constraint_configuration(Mock(), Mock(), mock_conn)
        mock_conn.cursor.assert_not_called()


class TestExecuteQueryWithValidation:
    """Test execute_query when row-count validation is enabled."""

    def test_execute_query_with_validation_calls_validator(self, questdb_stubs):
        """execute_query should call QueryValidator when validate_row_count=True and benchmark_type set."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = [(1,), (2,)]
        mock_conn.cursor.return_value = mock_cursor

        adapter = QuestDBAdapter()

        mock_validator_instance = Mock()
        mock_validator_instance.validate_query_result.return_value = None
        mock_validator_cls = Mock(return_value=mock_validator_instance)

        with patch("benchbox.core.validation.query_validation.QueryValidator", mock_validator_cls):
            adapter.execute_query(
                mock_conn,
                "SELECT * FROM lineitem",
                "Q1",
                benchmark_type="tpch",
                scale_factor=1.0,
                validate_row_count=True,
            )

        mock_validator_instance.validate_query_result.assert_called_once()

    def test_execute_query_no_validation_when_no_benchmark_type(self, questdb_stubs):
        """execute_query should skip validation when benchmark_type is None."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = [(1,)]
        mock_conn.cursor.return_value = mock_cursor

        adapter = QuestDBAdapter()

        result = adapter.execute_query(
            mock_conn,
            "SELECT 1",
            "Q1",
            validate_row_count=True,
            benchmark_type=None,
        )
        assert result["status"] == "SUCCESS"


class TestGetPlatformInfoVersionError:
    """Test get_platform_info when version query fails."""

    def test_get_platform_info_version_query_fails(self, questdb_stubs):
        """get_platform_info should set version='unknown' when version query fails."""
        adapter = QuestDBAdapter()

        mock_cursor = Mock()
        mock_cursor.execute.side_effect = Exception("Column not found")
        mock_conn = Mock()
        mock_conn.cursor.return_value = mock_cursor

        info = adapter.get_platform_info(connection=mock_conn)

        assert info["version"] == "unknown"

    def test_get_platform_info_configuration_block(self, questdb_stubs):
        """get_platform_info should include configuration sub-dict."""
        adapter = QuestDBAdapter(
            loading_method="ilp",
            partition_by="DAY",
            ilp_port=9009,
        )

        info = adapter.get_platform_info()

        assert info["configuration"]["loading_method"] == "ilp"
        assert info["configuration"]["partition_by"] == "DAY"
        assert info["configuration"]["ilp_port"] == 9009


class TestTableOperationErrorBranches:
    """Test exception handling in table operations."""

    def test_table_exists_exception_returns_false(self, questdb_stubs):
        """table_exists should return False when cursor raises."""
        mock_cursor = Mock()
        mock_cursor.execute.side_effect = Exception("Query failed")
        mock_conn = Mock()
        mock_conn.cursor.return_value = mock_cursor

        adapter = QuestDBAdapter()
        result = adapter.table_exists(mock_conn, "lineitem")
        assert result is False

    def test_drop_table_exception_logs_warning(self, questdb_stubs):
        """drop_table should log warning and not raise when cursor fails."""
        mock_cursor = Mock()
        mock_cursor.execute.side_effect = Exception("Drop failed")
        mock_conn = Mock()
        mock_conn.cursor.return_value = mock_cursor

        adapter = QuestDBAdapter()
        adapter.drop_table(mock_conn, "lineitem")


class TestIlpHelpers:
    """Test ILP helper utility functions."""

    def test_ilp_escape_measurement_special_chars(self):
        """_ilp_escape_measurement should escape commas, spaces, and equals."""
        assert _ilp_escape_measurement("my,table") == r"my\,table"
        assert _ilp_escape_measurement("my table") == r"my\ table"
        assert _ilp_escape_measurement("my=table") == r"my\=table"

    def test_ilp_escape_measurement_clean_name(self):
        """_ilp_escape_measurement should leave clean names unchanged."""
        assert _ilp_escape_measurement("lineitem") == "lineitem"

    def test_ilp_escape_tag_key_special_chars(self):
        """_ilp_escape_tag_key should escape commas, equals, and spaces."""
        assert _ilp_escape_tag_key("my,key") == r"my\,key"
        assert _ilp_escape_tag_key("my=key") == r"my\=key"
        assert _ilp_escape_tag_key("my key") == r"my\ key"

    def test_ilp_escape_field_integer(self):
        """_ilp_escape_field should format integers with 'i' suffix."""
        result = _ilp_escape_field("count", "42")
        assert result == "count=42i"

    def test_ilp_escape_field_float(self):
        """_ilp_escape_field should format floats without suffix."""
        result = _ilp_escape_field("price", "3.14")
        assert result == "price=3.14"

    def test_ilp_escape_field_string(self):
        """_ilp_escape_field should wrap strings in double quotes."""
        result = _ilp_escape_field("name", "hello")
        assert result == 'name="hello"'

    def test_ilp_escape_field_empty_returns_none(self):
        """_ilp_escape_field should return None for empty value."""
        result = _ilp_escape_field("name", "")
        assert result is None

    def test_ilp_escape_field_string_with_quotes(self):
        """_ilp_escape_field should escape backslashes and double quotes in strings."""
        result = _ilp_escape_field("name", 'say "hello"')
        assert result == 'name="say \\"hello\\""'

    def test_ilp_escape_field_negative_integer(self):
        """_ilp_escape_field should handle negative integers."""
        result = _ilp_escape_field("delta", "-5")
        assert result == "delta=-5i"

    def test_ilp_escape_field_scientific_notation(self):
        """_ilp_escape_field should handle scientific notation floats."""
        result = _ilp_escape_field("val", "1.23e10")
        assert result is not None
        assert "val=" in result


class TestDateToEpochNs:
    """Test date to nanosecond epoch conversion."""

    def test_date_format_yyyy_mm_dd(self):
        """Should convert YYYY-MM-DD format to nanosecond epoch."""
        result = _date_to_epoch_ns("1994-01-01")
        assert result is not None
        assert result.isdigit()
        # 1994-01-01 is after Unix epoch
        assert int(result) > 0

    def test_date_format_datetime(self):
        """Should convert YYYY-MM-DD HH:MM:SS format."""
        result = _date_to_epoch_ns("1994-01-01 12:30:00")
        assert result is not None
        assert result.isdigit()

    def test_date_format_iso_datetime(self):
        """Should convert YYYY-MM-DDTHH:MM:SS format."""
        result = _date_to_epoch_ns("1994-01-01T12:30:00")
        assert result is not None
        assert result.isdigit()

    def test_invalid_date_returns_none(self):
        """Should return None for invalid date strings."""
        result = _date_to_epoch_ns("not-a-date")
        assert result is None

    def test_empty_string_returns_none(self):
        """Should return None for empty string."""
        result = _date_to_epoch_ns("   ")
        assert result is None

    def test_epoch_ns_is_nanoseconds(self):
        """Epoch value should be in nanoseconds (1e18 magnitude for year 2000)."""
        result = _date_to_epoch_ns("2000-01-01")
        assert result is not None
        # Year 2000 in nanoseconds: ~9.46e17
        assert int(result) > 9 * 10**17


class TestAdapterInitEdgeCases:
    """Test adapter initialization edge cases."""

    def test_ilp_host_defaults_to_host(self, questdb_stubs):
        """ilp_host should default to host when not explicitly set."""
        adapter = QuestDBAdapter(host="myhost")
        assert adapter.ilp_host == "myhost"

    def test_ilp_host_explicit_override(self, questdb_stubs):
        """ilp_host should use explicit value when provided."""
        adapter = QuestDBAdapter(host="pghost", ilp_host="ilphost")
        assert adapter.ilp_host == "ilphost"

    def test_default_loading_method(self, questdb_stubs):
        """Default loading method should be 'rest'."""
        adapter = QuestDBAdapter()
        assert adapter.loading_method == "rest"

    def test_ilp_loading_method(self, questdb_stubs):
        """Can configure ilp loading method."""
        adapter = QuestDBAdapter(loading_method="ilp")
        assert adapter.loading_method == "ilp"

    def test_partition_by_none_by_default(self, questdb_stubs):
        """partition_by should be None by default (auto per table)."""
        adapter = QuestDBAdapter()
        assert adapter.partition_by is None

    def test_connect_timeout_default(self, questdb_stubs):
        """connect_timeout should default to 10."""
        adapter = QuestDBAdapter()
        assert adapter.connect_timeout == 10

    def test_connect_timeout_custom(self, questdb_stubs):
        """connect_timeout should accept custom value."""
        adapter = QuestDBAdapter(connect_timeout=30)
        assert adapter.connect_timeout == 30
