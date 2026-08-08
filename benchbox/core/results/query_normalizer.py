"""Query result normalization utilities.

This module provides utilities for normalizing query IDs and query results
from various input formats to a consistent, standardized format.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import re
from typing import Any

from benchbox.core.results.models import (
    QUERY_RUN_TYPE_MEASUREMENT,
    QueryExecution,
)
from benchbox.core.results.query_execution import query_execution_from_legacy_dict


def normalize_query_id(query_id: str | int) -> str:
    """Normalize query ID to consistent format (numeric string without prefix).

    Converts various query ID formats to a standardized numeric string:
    - "Q1" -> "1"
    - "Q21" -> "21"
    - "q1" -> "1"
    - "1" -> "1"
    - "query_1" -> "1"
    - 1 -> "1"

    Args:
        query_id: Query identifier in any common format

    Returns:
        Normalized query ID as numeric string (e.g., "1", "21")
    """
    # Handle integer input
    if isinstance(query_id, int):
        return str(query_id)

    normalized = str(query_id).strip()

    # Remove common prefixes (case-insensitive)
    upper = normalized.upper()
    if upper.startswith("QUERY_"):
        normalized = normalized[6:]
    elif upper.startswith("QUERY"):
        normalized = normalized[5:]
    elif upper.startswith("Q") and len(normalized) > 1 and (normalized[1].isdigit() or normalized[1].islower()):
        normalized = normalized[1:]

    normalized = normalized.strip()

    # Remove file extensions (e.g., ".sql", ".q") but preserve dot-notation
    # query IDs like SSB's "3.1", "4.2".  Split on the LAST dot and only strip
    # when the trailing part is purely alphabetic (a file extension), not numeric.
    if "." in normalized:
        base, _, ext = normalized.rpartition(".")
        if ext.isalpha():  # "sql", "q", "txt" → strip; "1", "2" → keep
            normalized = base.strip()

    # Preserve variant suffixes for multi-part templates (e.g., "14a", "39b")
    match = re.fullmatch(r"(\d+)([A-Za-z]+)?", normalized)
    if match:
        digits, suffix = match.groups()
        return f"{digits}{suffix.lower() if suffix else ''}"

    return normalized


def format_query_id(query_id: str | int, with_prefix: bool = True) -> str:
    """Format query ID with optional Q prefix.

    Args:
        query_id: Query identifier in any format
        with_prefix: If True, add "Q" prefix (e.g., "Q1"); if False, return bare number

    Returns:
        Formatted query ID
    """
    normalized = normalize_query_id(query_id)
    if with_prefix:
        return f"Q{normalized}"
    return normalized


class QueryResultInput(QueryExecution):
    """Compatibility constructor for producer-facing seconds results.

    This class adds no fields or behavior to the canonical QueryExecution
    model.  It preserves the historical constructor defaults while serving as
    an explicit boundary adapter for callers that still import
    ``QueryResultInput``.
    """

    def __init__(
        self,
        query_id: str,
        execution_time_seconds: float | None,
        rows_returned: int | None,
        status: str,
        iteration: int | None = 1,
        stream_id: int | str | None = 0,
        run_type: str | None = QUERY_RUN_TYPE_MEASUREMENT,
        error_message: str | None = None,
        cost: float | None = None,
        row_count_validation: dict[str, Any] | None = None,
        dataframe_skip_summary: dict[str, Any] | None = None,
        query_plan: Any | None = None,
        plan_fingerprint: str | None = None,
        plan_fingerprint_normalized: str | None = None,
        plan_capture_time_ms: float | None = None,
        plan_capture_error: str | None = None,
        result_digest: str | None = None,
        test_type: str | None = None,
        error_type: str | None = None,
        resource_usage: dict[str, Any] | None = None,
        execution_order: int | None = None,
        execution_time_ms: float | None = None,
    ) -> None:
        super().__init__(
            query_id=query_id,
            stream_id=stream_id,
            execution_order=execution_order,
            execution_time_ms=execution_time_ms,
            execution_time_seconds=execution_time_seconds,
            status=status,
            rows_returned=rows_returned,
            resource_usage=resource_usage,
            error_message=error_message,
            iteration=iteration,
            run_type=run_type,
            row_count_validation=row_count_validation,
            cost=cost,
            query_plan=query_plan,
            plan_fingerprint=plan_fingerprint,
            plan_fingerprint_normalized=plan_fingerprint_normalized,
            plan_capture_time_ms=plan_capture_time_ms,
            plan_capture_error=plan_capture_error,
            dataframe_skip_summary=dataframe_skip_summary,
            result_digest=result_digest,
            test_type=test_type,
            error_type=error_type,
        )

    @classmethod
    def from_execution(cls, execution: QueryExecution) -> QueryResultInput:
        """Wrap a canonical execution with the legacy constructor type."""
        return cls(
            query_id=execution.query_id,
            execution_time_seconds=None,
            execution_time_ms=execution.execution_time_ms,
            rows_returned=execution.rows_returned,
            status=execution.status,
            iteration=execution.iteration,
            stream_id=execution.stream_id,
            run_type=execution.run_type,
            error_message=execution.error_message,
            cost=execution.cost,
            row_count_validation=execution.row_count_validation,
            dataframe_skip_summary=execution.dataframe_skip_summary,
            query_plan=execution.query_plan,
            plan_fingerprint=execution.plan_fingerprint,
            plan_fingerprint_normalized=execution.plan_fingerprint_normalized,
            plan_capture_time_ms=execution.plan_capture_time_ms,
            plan_capture_error=execution.plan_capture_error,
            result_digest=execution.result_digest,
            test_type=execution.test_type,
            error_type=execution.error_type,
            resource_usage=execution.resource_usage,
            execution_order=execution.execution_order,
        )


def normalize_query_result(
    raw_result: dict[str, Any],
    default_iteration: int = 1,
    default_stream_id: int = 0,
) -> QueryResultInput:
    """Normalize a raw query result dict to QueryResultInput.

    Handles various input formats from SQL and DataFrame runners, extracting
    and normalizing fields to a consistent format.

    Args:
        raw_result: Raw query result dictionary from any runner
        default_iteration: Default iteration number if not specified
        default_stream_id: Default stream ID if not specified

    Returns:
        Normalized QueryResultInput instance
    """
    return QueryResultInput.from_execution(
        query_execution_from_legacy_dict(
            raw_result,
            default_iteration=default_iteration,
            default_stream_id=default_stream_id,
            normalize_query_id=normalize_query_id,
        )
    )


def normalize_query_results(
    raw_results: list[dict[str, Any]],
    default_stream_id: int = 0,
) -> list[QueryResultInput]:
    """Normalize a list of raw query results.

    Args:
        raw_results: List of raw query result dictionaries
        default_stream_id: Default stream ID for results without one

    Returns:
        List of normalized QueryResultInput instances
    """
    normalized = []
    for i, raw in enumerate(raw_results, start=1):
        # Use the result's iteration if present, otherwise use position
        default_iter = raw.get("iteration", i)
        normalized.append(
            normalize_query_result(
                raw,
                default_iteration=default_iter,
                default_stream_id=default_stream_id,
            )
        )
    return normalized
