"""Behavior-verifying tests for DuckDB adapter using real in-memory connections.

These tests replace mock-heavy coverage tests with real database operations.
Every test creates a real DuckDB connection - no MagicMock on the connection path.
"""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture()
def adapter():
    """Create a DuckDB adapter with in-memory database."""
    from benchbox.platforms.duckdb import DuckDBAdapter

    return DuckDBAdapter(database_path=":memory:", memory_limit="256MB")


@pytest.fixture()
def connection(adapter):
    """Create a real in-memory DuckDB connection."""
    conn = adapter.create_connection()
    yield conn
    try:
        conn.close()
    except Exception:
        pass


class TestDuckDBRealConnection:
    def test_create_connection_returns_usable_connection(self, adapter):
        conn = adapter.create_connection()
        result = conn.execute("SELECT 1 AS x").fetchone()
        assert result == (1,)
        conn.close()

    def test_memory_limit_is_applied(self, connection):
        row = connection.execute("SELECT current_setting('memory_limit')").fetchone()
        assert row is not None
        # DuckDB reports memory in human-readable form, e.g. "244.1 MiB"
        value = row[0].lower()
        assert "mib" in value or "mb" in value or "gib" in value

    def test_execute_query_returns_result_dict(self, adapter, connection):
        result = adapter.execute_query(
            connection=connection,
            query="SELECT 42 AS answer",
            query_id="test_q1",
            validate_row_count=False,
        )
        assert result["query_id"] == "test_q1"
        assert result["execution_time_seconds"] >= 0
        assert result["rows_returned"] == 1
        assert result["first_row"] is not None

    def test_execute_query_captures_row_count(self, adapter, connection):
        connection.execute("CREATE TABLE test_tbl (id INT, name VARCHAR)")
        connection.execute("INSERT INTO test_tbl VALUES (1, 'a'), (2, 'b'), (3, 'c')")
        result = adapter.execute_query(
            connection=connection,
            query="SELECT * FROM test_tbl",
            query_id="test_q2",
            validate_row_count=False,
        )
        assert result["rows_returned"] == 3

    def test_execute_query_with_malformed_sql_returns_error(self, adapter, connection):
        result = adapter.execute_query(
            connection=connection,
            query="SELECTX INVALID SQL!!!",
            query_id="bad_q",
            validate_row_count=False,
        )
        assert "error" in result
        assert result["rows_returned"] == 0

    def test_real_sql_execution_with_tables(self, adapter, connection):
        """Verify table creation and querying works end-to-end."""
        connection.execute("CREATE TABLE region (r_regionkey INTEGER, r_name VARCHAR(25))")
        connection.execute("INSERT INTO region VALUES (0, 'AFRICA'), (1, 'AMERICA'), (2, 'ASIA')")

        result = adapter.execute_query(
            connection=connection,
            query="SELECT r_name FROM region WHERE r_regionkey = 1",
            query_id="schema_q",
            validate_row_count=False,
        )
        assert result["rows_returned"] == 1
        assert result["first_row"][0] == "AMERICA"

    def test_platform_info_returns_real_version(self, adapter, connection):
        info = adapter.get_platform_info(connection)
        assert "platform_version" in info
        # DuckDB version is a string like "v1.2.0"
        assert "." in info["platform_version"]

    def test_from_config_creates_working_adapter(self, tmp_path):
        from benchbox.platforms.duckdb import DuckDBAdapter

        adapter = DuckDBAdapter.from_config(
            {
                "benchmark": "tpch",
                "scale_factor": 0.01,
                "output_dir": str(tmp_path),
                "memory_limit": "128MB",
            }
        )
        conn = adapter.create_connection()
        result = conn.execute("SELECT 1 + 1").fetchone()
        assert result == (2,)
        conn.close()

    def test_close_connection_makes_connection_unusable(self, adapter):
        conn = adapter.create_connection()
        conn.execute("SELECT 1")  # works
        conn.close()
        with pytest.raises(Exception):
            conn.execute("SELECT 1")  # should fail after close
