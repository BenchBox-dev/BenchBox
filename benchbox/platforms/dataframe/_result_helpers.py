"""Shared result-dict builders for DataFrame adapter families.

Expression-family and Pandas-family adapters construct identical success and
failure result dicts after running a query. These helpers centralize that
shape so the two families stay consistent.
"""

from __future__ import annotations

from typing import Any


def build_success_result_dict(
    query_id: str,
    execution_time_seconds: float,
    row_count: int,
    first_row: tuple[Any, ...] | None,
) -> dict[str, Any]:
    """Build the success payload returned by DataFrame ``execute_query``.

    Args:
        query_id: Canonical query identifier.
        execution_time_seconds: Wall-clock duration of the query.
        row_count: Rows returned by the query.
        first_row: First row tuple, or ``None`` when unavailable.
    """
    return {
        "query_id": query_id,
        "status": "SUCCESS",
        "execution_time_seconds": execution_time_seconds,
        "rows_returned": row_count,
        "first_row": first_row,
    }


def build_failure_result_dict(
    query_id: str,
    execution_time_seconds: float,
    error_message: str,
) -> dict[str, Any]:
    """Build the failure payload returned by DataFrame ``execute_query``.

    Args:
        query_id: Canonical query identifier.
        execution_time_seconds: Wall-clock duration before the failure.
        error_message: Stringified exception message.
    """
    return {
        "query_id": query_id,
        "status": "FAILED",
        "execution_time_seconds": execution_time_seconds,
        "error": error_message,
    }
