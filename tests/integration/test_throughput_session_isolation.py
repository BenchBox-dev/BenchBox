# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""Integration tests for the per-stream session capability
(``throughput-independent-sessions-per-stream``).

The production throughput drivers (``benchbox/platforms/base/execution.py``
``_execute_tpch_throughput_test`` / ``_execute_tpcds_throughput_test``) hand
each concurrent stream a ``connection_factory()`` call. Before this fix that
factory unconditionally called ``_make_stream_cursor(connection)`` -
returning a cursor of ONE shared platform connection to every stream. That is
correct and intentional for DuckDB (its Python client is documented
thread-safe only at the cursor level against one process-local database -
see docs/benchmarks/tpc-h.md), but TPC throughput semantics model N
INDEPENDENT concurrent sessions, and for client/server engines (psycopg,
Snowflake, Databricks SQL, Trino, ...) a single connection is a single
session: many DB-API drivers serialize or raise across cursors of one
connection, and even where they don't, every "stream" would share one
session's server-side state instead of measuring real multi-user
concurrency.

The fix makes per-stream connection acquisition a platform capability -
``StreamConnectionCapability`` (``benchbox/platforms/base/connection_wrappers.py``)
plus the ``PlatformAdapter.new_stream_connection()`` hook
(``benchbox/platforms/base/adapter.py``) that the throughput
``connection_factory`` closures now call instead of ``_make_stream_cursor``
directly. This module proves both sides of that capability fork with real
engines (real DuckDB, real sqlite3) rather than mocks:

- ``TestSharedCursorCapabilityIsDuckDBDefault``: DuckDB does not override the
  capability, so it stays on ``SHARED_CURSOR`` - the anti-pattern this TODO
  explicitly forbids ("DO NOT open N real connections for embedded DuckDB")
  is pinned by showing a plain table created via one stream's handle is
  immediately visible via another stream's handle, proving they share one
  connection/session with zero extra connections opened.
- ``TestIndependentConnectionCapabilityIsolatesSessions``: a minimal
  SQLite-per-connection stand-in for a server-style engine (each stream gets
  its own ``sqlite3.connect()`` against the same on-disk file, modeling one
  connection == one session) declares ``INDEPENDENT_CONNECTION`` and proves
  real session isolation: a ``CREATE TEMP TABLE`` (SQLite's connection-scoped,
  session-local construct - the closest single-process analog to a
  Postgres-style ``SET`` session variable) made by one stream is invisible to
  another.

SQLite is used instead of Postgres/docker per the TODO's own guidance
(``throughput-independent-sessions-per-stream-per-stream.yaml`` work item
w3): a stand-in server-style engine models the connection-is-a-session
property just as faithfully, with no docker dependency and no network I/O -
much faster and more reliable for CI.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from benchbox.platforms.base.adapter import PlatformAdapter
from benchbox.platforms.base.connection_wrappers import (
    PlatformAdapterConnection,
    StreamConnectionCapability,
)
from benchbox.platforms.duckdb import DuckDBAdapter

pytestmark = [
    pytest.mark.integration,
]


class _SQLiteServerStyleAdapter(PlatformAdapter):
    """Minimal server-style adapter stand-in for this test only.

    Declares ``INDEPENDENT_CONNECTION`` and overrides ``new_stream_connection``
    to open a brand-new ``sqlite3`` connection against the same on-disk file
    for every stream - modeling a client/server engine where "one connection"
    IS "one session", the property real server engines (psycopg, Snowflake,
    Databricks SQL, Trino, ...) share and DuckDB does not.

    Not a real platform adapter registered anywhere - it exists purely to
    exercise the ``new_stream_connection()`` capability seam against a real
    (if minimal) database engine instead of a bare ``Mock``.
    """

    stream_connection_capability = StreamConnectionCapability.INDEPENDENT_CONNECTION

    def __init__(self, db_path: str, **config: Any) -> None:
        super().__init__(**config)
        self._db_path = db_path

    @staticmethod
    def add_cli_arguments(parser) -> None:
        pass

    @classmethod
    def from_config(cls, config: dict[str, Any]):
        return cls(db_path=config["db_path"])

    def get_target_dialect(self) -> str | None:
        return "sqlite"

    def create_connection(self, **connection_config: Any) -> Any:
        return sqlite3.connect(self._db_path)

    def create_schema(self, benchmark, connection: Any) -> float:
        return 0.0

    def apply_platform_optimizations(self, platform_config, connection: Any) -> None:
        pass

    def apply_constraint_configuration(self, primary_key_config, foreign_key_config, connection: Any) -> None:
        pass

    def load_data(self, benchmark, connection: Any, data_dir):
        return {}, 0.0, None

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        pass

    def execute_query(
        self,
        connection: Any,
        query: str,
        query_id: str,
        benchmark_type: str | None = None,
        scale_factor: float | None = None,
        validate_row_count: bool = True,
        stream_id: int | None = None,
    ) -> dict[str, Any]:
        cursor = connection.execute(query)
        rows = cursor.fetchall()
        return {
            "query_id": query_id,
            "status": "SUCCESS",
            "execution_time_seconds": 0.0,
            "rows_returned": len(rows),
            "rows": rows,
        }

    def new_stream_connection(self, connection: Any) -> Any:
        # Server-style override: ignore the shared `connection` handed in and
        # open a brand-new connection/session per stream. This is the
        # override contract StreamConnectionCapability.INDEPENDENT_CONNECTION
        # requires (see PlatformAdapter.new_stream_connection docstring).
        return sqlite3.connect(self._db_path)


def _stream_wrapper(adapter: PlatformAdapter, shared_connection: Any) -> PlatformAdapterConnection:
    """Reproduce exactly what execution.py's throughput connection_factory
    closures now do per stream: ``PlatformAdapterConnection(adapter.new_stream_connection(shared_connection), adapter)``."""
    stream_connection = adapter.new_stream_connection(shared_connection)
    return PlatformAdapterConnection(stream_connection, adapter)


class TestIndependentConnectionCapabilityIsolatesSessions:
    """Server-style stand-in (SQLite-per-connection): streams get isolated sessions."""

    def test_temp_table_does_not_leak_across_streams(self, tmp_path) -> None:
        """A session-local value (SQLite TEMP TABLE) set in one stream must be
        invisible from another stream - proving each stream has its OWN
        connection/session, not a cursor of a shared one."""
        db_path = str(tmp_path / "server_style.db")
        adapter = _SQLiteServerStyleAdapter(db_path=db_path)
        assert adapter.stream_connection_capability is StreamConnectionCapability.INDEPENDENT_CONNECTION

        shared_connection = adapter.create_connection()
        try:
            stream_a = _stream_wrapper(adapter, shared_connection)
            stream_b = _stream_wrapper(adapter, shared_connection)
            try:
                # Sanity: each stream really did get its own connection object,
                # distinct from each other AND from the shared connection.
                assert stream_a.connection is not stream_b.connection
                assert stream_a.connection is not shared_connection
                assert stream_b.connection is not shared_connection

                # Stream A sets session-local state (a TEMP TABLE is private
                # to the connection that created it in SQLite).
                stream_a.execute("CREATE TEMP TABLE stream_local (value INTEGER)")
                stream_a.execute("INSERT INTO stream_local VALUES (42)")
                assert stream_a.execute("SELECT value FROM stream_local").fetchall() == [(42,)]

                # Stream B's independent session must NOT see it.
                with pytest.raises(sqlite3.OperationalError, match="no such table"):
                    stream_b.execute("SELECT value FROM stream_local")
            finally:
                stream_a.close()
                stream_b.close()
        finally:
            shared_connection.close()

    def test_undeclared_override_fails_fast(self) -> None:
        """A subclass that declares INDEPENDENT_CONNECTION but forgets to
        override new_stream_connection() must fail loudly, not silently fall
        back to cursor sharing (the exact bug this capability fixes)."""

        class _ForgotToOverride(_SQLiteServerStyleAdapter):
            # Inherits stream_connection_capability = INDEPENDENT_CONNECTION
            # from _SQLiteServerStyleAdapter, but explicitly restores the
            # base (unoverridden) hook implementation instead of the
            # parent's working override.
            new_stream_connection = PlatformAdapter.new_stream_connection

        adapter = _ForgotToOverride(db_path=":memory:")
        with pytest.raises(NotImplementedError, match="INDEPENDENT_CONNECTION"):
            adapter.new_stream_connection(object())


class TestSharedCursorCapabilityIsDuckDBDefault:
    """DuckDB pins the SHARED_CURSOR default: the anti_pattern this TODO
    forbids ("DO NOT open N real connections for embedded DuckDB") stays
    fixed - no capability override, no extra connections."""

    def test_duckdb_does_not_override_capability(self) -> None:
        adapter = DuckDBAdapter()
        assert adapter.stream_connection_capability is StreamConnectionCapability.SHARED_CURSOR
        # DuckDBAdapter must not override the hook either - confirms the fast
        # path is exercised via the base implementation, not a platform-local
        # reimplementation that could silently drift from it.
        assert type(adapter).new_stream_connection is PlatformAdapter.new_stream_connection

    def test_streams_share_one_connection_no_new_connections_opened(self) -> None:
        """Two streams' handles must both operate against the SAME
        underlying DuckDB connection/session (the fast path documented in
        docs/benchmarks/tpc-h.md), not independent connections."""
        adapter = DuckDBAdapter()
        shared_connection = adapter.create_connection()
        try:
            stream_a = _stream_wrapper(adapter, shared_connection)
            stream_b = _stream_wrapper(adapter, shared_connection)

            # A plain (non-TEMP) table created via stream A's cursor is
            # immediately visible via stream B's cursor: both cursors share
            # one connection's catalog/session, exactly as before this fix -
            # zero new connections were opened to get stream B its handle.
            stream_a.execute("CREATE TABLE shared_state (value INTEGER)")
            stream_a.execute("INSERT INTO shared_state VALUES (7)")
            assert stream_b.execute("SELECT value FROM shared_state").fetchall() == [(7,)]

            # Closing a stream's cursor must not tear down the shared
            # connection out from under the other stream (must_preserve:
            # connections are still closed per stream in _execute_stream's
            # finally block).
            stream_a.close()
            assert stream_b.execute("SELECT value FROM shared_state").fetchall() == [(7,)]
        finally:
            shared_connection.close()
