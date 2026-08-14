"""Executable characterization prototypes for the SQL composition boundary."""

from __future__ import annotations

from typing import Any

import pytest

from benchbox.core.benchmark_mixins import CursorValidationQueryExecutionMixin
from benchbox.platforms.base.sql_execution import execute_sql_query

pytestmark = [pytest.mark.unit, pytest.mark.fast]


class _Cursor:
    def __init__(self, *, rows: list[tuple[Any, ...]] | None = None, error: Exception | None = None) -> None:
        self.rows = rows or []
        self.error = error
        self.connection: _Connection | None = None
        self.closed = False

    def execute(self, _query: str) -> None:
        if self.error is not None:
            raise self.error

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows

    def close(self) -> None:
        self.closed = True


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor
        self._cursor.connection = self
        self.rollback_count = 0

    def cursor(self) -> _Cursor:
        return self._cursor

    def rollback(self) -> None:
        self.rollback_count += 1


class _CoreHooks:
    """Minimal hooks required by the core mixin prototype."""

    def log_verbose(self, _message: str) -> None:
        pass

    def log_very_verbose(self, _message: str) -> None:
        pass

    def _build_query_result_with_validation(self, **kwargs: Any) -> dict[str, Any]:
        return {"status": "SUCCESS", **kwargs}


class _CoreSqlPrototype(CursorValidationQueryExecutionMixin, _CoreHooks):
    """Option A prototype: core owns cursor-based SQL execution behavior."""


def _platform_injected_prototype(
    connection_or_cursor: Any,
    *,
    hooks: _CoreHooks,
) -> dict[str, Any]:
    """Option B prototype: a platform helper receives core result callbacks."""
    return execute_sql_query(
        connection_or_cursor,
        "SELECT 1",
        "q1",
        log_verbose=hooks.log_verbose,
        build_query_result_with_validation=hooks._build_query_result_with_validation,
    )


def test_sql_prototypes_characterize_success_contracts() -> None:
    """The two incumbents differ even on a successful one-row query."""
    core_cursor = _Cursor(rows=[(1,)])
    core_connection = _Connection(core_cursor)
    core_result = _CoreSqlPrototype().execute_query(core_connection, "SELECT 1", "q1")

    platform_cursor = _Cursor(rows=[(1,)])
    platform_connection = _Connection(platform_cursor)
    platform_result = _platform_injected_prototype(platform_cursor, hooks=_CoreHooks())

    assert core_result["query_statistics"] is core_result["resource_usage"]
    assert "query_statistics" not in platform_result
    assert core_cursor.closed is True
    assert platform_cursor.closed is False
    assert platform_cursor.connection is platform_connection


def test_sql_prototypes_characterize_failure_recovery_contracts() -> None:
    """The platform helper rolls back failures; the core mixin does not."""
    core_cursor = _Cursor(error=RuntimeError("core failure"))
    core_connection = _Connection(core_cursor)
    core_result = _CoreSqlPrototype().execute_query(core_connection, "SELECT 1", "q1")

    platform_cursor = _Cursor(error=RuntimeError("platform failure"))
    platform_connection = _Connection(platform_cursor)
    platform_result = _platform_injected_prototype(platform_cursor, hooks=_CoreHooks())

    assert core_result["status"] == "FAILED"
    assert platform_result["status"] == "FAILED"
    assert core_connection.rollback_count == 0
    assert platform_connection.rollback_count == 1
    assert core_cursor.closed is True
    assert platform_cursor.closed is False
