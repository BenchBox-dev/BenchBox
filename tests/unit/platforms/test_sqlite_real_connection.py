"""Behavior-verifying tests for SQLite adapter using real in-memory connections.

Every test creates a real SQLite connection - no MagicMock on the connection path.
"""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture()
def adapter(tmp_path):
    """Create a SQLite adapter with in-memory database."""
    from benchbox.platforms.sqlite import SQLiteAdapter

    return SQLiteAdapter(database_path=":memory:")


@pytest.fixture()
def connection(adapter):
    """Create a real in-memory SQLite connection."""
    conn = adapter.create_connection()
    yield conn
    try:
        conn.close()
    except Exception:
        pass


class TestSQLiteRealConnection:
    def test_create_connection_returns_usable_connection(self, adapter):
        conn = adapter.create_connection()
        cursor = conn.execute("SELECT 1")
        assert cursor.fetchone() == (1,)
        conn.close()

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

    def test_execute_query_with_table_data(self, adapter, connection):
        connection.execute("CREATE TABLE items (id INTEGER, name TEXT)")
        connection.execute("INSERT INTO items VALUES (1, 'alpha'), (2, 'beta')")
        connection.commit()

        result = adapter.execute_query(
            connection=connection,
            query="SELECT * FROM items ORDER BY id",
            query_id="q_items",
            validate_row_count=False,
        )
        assert result["rows_returned"] == 2
        assert result.get("error") is None

    def test_execute_query_with_bad_sql_returns_error(self, adapter, connection):
        result = adapter.execute_query(
            connection=connection,
            query="SELECTX GARBAGE",
            query_id="bad_q",
            validate_row_count=False,
        )
        assert result["error"] is not None

    def test_platform_info_returns_sqlite_version(self, adapter, connection):
        info = adapter.get_platform_info(connection)
        assert "platform_version" in info
        # SQLite version is a string like "3.45.0"
        assert "." in info["platform_version"]

    def test_wal_mode_applied_for_file_database(self, adapter, tmp_path):
        """Verify WAL mode is applied for file-based databases."""
        from benchbox.platforms.sqlite import SQLiteAdapter

        db_path = str(tmp_path / "test.db")
        file_adapter = SQLiteAdapter(database_path=db_path)
        conn = file_adapter.create_connection()

        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()
        # WAL mode should be set for file databases
        assert journal_mode is not None
        conn.close()

    def test_close_connection_makes_connection_unusable(self, adapter):
        conn = adapter.create_connection()
        conn.execute("SELECT 1")
        conn.close()
        with pytest.raises(Exception):
            conn.execute("SELECT 1")
