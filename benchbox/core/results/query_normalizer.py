"""Query result normalization utilities.

This module provides utilities for normalizing query IDs and query results
from various input formats to a consistent, standardized format.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from benchbox.core.results.models import (
    QUERY_RUN_TYPE_MEASUREMENT,
    QUERY_RUN_TYPE_WARMUP,
)


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


@dataclass
class QueryResultInput:
    """Normalized input for a single query execution.

    This dataclass represents the standardized format for query results
    regardless of whether they come from SQL or DataFrame execution.
    """

    query_id: str  # Always numeric string: "1", "21" (no prefix)
    execution_time_seconds: float
    rows_returned: int
    status: str  # "SUCCESS" or "FAILED"
    iteration: int = 1  # 0 = warmup, 1+ = measurement
    stream_id: int = 0  # TPC stream ID (0 = power test default)
    run_type: str = QUERY_RUN_TYPE_MEASUREMENT  # canonical values from core.results.models
    error_message: str | None = None
    # Optional extended metadata
    cost: float | None = None  # Cloud platform cost estimation
    row_count_validation: dict[str, Any] | None = None  # Validation results
    dataframe_skip_summary: dict[str, Any] | None = None  # DataFrame skip metadata
    # Query plan capture (passed through to BenchmarkResults.query_results for companion file)
    query_plan: Any | None = None
    plan_fingerprint: str | None = None
    plan_fingerprint_normalized: str | None = None
    plan_capture_time_ms: float | None = None
    # Gate-only value-digest oracle (BENCHBOX_EMIT_RESULT_DIGEST): full-result
    # digest of a stream-0 query. None on a normal run (no payload change).
    result_digest: str | None = None
    # Phase discriminator (power/throughput/maintenance). Needed alongside
    # stream_id to key multi-stream plan-capture rows: a power measurement
    # stream and a throughput stream are independent counters that can both be
    # numbered 0 (see build_plans_payload in core.results.schema).
    test_type: str | None = None


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
    # Extract query ID - try multiple field names
    query_id = raw_result.get("query_id") or raw_result.get("id") or raw_result.get("query") or ""
    query_id = normalize_query_id(query_id)

    # Extract execution time from canonical seconds key, then explicit ms keys.
    time_seconds = raw_result.get("execution_time_seconds")
    if time_seconds is None:
        time_ms = raw_result.get("execution_time_ms") or raw_result.get("ms") or 0
        time_seconds = time_ms / 1000.0

    # Extract rows returned
    rows_returned = raw_result.get("rows_returned") or raw_result.get("rows") or raw_result.get("result_count") or 0

    # Extract status
    status = raw_result.get("status", "SUCCESS")
    # Normalize status values
    if status.upper() in ("SUCCESS", "SUCCEEDED", "OK", "PASS", "PASSED"):
        status = "SUCCESS"
    elif status.upper() in ("FAILED", "FAIL", "ERROR"):
        status = "FAILED"

    # Extract iteration and stream
    if raw_result.get("iteration") is not None:
        iteration = raw_result.get("iteration")
    elif raw_result.get("iter") is not None:
        iteration = raw_result.get("iter")
    else:
        iteration = default_iteration

    if raw_result.get("stream_id") is not None:
        stream_id = raw_result.get("stream_id")
    elif raw_result.get("stream") is not None:
        stream_id = raw_result.get("stream")
    else:
        stream_id = default_stream_id

    run_type = raw_result.get("run_type") or raw_result.get("runType")
    if not run_type:
        # Backward-compatibility fallback for historical artifacts and legacy
        # producer paths. New producer code should stamp run_type explicitly.
        if raw_result.get("is_warmup") or int(iteration) == 0:
            run_type = QUERY_RUN_TYPE_WARMUP
        else:
            run_type = QUERY_RUN_TYPE_MEASUREMENT

    # Extract error message
    error_message = raw_result.get("error_message") or raw_result.get("error") or raw_result.get("message")

    return QueryResultInput(
        query_id=query_id,
        execution_time_seconds=float(time_seconds) if time_seconds else 0.0,
        rows_returned=int(rows_returned) if rows_returned else 0,
        status=status,
        iteration=int(iteration),
        stream_id=int(stream_id),
        run_type=str(run_type),
        error_message=str(error_message) if error_message else None,
        cost=raw_result.get("cost"),
        row_count_validation=raw_result.get("row_count_validation"),
        dataframe_skip_summary=raw_result.get("dataframe_skip_summary"),
        query_plan=raw_result.get("query_plan"),
        plan_fingerprint=raw_result.get("plan_fingerprint"),
        plan_fingerprint_normalized=raw_result.get("plan_fingerprint_normalized"),
        plan_capture_time_ms=raw_result.get("plan_capture_time_ms"),
        result_digest=raw_result.get("result_digest"),
        test_type=raw_result.get("test_type"),
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
