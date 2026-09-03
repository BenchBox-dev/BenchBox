"""Unit tests for post-benchmark statement overhead probe."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from benchbox.platforms.base.link_probe import probe_statement_overhead

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class _MockCursor:
    def __init__(self) -> None:
        self.executed_queries: list[str] = []
        self.closed = False

    def execute(self, query: str) -> None:
        self.executed_queries.append(query)

    def fetchall(self) -> list[tuple[int]]:
        return [(1,)]

    def close(self) -> None:
        self.closed = True


class _MockConnection:
    def __init__(self, cursor: _MockCursor | None = None) -> None:
        self._cursor = cursor or _MockCursor()

    def cursor(self) -> _MockCursor:
        return self._cursor


def test_probe_statement_overhead_success() -> None:
    cursor = _MockCursor()
    conn = _MockConnection(cursor)

    result = probe_statement_overhead(conn, timeout_seconds=5.0, sample_count=5)

    assert result["collection_status"] == "available"
    assert result["source"] == "observed"
    overhead = result["statement_overhead_ms"]
    assert overhead["samples"] == 5
    assert overhead["min"] >= 0.0
    assert overhead["median"] >= 0.0
    assert overhead["min"] <= overhead["median"]
    # 1 warmup + 5 measurement queries = 6 total SELECT 1
    assert len(cursor.executed_queries) == 6
    assert all(q == "SELECT 1" for q in cursor.executed_queries)
    assert cursor.closed is True


def test_probe_statement_overhead_custom_sample_count() -> None:
    cursor = _MockCursor()
    conn = _MockConnection(cursor)

    result = probe_statement_overhead(conn, timeout_seconds=5.0, sample_count=3)

    assert result["collection_status"] == "available"
    overhead = result["statement_overhead_ms"]
    assert overhead["samples"] == 3
    # 1 warmup + 3 measurement queries = 4 total
    assert len(cursor.executed_queries) == 4
    assert cursor.closed is True


def test_probe_statement_overhead_none_connection() -> None:
    result = probe_statement_overhead(None)
    assert result["collection_status"] == "partial"
    assert result["source"] == "unavailable"
    assert result["collection_error_class"] == "ValueError"
    assert "No active database connection" in result["collection_error_message"]


def test_probe_statement_overhead_missing_cursor() -> None:
    class _NoCursorClient:
        pass

    result = probe_statement_overhead(_NoCursorClient())
    assert result["collection_status"] == "partial"
    assert result["source"] == "unavailable"
    assert result["collection_error_class"] == "AttributeError"
    assert "cursor" in result["collection_error_message"]


def test_probe_statement_overhead_execution_failure() -> None:
    class _FailingCursor:
        def __init__(self) -> None:
            self.closed = False

        def execute(self, query: str) -> None:
            raise RuntimeError("Database execution failed")

        def close(self) -> None:
            self.closed = True

    cursor = _FailingCursor()
    conn = MagicMock()
    conn.cursor.return_value = cursor

    result = probe_statement_overhead(conn)
    assert result["collection_status"] == "partial"
    assert result["source"] == "unavailable"
    assert result["collection_error_class"] == "RuntimeError"
    assert "Database execution failed" in result["collection_error_message"]
    assert cursor.closed is True


def test_probe_statement_overhead_timeout_deadline() -> None:
    cursor = _MockCursor()
    conn = _MockConnection(cursor)

    with patch("benchbox.platforms.base.link_probe.mono_time", side_effect=[0.0, 10.0, 20.0]):
        result = probe_statement_overhead(conn, timeout_seconds=1.0, sample_count=5)

    assert result["collection_status"] == "partial"
    assert result["source"] == "unavailable"
    assert result["collection_error_class"] == "TimeoutError"
    assert "timed out" in result["collection_error_message"]
    assert cursor.closed is True
