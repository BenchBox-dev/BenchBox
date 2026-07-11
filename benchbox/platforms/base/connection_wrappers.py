"""Connection-wrapping primitives for PlatformAdapter.

Extracted from `benchbox.platforms.base.adapter` per the refactor map
(`docs/development/adapter-refactor-map.md` Slice 3b). Houses:

- `DriverIsolationCapability` - enum declaring driver-isolation support
- `check_isolation_capability` - gate used by the adapter factory
- `_NoCloseProxy` / `_make_stream_cursor` - per-stream cursor helpers
- `PlatformAdapterConnection` - validation-capable connection wrapper
  used by TPC test runners
- `PlatformAdapterCursor` - cursor-like view over platform-adapter
  execution results

External imports (``from benchbox.platforms.base.adapter import ...``)
continue to work via re-exports in `adapter.py`.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from benchbox.platforms.base.adapter import PlatformAdapter

logger = logging.getLogger(__name__)


class DriverIsolationCapability(Enum):
    """Declares whether a platform adapter supports isolated driver runtime binding.

    This replaces the implicit ``getattr(cls, "supports_driver_runtime_isolation", False)``
    pattern with an explicit, discoverable capability declaration.

    Values:
        SUPPORTED: Adapter supports isolated-site-packages runtime binding with live
            version verification (e.g. DuckDB, DataFusion).
        NOT_APPLICABLE: Isolation is meaningless for this platform - no versioned driver
            package (e.g. SQLite, DataFrame-only platforms, SDK-based cloud services).
        NOT_FEASIBLE: Platform has a driver package but isolation is blocked by technical
            constraints (e.g. JVM-backed, native C driver, shared library conflicts).
        FEASIBLE_CLIENT_ONLY: Client package can be isolated, but it only controls the
            Python client version - engine version is managed independently by the
            remote service (e.g. Snowflake, BigQuery, Redshift).
    """

    SUPPORTED = "supported"
    NOT_APPLICABLE = "not_applicable"
    NOT_FEASIBLE = "not_feasible"
    FEASIBLE_CLIENT_ONLY = "feasible_client_only"


class StreamConnectionCapability(Enum):
    """Declares how a platform adapter hands each concurrent throughput/pool-test
    stream its query-execution handle.

    This is the seam that closes the gap described in
    ``throughput-independent-sessions-per-stream``: the production throughput
    drivers give every concurrent stream a ``connection_factory()`` call
    (``benchbox/platforms/base/execution.py``), but until this capability
    existed every adapter answered that call the same way - a cursor of one
    shared connection - regardless of whether the underlying engine actually
    models concurrency at the connection level.

    Values:
        SHARED_CURSOR: (default) The adapter's single underlying connection is
            safe to share across concurrent stream threads via one cursor per
            stream (``_make_stream_cursor`` - a DB-API cursor, or a
            ``_NoCloseProxy`` for execute-only clients). This is the correct,
            documented fast path for embedded engines whose Python client is
            thread-safe at cursor level against one process-local database
            (e.g. DuckDB - see docs/benchmarks/tpc-h.md). Streams are NOT
            independent sessions in this mode: they share one connection's
            server-side session state, and no new connections are opened.
        INDEPENDENT_CONNECTION: Each concurrent stream gets its OWN
            connection/session, returned by the adapter's
            ``new_stream_connection()`` override. Required for client/server
            engines whose driver does not support true concurrent statement
            execution across cursors of one connection (many DB-API drivers,
            e.g. psycopg, Snowflake, Databricks SQL, Trino, serialize on the
            connection lock or raise), and where TPC throughput semantics
            model N independent user sessions rather than N cursors of one
            session.
    """

    SHARED_CURSOR = "shared_cursor"
    INDEPENDENT_CONNECTION = "independent_connection"


_ISOLATION_REMEDIATION = {
    DriverIsolationCapability.NOT_APPLICABLE: (
        "This platform has no versioned driver package. Driver version isolation is not applicable."
    ),
    DriverIsolationCapability.NOT_FEASIBLE: (
        "This platform's driver has technical constraints that prevent isolated runtime binding "
        "(e.g. JVM dependency, native C library, shared library conflicts). "
        "Install the requested driver version into the active environment instead."
    ),
    DriverIsolationCapability.FEASIBLE_CLIENT_ONLY: (
        "This platform's Python client can be version-isolated, but the client version is independent "
        "from the engine/service version. Install the requested client version into the active "
        "environment, or omit driver_version to use the current client."
    ),
}


def check_isolation_capability(
    adapter_class: type,
    platform_name: str,
    runtime_strategy: str,
) -> None:
    """Check whether an adapter supports the requested runtime isolation strategy.

    Raises RuntimeError with capability-specific remediation guidance if the adapter
    does not support the requested isolation strategy.
    """
    capability = getattr(adapter_class, "driver_isolation_capability", DriverIsolationCapability.NOT_APPLICABLE)
    if runtime_strategy != "isolated-site-packages" or capability == DriverIsolationCapability.SUPPORTED:
        return

    remediation = _ISOLATION_REMEDIATION.get(capability, "Driver version isolation is not supported.")
    raise RuntimeError(
        f"Platform '{platform_name}' requested runtime strategy '{runtime_strategy}', "
        f"but adapter '{adapter_class.__name__}' does not support isolated driver runtime binding "
        f"(capability: {capability.value}). {remediation}"
    )


class _NoCloseProxy:
    """Transparent proxy that makes close() a no-op.

    Used by connection_factory closures so that the caller (e.g. TPCDSPowerTest)
    can call close() at the end of a run without destroying the shared underlying
    connection before the next warmup/measurement run reuses it.  Cursor-based
    connections don't need this because closing a cursor leaves the connection alive.

    All attribute access (except close) is delegated to the wrapped connection,
    so this works with both DB-API connections (execute/commit) and richer clients
    like SparkSession (catalog, sql, etc.).

    This class is internal - only instantiated by _make_stream_cursor().
    The open delegation surface is intentional: new attributes on the wrapped
    connection should "just work" without maintaining an explicit allowlist.
    """

    __slots__ = ("_conn",)

    def __init__(self, connection: Any) -> None:
        self._conn = connection

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def close(self) -> None:
        # Explicit method - shadows _conn.close() via normal MRO lookup,
        # so __getattr__ is never reached for 'close'.
        pass


def _make_stream_cursor(connection: Any) -> Any:
    """Return a cursor (or non-closing proxy) suitable for a power-test stream.

    DB-API 2.0 connections → ``connection.cursor()``
    Execute-only clients (e.g. ClickHouseLocalClient) → ``_NoCloseProxy(connection)``
    """
    if hasattr(connection, "cursor"):
        return connection.cursor()
    return _NoCloseProxy(connection)


class PlatformAdapterConnection:
    """Adapter to wrap platform adapter connections for TPC test classes.

    Supports two modes:
    - Validation mode (default): Routes queries through platform adapter for TPC validation
    - Maintenance mode: Routes all queries directly to underlying connection for real data

    Maintenance operations (RF1/RF2) require real query results and parameterized queries,
    so they use maintenance mode. Power/throughput tests use validation mode for result checking.
    """

    def __init__(self, connection: Any, platform_adapter: PlatformAdapter, maintenance_mode: bool = False):
        """Initialize the connection adapter.

        Args:
            connection: Original platform connection
            platform_adapter: Platform adapter instance for query execution
            maintenance_mode: If True, all queries bypass validation and execute directly
                            on the underlying connection (needed for RF1/RF2 operations)
        """
        self.connection = connection
        self.platform_adapter = platform_adapter
        self.connection_string = getattr(connection, "connection_string", "platform_adapter_connection")
        self.dialect = getattr(platform_adapter, "get_target_dialect", lambda: "standard")()
        self._maintenance_mode = maintenance_mode
        self._validate_row_count = True

        # Benchmark context for query validation (set by TPC test runners)
        self.benchmark_type: str | None = None
        self.scale_factor: float | None = None
        self._current_query_id: str = "unknown_query"
        self._current_stream_id: int | None = None

    def set_query_context(self, query_id: str, stream_id: int | None = None) -> None:
        """Set context for the next query execution.

        Used by TPC test runners to provide query identification for validation.

        Args:
            query_id: Query identifier (e.g., "q1", "q15a", "1")
            stream_id: Stream identifier for multi-stream benchmarks (e.g., 0, 1, 2...)
                      None indicates stream 0 or single-stream execution.
        """
        self._current_query_id = query_id
        self._current_stream_id = stream_id

    def execute(self, query: str, parameters: tuple | list | None = None):
        """Execute a query using the platform adapter with validation support.

        In maintenance mode, all queries execute directly on the underlying connection
        to get real results (needed for RF1/RF2 operations that use INSERT/DELETE/SELECT).

        In validation mode (default), non-parameterized queries use the platform adapter
        for TPC result validation support.

        Args:
            query: SQL query to execute
            parameters: Optional parameters for parameterized queries

        Returns:
            Cursor with results - either raw DB cursor (maintenance) or PlatformAdapterCursor
        """
        # Maintenance mode: all queries execute directly on underlying connection
        # This is needed for RF1/RF2 operations that require real data
        if self._maintenance_mode:
            if parameters:
                return self.connection.execute(query, parameters)
            else:
                return self.connection.execute(query)

        # Validation mode: parameterized queries still go through directly
        if parameters:
            return self.connection.execute(query, parameters)

        # Non-parameterized queries use the platform adapter for validation support
        # Execute query with validation context
        result = self.platform_adapter.execute_query(
            self.connection,
            query,
            self._current_query_id,
            benchmark_type=self.benchmark_type,
            scale_factor=self.scale_factor,
            validate_row_count=self._validate_row_count,
            stream_id=self._current_stream_id,
        )
        return PlatformAdapterCursor(result)

    def commit(self):
        """Commit transaction on underlying connection."""
        if hasattr(self.connection, "commit"):
            self.connection.commit()

    def rollback(self):
        """Rollback transaction on underlying connection."""
        if hasattr(self.connection, "rollback"):
            self.connection.rollback()

    def close(self):
        """Close underlying connection."""
        if hasattr(self.connection, "close"):
            self.connection.close()


class PlatformAdapterCursor:
    """Cursor-like wrapper around platform adapter execution results.

    ``platform_result`` (the dict handed in at construction) carries one of
    three shapes, and every fetch-shaped accessor (``rows``/``fetchall()``/
    ``fetchone()``) resolves to exactly one of these three branches - see
    ``_extract_rows()`` for the priority order:

      1. **Explicit rows** - ``platform_result["rows"]`` is a real,
         fully-materialized list/tuple of row tuples. ``has_real_rows`` is
         ``True`` and nothing is fabricated.
      2. **Count + sampled first row** - ``rows_returned`` (an int
         cardinality) plus ``first_row`` (one real sampled row, per
         ``sql_execution.execute_sql_query``). Element 0 of the returned
         list is the real ``first_row``; every remaining element is a
         fabricated ``(None,)`` placeholder that exists only to preserve
         list length (#1117). ``has_real_rows`` is ``False`` here even
         though index 0 is genuine - the list as a whole is not safe to
         read past index 0.
      3. **Count only, or first_row only** - either an all-placeholder
         ``[(None,)] * rows_returned`` list (no sampled row available), or
         (when no ``rows_returned`` count is present at all) a single real
         ``[first_row]``. ``has_real_rows`` is ``False`` in both cases: the
         former is fully fabricated, and the latter - while its one element
         is real - carries no confirmed cardinality guarantee beyond it.

    Callers that only need a row *count* should use ``row_count()`` (or the
    module-level ``count_query_rows()``) instead of ``fetchall()``/``.rows``:
    that path reads ``platform_result`` directly, never builds the
    placeholder list, and never logs the warning below - it is the sanctioned
    always-silent, never-materializing path (see #1100).

    Materializing rows that contain fabricated placeholders via
    ``fetchall()``/``fetchone()``/``.rows`` logs a one-time-per-cursor
    ``logger.warning`` - added after the 2026-07-10 incident where
    ``assert fetchall() == [(7,)]`` silently became ``[(None,)]`` in a
    session-isolation test (see ``has_real_rows`` and
    ``fix-session-isolation-placeholder-rows``). Use ``has_real_rows`` to
    check placeholder-ness without triggering the warning.
    """

    def __init__(self, platform_result: dict):
        """Initialize with platform adapter result.

        Args:
            platform_result: Result dictionary from platform adapter
        """
        self.platform_result = platform_result
        # Lazily materialized on first fetchall()/fetchone()/.rows access - see
        # the `rows` property. Callers that only need a row *count* (e.g. the
        # TPC-H/TPC-DS throughput drivers) should use count_query_rows()
        # instead, which reads platform_result directly and never builds this
        # placeholder list at all.
        self._rows: list | None = None
        # Set by _extract_rows() the first time it runs: True iff the
        # extracted list contains at least one fabricated (None,) placeholder
        # element (branch 2 with padding, or branch 3's count-only case).
        # Distinct from has_real_rows: a first_row-only list (branch 3) has
        # zero fabricated elements but still reports has_real_rows == False,
        # since it carries no rows_returned cardinality guarantee.
        self._has_placeholder_padding: bool = False
        self._placeholder_kind: str | None = None
        self._warned_placeholder_materialization: bool = False

    def _extract_rows(self):
        """Extract rows (or cardinality-preserving placeholders) from platform result.

        Priority order:
          1. An explicit ``rows`` list/tuple - already fully materialized upstream.
          2. ``rows_returned`` int - reconstructs a placeholder list of the *correct
             length*. This must be checked before ``first_row`` alone determines
             cardinality: ``first_row`` is only ONE sample row (see
             ``sql_execution.execute_sql_query``'s
             ``first_row=results[0] if results else None``), so treating its mere
             presence as "the whole result" silently collapsed every non-empty result
             to a length-1 list regardless of the true row count - a real correctness
             bug (empirically: 21/22 TPC-H throughput queries in a real run reported
             result_count=1; re-executing query 2's captured SQL returned 3 rows).
             When both ``rows_returned`` and ``first_row`` are present (the normal
             payload from ``execute_sql_query``), the first element of the returned
             list is the real ``first_row`` value, not a placeholder - only the
             remaining cardinality is padded with ``(None,)``. Fabricating an
             all-``None`` list here silently discarded a real sampled row (e.g.
             ``fetchone()``/``fetchall()[0]`` returning ``(None,)`` instead of the
             adapter-reported value).
          3. ``first_row`` alone, only when no ``rows_returned`` count is present at
             all - the last remaining cardinality signal, so it fabricates a
             single-row list.

        As a side effect, records whether the extracted list contains any
        fabricated ``(None,)`` placeholder elements (``self._has_placeholder_padding``)
        and a short ``self._placeholder_kind`` label identifying which branch
        produced them, for the one-time materialization warning in ``rows``.
        """
        explicit_rows = self.platform_result.get("rows")
        if isinstance(explicit_rows, (list, tuple)):
            return list(explicit_rows)

        first_row = self.platform_result.get("first_row")
        row_count = self.platform_result.get("rows_returned")
        if isinstance(row_count, int):
            if row_count <= 0:
                return []
            if first_row is not None:
                padding = row_count - 1
                if padding > 0:
                    self._has_placeholder_padding = True
                    self._placeholder_kind = "first_row+padding"
                return [first_row] + [(None,)] * padding
            self._has_placeholder_padding = True
            self._placeholder_kind = "rows_returned_only"
            return [(None,)] * row_count

        if first_row is not None:
            return [first_row]

        return []

    @property
    def has_real_rows(self) -> bool:
        """True only when ``platform_result["rows"]`` is a fully-materialized list.

        This does not force materialization of the placeholder-padded list
        and never logs the warning - it is a cheap, static check of the same
        condition ``_extract_rows()`` branch 1 tests, so it is safe to call
        before deciding whether to trust ``fetchall()``/``fetchone()``/``.rows``.

        False for every other case, including the #1117 first_row-in-slot-0
        case (element 0 is real but the remaining padding is not) and the
        first_row-alone case (one real row, but no confirmed cardinality).
        """
        return isinstance(self.platform_result.get("rows"), (list, tuple))

    @property
    def rows(self):
        """Materialized rows, computed lazily on first access.

        Logs a one-time-per-cursor warning the first time this (or
        ``fetchall()``/``fetchone()``) materializes a list containing
        fabricated placeholder elements - see the class docstring.
        """
        if self._rows is None:
            self._rows = self._extract_rows()
        self._warn_if_placeholder_materialized()
        return self._rows

    def _warn_if_placeholder_materialized(self) -> None:
        if not self._has_placeholder_padding or self._warned_placeholder_materialization:
            return
        self._warned_placeholder_materialization = True
        query_id = self.platform_result.get("query_id", "unknown")
        logger.warning(
            "PlatformAdapterCursor materialized placeholder rows for query_id=%s "
            "(kind=%s): the platform result carried only a row count (and, in the "
            "first_row+padding case, one sampled row), so fetchall()/fetchone()/.rows "
            "fabricated (None,) placeholders to preserve cardinality. These are NOT "
            "real platform values - check has_real_rows before trusting them, or use "
            "row_count()/count_query_rows() if only the count is needed. "
            "(This warning fires once per cursor.)",
            query_id,
            self._placeholder_kind,
        )

    def fetchall(self):
        """Return all rows."""
        return self.rows

    def fetchone(self):
        """Return one row."""
        rows = self.rows
        return rows[0] if rows else None

    def row_count(self) -> int:
        """Return this cursor's row count without forcing full materialization.

        Thin delegate to ``count_query_rows(self)``. Exists so that
        `benchbox.core` callers (e.g. the TPC-H/TPC-DS throughput drivers)
        can duck-type on a ``row_count()`` method instead of importing
        ``count_query_rows`` directly - the layering convention
        ``utils < core < platforms < cli`` forbids ``core`` importing from
        ``platforms``. See `benchbox.core.tpch.throughput_test` and
        `benchbox.core.tpcds.throughput_test` for the call sites.

        Always silent: reads ``platform_result`` directly and never builds
        the placeholder list, so it never logs the materialization warning.
        """
        return count_query_rows(self)


def count_query_rows(cursor: Any) -> int:
    """Return a stream query result's row count without forcing full materialization.

    Used by the TPC-H/TPC-DS throughput drivers in place of
    ``len(cursor.fetchall())`` so that counting results doesn't add a second,
    redundant materialization pass under the GIL on top of whatever the
    platform adapter already did. Priority (cheapest/most-truthful first):

      1. ``cursor.platform_result`` (``PlatformAdapterCursor``, the normal
         validation-mode path): read the adapter-reported ``rows``/
         ``rows_returned`` directly. The real driver fetch already happened
         one layer down (``sql_execution.execute_sql_query``), so this costs
         nothing extra and never builds a placeholder row list.
      2. ``cursor.rowcount`` (DB-API 2.0): some drivers populate this without
         requiring a fetch at all.
      3. A bounded consume loop over an iterable cursor: counts rows one at a
         time instead of materializing the whole result set into a single
         list in memory.
      4. ``len(cursor.fetchall())``: last resort, for cursors/test-doubles
         that expose none of the above.
    """
    platform_result = getattr(cursor, "platform_result", None)
    if isinstance(platform_result, dict):
        explicit_rows = platform_result.get("rows")
        if isinstance(explicit_rows, (list, tuple)):
            return len(explicit_rows)
        reported = platform_result.get("rows_returned")
        if isinstance(reported, int) and reported >= 0:
            return reported

    rowcount = getattr(cursor, "rowcount", None)
    if isinstance(rowcount, int) and rowcount >= 0:
        return rowcount

    if hasattr(cursor, "__iter__"):
        return sum(1 for _ in cursor)

    if hasattr(cursor, "fetchall"):
        return len(cursor.fetchall())

    return 0
