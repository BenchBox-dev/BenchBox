"""Shared status policy for result publication and ranking."""

from __future__ import annotations

from typing import Any

NON_CLEAN_VALIDATION_STATUSES: frozenset[str] = frozenset({"failed", "interrupted", "partial", "error"})


def normalize_validation_status(value: Any) -> str | None:
    """Normalize schema and model validation status values for policy checks."""
    if isinstance(value, dict):
        value = value.get("status")
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


def validation_status_is_non_clean(value: Any) -> bool:
    """Return True when a validation status must not be treated as a clean pass."""
    status = normalize_validation_status(value)
    return status in NON_CLEAN_VALIDATION_STATUSES


def result_failed_query_count(result: Any) -> int:
    """Return a conservative failed-query count from a BenchmarkResults-like object."""
    failed = _int_or_none(getattr(result, "failed_queries", None))
    if failed is not None and failed > 0:
        return failed

    total = _int_or_none(getattr(result, "total_queries", None))
    successful = _int_or_none(getattr(result, "successful_queries", None))
    if total is not None and successful is not None and total > successful:
        return max(total - successful, 0)
    return 0


def result_non_clean_reason(result: Any) -> str | None:
    """Return a user-facing reason when a result is not a clean pass."""
    failed = result_failed_query_count(result)
    if failed:
        noun = "query" if failed == 1 else "queries"
        return f"{failed} failed {noun}"

    status = normalize_validation_status(getattr(result, "validation_status", None))
    if status in NON_CLEAN_VALIDATION_STATUSES:
        return f"validation_status={status}"
    return None


def result_is_clean_pass(result: Any) -> bool:
    """Return True when a result has no query failures or non-clean validation status."""
    return result_non_clean_reason(result) is None


def bundle_failed_query_count(data: dict[str, Any]) -> int:
    """Return failed query count from a schema-v2 bundle dict."""
    summary = data.get("summary")
    if isinstance(summary, dict):
        queries = summary.get("queries")
        if isinstance(queries, dict):
            failed = _int_or_none(queries.get("failed"))
            if failed is not None and failed > 0:
                return failed

            total = _int_or_none(queries.get("total"))
            passed = _int_or_none(queries.get("passed"))
            if total is not None and passed is not None and total > passed:
                return max(total - passed, 0)

    query_rows = data.get("queries")
    if isinstance(query_rows, list):
        return sum(1 for query in query_rows if _query_row_failed(query))
    return 0


def bundle_non_clean_reason(data: dict[str, Any]) -> str | None:
    """Return a user-facing reason when a schema-v2 bundle is not a clean pass."""
    failed = bundle_failed_query_count(data)
    if failed:
        noun = "query" if failed == 1 else "queries"
        return f"{failed} failed {noun}"

    status = _bundle_validation_status(data)
    if status in NON_CLEAN_VALIDATION_STATUSES:
        return f"validation_status={status}"
    return None


def bundle_is_clean_pass(data: dict[str, Any]) -> bool:
    """Return True when a schema-v2 bundle has no query failures or non-clean status."""
    return bundle_non_clean_reason(data) is None


def _bundle_validation_status(data: dict[str, Any]) -> str | None:
    summary = data.get("summary")
    if not isinstance(summary, dict):
        return None
    return normalize_validation_status(summary.get("validation"))


def _query_row_failed(query: Any) -> bool:
    if not isinstance(query, dict):
        return False
    run_type = str(query.get("run_type") or "measurement").lower()
    if run_type != "measurement":
        return False
    status = query.get("status")
    return status is not None and str(status).upper() != "SUCCESS"


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None
