"""Honest row-count validation for DataFrame benchmark results.

DataFrame adapters fully materialize each result and already report its row
count, but historically no oracle consumed that count.  This module reuses the
same expected-result registry as SQL execution while keeping the evidence
boundary deliberately narrow: only TPC-H SF1 runs using reference-equivalent
parameters may produce a clean validation pass today.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from benchbox.core.expected_results.models import ValidationMode
from benchbox.core.validation.query_validation import QueryValidator

_MAX_EVIDENCE_MESSAGE_CHARS = 500


@dataclass(frozen=True)
class DataFrameQueryValidationSummary:
    """Run-level status and bounded evidence for DataFrame query validation."""

    status: str
    details: dict[str, Any]


def validate_dataframe_query_results(
    query_results: list[dict[str, Any]],
    *,
    benchmark_name: str,
    scale_factor: float,
    validation_mode: str | None = None,
    seed: int | None = None,
) -> DataFrameQueryValidationSummary:
    """Validate successful measurement rows against a supported TPC oracle.

    Warmups and summary rows are never evidence.  DataFrame ``stream_id`` is
    also intentionally not forwarded to :class:`QueryValidator`: in this path
    it labels repeated measurements, while the expected-result registry uses it
    to select distinct answer streams.

    TPC-DS remains uncertain because its stored row counts represent one
    parameterization and its provider defaults to ``SKIP``.  Other benchmarks
    remain ``NOT_RUN`` until a production-faithful cross-surface provider is
    available.
    """
    benchmark_id = _normalize_benchmark_name(benchmark_name)
    mode = str(validation_mode or "exact").strip().lower()
    evidence = {
        "provider": "tpc_expected_row_counts",
        "benchmark": benchmark_id,
        "checked": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "errors": 0,
    }

    measurement_rows = [row for row in query_results if _is_measurement(row)]
    execution_failures = sum(1 for row in measurement_rows if _is_execution_failure(row))
    selected_skips = sum(
        1
        for row in query_results
        if str(row.get("status", "")).upper() == "SKIPPED"
        and str(row.get("run_type") or "measurement").lower() != "warmup"
        and str(row.get("query_id", "")).upper() != "DF_SKIP_SUMMARY"
    )

    if mode == "disabled":
        evidence["reason"] = "validation disabled by run configuration"
        return DataFrameQueryValidationSummary("PARTIAL" if execution_failures else "NOT_RUN", evidence)

    successful_rows = [row for row in measurement_rows if str(row.get("status", "")).upper() == "SUCCESS"]
    if mode != "exact":
        reason = f"DataFrame publication evidence does not support validation mode {mode!r}"
        for row in successful_rows:
            _attach_skipped_validation(row, reason)
        evidence["skipped"] = len(successful_rows) + selected_skips
        evidence["reason"] = reason
        status = _unavailable_status(execution_failures, bool(successful_rows or selected_skips))
        return DataFrameQueryValidationSummary(status, evidence)

    if benchmark_id not in {"tpch", "tpcds"}:
        evidence["provider"] = "none"
        evidence["reason"] = "no production DataFrame oracle is registered for this benchmark"
        return DataFrameQueryValidationSummary("PARTIAL" if execution_failures else "NOT_RUN", evidence)

    if benchmark_id == "tpcds" or not _tpch_reference_context(scale_factor, seed):
        reason = (
            "TPC-DS expected row counts are not seed-aligned with this DataFrame run"
            if benchmark_id == "tpcds"
            else "TPC-H row-count evidence requires SF1 reference-equivalent parameters"
        )
        for row in successful_rows:
            _attach_skipped_validation(row, reason)
        evidence["skipped"] = len(successful_rows) + selected_skips
        evidence["reason"] = reason
        status = _unavailable_status(execution_failures, bool(successful_rows or selected_skips))
        return DataFrameQueryValidationSummary(status, evidence)

    initialization_error = _apply_expected_row_counts(successful_rows, benchmark_id, scale_factor, evidence)
    if initialization_error:
        evidence["reason"] = initialization_error
        status = _unavailable_status(execution_failures, bool(successful_rows))
        return DataFrameQueryValidationSummary(status, evidence)

    evidence["skipped"] += selected_skips
    if evidence["failed"]:
        status = "FAILED"
    elif execution_failures:
        status = "PARTIAL"
    elif evidence["skipped"] or evidence["errors"]:
        status = "UNCERTAIN"
    elif evidence["checked"] and evidence["checked"] == len(successful_rows):
        status = "PASSED"
    else:
        status = "NOT_RUN"
    return DataFrameQueryValidationSummary(status, evidence)


def _normalize_benchmark_name(value: str) -> str:
    return str(value).strip().lower().replace("tpc-h", "tpch").replace("tpc-ds", "tpcds")


def _unavailable_status(execution_failures: int, has_unavailable_evidence: bool) -> str:
    if execution_failures:
        return "PARTIAL"
    if has_unavailable_evidence:
        return "UNCERTAIN"
    return "NOT_RUN"


def _apply_expected_row_counts(
    successful_rows: list[dict[str, Any]],
    benchmark_id: str,
    scale_factor: float,
    evidence: dict[str, Any],
) -> str | None:
    """Attach per-query evidence, returning an initialization error if one occurs."""
    try:
        validator = QueryValidator()
    except Exception as exc:  # noqa: BLE001 - an unavailable oracle is not a candidate-result mismatch
        message = _bounded_message(f"Row-count oracle failed to initialize: {type(exc).__name__}: {exc}")
        for row in successful_rows:
            row["row_count_validation"] = {
                "status": "ERROR",
                "expected": None,
                "actual": row.get("rows_returned"),
                "error": message,
            }
        evidence["errors"] = len(successful_rows)
        return message

    for row in successful_rows:
        actual_row_count = row.get("rows_returned")
        if isinstance(actual_row_count, bool) or not isinstance(actual_row_count, int) or actual_row_count < 0:
            message = "Successful DataFrame query did not report a valid non-negative rows_returned value"
            _attach_validation_error(row, message)
            evidence["failed"] += 1
            evidence["errors"] += 1
            continue

        try:
            result = validator.validate_query_result(
                benchmark_type=benchmark_id,
                query_id=str(row.get("query_id", "")),
                actual_row_count=actual_row_count,
                scale_factor=scale_factor,
                # Deliberately omit stream_id; it is a repetition ID in this path.
            )
        except Exception as exc:  # noqa: BLE001 - an unavailable oracle is not a candidate-result mismatch
            message = _bounded_message(f"Row-count oracle failed: {type(exc).__name__}: {exc}")
            row["row_count_validation"] = {
                "status": "ERROR",
                "expected": None,
                "actual": actual_row_count,
                "error": message,
            }
            evidence["errors"] += 1
            continue

        row_count_validation: dict[str, Any] = {
            "expected": result.expected_row_count,
            "actual": actual_row_count,
        }
        if result.validation_mode == ValidationMode.SKIP:
            row_count_validation["status"] = "SKIPPED"
            if result.warning_message:
                row_count_validation["warning"] = _bounded_message(result.warning_message)
            evidence["skipped"] += 1
        elif result.is_valid:
            row_count_validation["status"] = "PASSED"
            evidence["checked"] += 1
            evidence["passed"] += 1
        else:
            message = _bounded_message(result.error_message or "Row-count validation failed")
            row_count_validation["status"] = "FAILED"
            row_count_validation["error"] = message
            row["status"] = "FAILED"
            row["error"] = message
            evidence["checked"] += 1
            evidence["failed"] += 1
        row["row_count_validation"] = row_count_validation
    return None


def _tpch_reference_context(scale_factor: float, seed: int | None) -> bool:
    if float(scale_factor) != 1.0:
        return False
    from benchbox.core.tpch.benchmark import get_reference_seed

    reference_seed = get_reference_seed(float(scale_factor))
    return seed is None or seed == reference_seed


def _bounded_message(value: str) -> str:
    if len(value) <= _MAX_EVIDENCE_MESSAGE_CHARS:
        return value
    return value[: _MAX_EVIDENCE_MESSAGE_CHARS - 3] + "..."


def _is_measurement(row: dict[str, Any]) -> bool:
    return str(row.get("run_type") or "measurement").lower() == "measurement"


def _is_execution_failure(row: dict[str, Any]) -> bool:
    return str(row.get("status", "")).upper() not in {"SUCCESS", "SKIPPED"}


def _attach_skipped_validation(row: dict[str, Any], warning: str) -> None:
    row["row_count_validation"] = {
        "status": "SKIPPED",
        "expected": None,
        "actual": row.get("rows_returned"),
        "warning": warning,
    }


def _attach_validation_error(row: dict[str, Any], message: str) -> None:
    row["rows_returned"] = None
    row["row_count_validation"] = {
        "status": "ERROR",
        "expected": None,
        "actual": None,
        "error": message,
    }
    row["status"] = "FAILED"
    row["error"] = message
