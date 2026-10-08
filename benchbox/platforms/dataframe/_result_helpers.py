from __future__ import annotations

from typing import Any


def build_success_result_dict(
    query_id: str,
    execution_time_seconds: float,
    row_count: int,
    first_row: tuple[Any, ...] | None,
) -> dict[str, Any]:
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
    return {
        "query_id": query_id,
        "status": "FAILED",
        "execution_time_seconds": execution_time_seconds,
        "error": error_message,
    }
