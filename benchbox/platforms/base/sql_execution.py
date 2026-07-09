"""Shared SQL execution helpers for DBAPI-style platform adapters."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from benchbox.utils.clock import elapsed_seconds, mono_time

logger = logging.getLogger(__name__)


def get_query_plan_from_cursor(connection: Any, query: str) -> str | None:
    """Get query execution plan via EXPLAIN on a DBAPI connection.

    Shared implementation for platforms that use the standard
    cursor -> EXPLAIN -> fetchall -> join pattern.

    Args:
        connection: DBAPI connection.
        query: SQL query to explain.

    Returns:
        Newline-joined plan rows, or ``None`` on failure.

    On failure this returns ``None`` and logs the exception, rather than
    returning the error text AS the plan (qpc-05 / F4.2). Encoding the error in
    the data channel was actively harmful: the display path printed
    ``"Could not get query plan: ..."`` as if it were a plan, and the capture
    path (``capture_query_plan``) would hand that error string to the platform
    parser as though it were EXPLAIN output. A ``None`` return is treated as a
    clean capture failure by callers and simply skips best-effort display.
    """
    cursor = connection.cursor()
    try:
        cursor.execute(f"EXPLAIN {query}")
        plan_rows = cursor.fetchall()
        return "\n".join([str(row[0]) for row in plan_rows])
    except Exception as e:
        logger.warning("Could not get query plan via EXPLAIN: %s", e)
        return None
    finally:
        cursor.close()


def execute_sql_query(
    connection: Any,
    query: str,
    query_id: str,
    *,
    log_verbose: Callable[[str], None],
    build_query_result_with_validation: Callable[..., dict[str, Any]],
    benchmark_type: str | None = None,
    scale_factor: float | None = None,
    validate_row_count: bool = True,
    stream_id: int | None = None,
) -> dict[str, Any]:
    """Execute a SQL query and build the standard BenchBox result payload."""
    start_time = mono_time()
    log_verbose(f"Executing query {query_id}")

    # Support both DB-API connections (need a new cursor) and pre-created cursors
    # (e.g. a psycopg2 cursor already created by _make_stream_cursor in the TPC-DS
    # power-test path).  DB-API cursors lack a callable .cursor() method.
    _owns_cursor = callable(getattr(connection, "cursor", None))
    cursor = connection.cursor() if _owns_cursor else connection
    try:
        cursor.execute(query)
        results = cursor.fetchall()

        execution_time = elapsed_seconds(start_time)
        actual_row_count = len(results)

        validation_result = None
        if validate_row_count and benchmark_type:
            from benchbox.core.validation.query_validation import QueryValidator

            validator = QueryValidator()
            validation_result = validator.validate_query_result(
                benchmark_type=benchmark_type,
                query_id=query_id,
                actual_row_count=actual_row_count,
                scale_factor=scale_factor,
                stream_id=stream_id,
            )

        # Gate-only value oracle: digest the FULL result set (behind
        # BENCHBOX_EMIT_RESULT_DIGEST, stream 0 only). Absent on a normal run.
        from benchbox.core.results.result_digest import compute_result_digest, result_digest_enabled

        result_digest = compute_result_digest(results) if result_digest_enabled() and stream_id in (None, 0) else None

        return build_query_result_with_validation(
            query_id=query_id,
            execution_time=execution_time,
            actual_row_count=actual_row_count,
            first_row=results[0] if results else None,
            validation_result=validation_result,
            result_digest=result_digest,
        )

    except Exception as exc:
        execution_time = elapsed_seconds(start_time)
        # Rollback to clear aborted-transaction state (psycopg3 requires this after any error)
        try:
            real_conn = connection if _owns_cursor else getattr(cursor, "connection", None)
            if real_conn is not None and hasattr(real_conn, "rollback"):
                real_conn.rollback()
        except Exception:
            pass
        return {
            "query_id": query_id,
            "status": "FAILED",
            "execution_time_seconds": execution_time,
            "rows_returned": 0,
            "error": str(exc),
            "error_type": type(exc).__name__,
        }
    finally:
        if _owns_cursor:
            cursor.close()
