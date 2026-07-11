"""Query result validation engine.

This module provides functionality for validating query execution results by comparing
actual row counts against expected results. It integrates with the expected results
registry to provide comprehensive validation across all benchmarks.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import threading

# Import expected_results to trigger provider registration
# This ensures TPC-H and TPC-DS providers are available when QueryValidator is instantiated
import benchbox.core.expected_results  # noqa: F401
from benchbox.core.expected_results.models import ValidationMode, ValidationResult
from benchbox.core.expected_results.registry import get_registry
from benchbox.core.expected_results.tpch_results import (
    PARAMETER_SENSITIVE_QUERY_IDS as _TPCH_PARAMETER_SENSITIVE_QUERY_IDS,
)

logger = logging.getLogger(__name__)

# Per-benchmark parameter-sensitive query-id sets consulted by the exclusion
# check in QueryValidator.validate_query_result(). Only TPC-H has one today
# (see tpch_results.PARAMETER_SENSITIVE_QUERY_IDS); benchmarks with no entry
# here get an empty set, so the exclusion never fires for them regardless of
# reference-seed context.
_PARAMETER_SENSITIVE_QUERY_IDS_BY_BENCHMARK: dict[str, frozenset[str]] = {
    "tpch": _TPCH_PARAMETER_SENSITIVE_QUERY_IDS,
    "tpc-h": _TPCH_PARAMETER_SENSITIVE_QUERY_IDS,
}


def get_parameter_sensitive_query_ids(benchmark_type: str) -> frozenset[str]:
    """Return the parameter-sensitive query-id set for a benchmark, if any.

    Empty frozenset for benchmarks with no known parameter-sensitive queries
    (e.g. TPC-DS today) -- the exclusion check in validate_query_result()
    never fires for them.
    """
    return _PARAMETER_SENSITIVE_QUERY_IDS_BY_BENCHMARK.get(benchmark_type.lower(), frozenset())


# Thread-local reference-seed determination. Set by the TPC-H power/throughput
# drivers (benchbox.core.tpch.power_test, benchbox.core.tpch.throughput_test)
# immediately before executing a query, and read here to decide whether a
# parameter-sensitive query's EXACT-mode mismatch should be excluded instead
# of failed. Thread-local (not a plain module global) because throughput
# streams execute concurrently, one thread per stream (see
# benchbox.core.throughput.runner.StreamRunner) -- a single shared global
# would let one stream's context leak into a concurrently-running stream's
# validation call.
_reference_seed_state = threading.local()


def set_reference_seed_context(is_reference_seed: bool | None) -> None:
    """Record, for the CURRENT THREAD, whether the query about to run through
    QueryValidator is using the pinned TPC reference seed's substitution
    parameters.

    This module never derives or compares seeds itself -- callers (the TPC-H
    power/throughput drivers) compute the comparison against
    benchbox.core.tpch.benchmark.get_reference_seed() and pass the result in.

    Values:
        True: this query's actual seed matches the reference seed for its
            scale factor (or the run used qgen defaults, which the TPC-H
            drivers treat as reference-equivalent) -- exact validation
            applies normally, with no exclusion.
        False: this query is running under different substitution parameters
            than the reference answer set -- get_parameter_sensitive_query_ids
            entries are excluded from EXACT-mode failure rather than
            compared.
        None (the default/unset value): unknown -- preserves the pre-existing
            behavior of always attempting EXACT validation. Benchmarks that
            never call this function (TPC-DS, DataFrame validation, any other
            QueryValidator caller) are therefore completely unaffected by the
            exclusion below.
    """
    _reference_seed_state.is_reference_seed = is_reference_seed


def get_reference_seed_context() -> bool | None:
    """Return the current thread's reference-seed determination, if set."""
    return getattr(_reference_seed_state, "is_reference_seed", None)


def clear_reference_seed_context() -> None:
    """Reset the current thread's reference-seed context to unset (None)."""
    _reference_seed_state.is_reference_seed = None


class QueryValidator:
    """Validator for query execution results.

    This class validates query results by comparing actual row counts against
    expected results from the registry. It supports:
    - Exact row count validation (requires reference seed)
    - Loose tolerance-based validation (for custom seeds, ±50% default)
    - Range-based validation for non-deterministic queries
    - Graceful handling of queries without expected results

    Automatically ensures all providers are registered on initialization.
    """

    def __init__(self):
        """Initialize the validator with the global registry.

        Explicitly ensures all expected results providers are registered.
        """
        # Explicitly ensure providers are registered (idempotent)
        from benchbox.core.expected_results import register_all_providers

        register_all_providers()

        self.registry = get_registry()

    def _normalize_query_id(self, benchmark_type: str, query_id: str | int) -> str:
        """Normalize query ID to string format for consistent lookups.

        Uses robust regex-based extraction to handle various ID formats:
        - Integers: 1 → "1"
        - String numerics: "15" → "15"
        - Prefixed: "Q1", "query15" → "1", "15"
        - TPC-H variants: "15a", "Q15b" → "15" (strip variant)
        - TPC-DS variants: "14a", "23b" → "14a", "23b" (PRESERVE variant)

        For TPC-H, extracts the leading integer (variants are stripped).
        For TPC-DS, preserves variant suffixes (14a, 23b, etc.) because
        answer files exist for each variant separately.
        For other benchmarks, returns the ID as-is (converted to string).

        Args:
            benchmark_type: Type of benchmark
            query_id: Raw query identifier (int or string)

        Returns:
            Normalized query ID as string
        """
        import re

        # Convert to string
        query_id_str = str(query_id)

        # For TPC-DS, preserve variant letters (14a, 23b, 39a, etc.)
        if benchmark_type.lower() in ("tpcds", "tpc-ds"):
            # Match pattern: optional prefix + digits + optional variant letter
            # Examples: "14a" → "14a", "Q23b" → "23b", "14" → "14"
            match = re.search(r"(\d+)([a-d]?)", query_id_str)
            if match:
                query_num = str(int(match.group(1)))  # Strip leading zeros
                variant = match.group(2)  # Preserve variant letter if present
                return f"{query_num}{variant}"

        # For TPC-H, extract leading integer (strip variants)
        elif benchmark_type.lower() in ("tpch", "tpc-h"):
            # Extract the first sequence of digits from the query ID
            # Handles: "1", "Q1", "query15", "15a", "Q15b", "01" (leading zeros stripped)
            match = re.search(r"(\d+)", query_id_str)
            if match:
                # Convert to int then back to string to strip leading zeros: "01" → "1"
                return str(int(match.group(1)))

        # For other benchmarks or if no digits found, return as-is
        return query_id_str

    def validate_query_result(
        self,
        benchmark_type: str,
        query_id: str | int,
        actual_row_count: int,
        scale_factor: float | None = None,
        stream_id: int | None = None,
    ) -> ValidationResult:
        """Validate a query result against expected row count.

        Args:
            benchmark_type: Type of benchmark (e.g., "tpch", "tpcds")
            query_id: Query identifier (e.g., 1, "1", "2a", "query14")
            actual_row_count: Actual number of rows returned by the query
            scale_factor: Scale factor used for the query (defaults to 1.0)
            stream_id: Stream identifier for multi-stream benchmarks (e.g., 0, 1, 2...)
                      Used to select stream-specific expected results. None indicates stream 0
                      or single-stream execution.

        Returns:
            ValidationResult with validation status and details

        Raises:
            ValueError: If actual_row_count is negative
        """
        # Validate non-negative row count
        if actual_row_count < 0:
            raise ValueError(f"actual_row_count must be non-negative, got {actual_row_count} for query '{query_id}'")

        # Always convert query_id to string for type consistency in ValidationResult
        query_id_str = str(query_id)

        # Normalize query_id for lookups in expected results
        # Benchmarks may use int keys but expected results use string keys
        query_id_normalized = self._normalize_query_id(benchmark_type, query_id)

        # Parameter-sensitive exclusion (non-reference-seed runs only). TPC-H's
        # answer-set-boundary queries (Q11/16/18/20 -- see
        # get_parameter_sensitive_query_ids) only have a validated cardinality
        # under the pinned reference seed's substitution parameters. When the
        # caller has told us (via set_reference_seed_context) that the CURRENT
        # query is running under different parameters, cardinality validation
        # is inapplicable rather than a false failure -- mirrors the bounded
        # correctness gate's existing exclusion policy (see
        # docs/operations/release-guide.md: "Q11/Q16/Q18/Q20 ... excluded for
        # answer-set boundary sensitivity"). Checked BEFORE the registry
        # lookup so it applies regardless of what stream_id the caller passed.
        # Reference-seed runs (context is True) and callers that never set the
        # context (None, e.g. TPC-DS, DataFrame validation) are unaffected.
        if get_reference_seed_context() is False and query_id_normalized in get_parameter_sensitive_query_ids(
            benchmark_type
        ):
            return ValidationResult(
                is_valid=True,
                query_id=query_id_str,
                expected_row_count=None,
                actual_row_count=actual_row_count,
                validation_mode=ValidationMode.SKIP,
                warning_message=(f"Query '{query_id}' not validated (parameter-sensitive, non-reference params)."),
            )

        # Get expected result from registry
        expected_result = self.registry.get_expected_result(
            benchmark_type, query_id_normalized, scale_factor, stream_id
        )

        # If no expected result found, skip validation with warning
        if expected_result is None:
            # Stream-aware warning message
            if stream_id is not None and stream_id > 0:
                warning_msg = (
                    f"Query '{query_id}' executed on stream {stream_id}. "
                    f"Answer files only available for stream 0 in '{benchmark_type}' benchmark. "
                    f"Validation skipped. Actual rows returned: {actual_row_count}"
                )
            else:
                warning_msg = (
                    f"No expected row count defined for query '{query_id}' in benchmark '{benchmark_type}'. "
                    f"Validation skipped. Actual rows returned: {actual_row_count}"
                )

            return ValidationResult(
                is_valid=True,  # Don't fail on unknown queries
                query_id=query_id_str,
                expected_row_count=None,
                actual_row_count=actual_row_count,
                validation_mode=ValidationMode.SKIP,
                warning_message=warning_msg,
            )

        # Get expected count (handles formulas and scale factors)
        expected_count = expected_result.get_expected_count(scale_factor)

        # CRITICAL SAFEGUARD: Handle EXACT mode with missing expected count
        # This occurs when a query variant (e.g., "14a") has an ExpectedQueryResult registered
        # but the expected_count lookup fails (e.g., variant not in row_counts dict).
        # Without this safeguard, EXACT mode would incorrectly fail validation.
        if expected_result.validation_mode == ValidationMode.EXACT and expected_count is None:
            return ValidationResult(
                is_valid=True,  # Don't fail - gracefully skip
                query_id=query_id_str,
                expected_row_count=None,
                actual_row_count=actual_row_count,
                validation_mode=ValidationMode.SKIP,  # Downgrade to SKIP
                warning_message=(
                    f"Query '{query_id}' has EXACT validation mode but no expected count available. "
                    f"Validation skipped. This may indicate a variant lookup issue or missing answer file. "
                    f"Actual rows returned: {actual_row_count}"
                ),
            )

        # Perform validation based on mode
        if expected_result.validation_mode == ValidationMode.SKIP:
            return ValidationResult(
                is_valid=True,
                query_id=query_id_str,
                expected_row_count=expected_count,
                actual_row_count=actual_row_count,
                validation_mode=ValidationMode.SKIP,
                warning_message=f"Validation skipped for query '{query_id}' (marked as skip in expected results)",
            )

        elif expected_result.validation_mode == ValidationMode.EXACT:
            return self._validate_exact(query_id_str, expected_count, actual_row_count)

        elif expected_result.validation_mode == ValidationMode.RANGE:
            return self._validate_range(
                query_id_str,
                expected_result.expected_row_count_min,
                expected_result.expected_row_count_max,
                actual_row_count,
            )

        elif expected_result.validation_mode == ValidationMode.LOOSE:
            # Use the validate_loose method from ExpectedQueryResult
            return expected_result.validate_loose(actual_row_count, scale_factor)

        else:
            # Should never reach here due to enum validation
            return ValidationResult(
                is_valid=False,
                query_id=query_id_str,
                expected_row_count=expected_count,
                actual_row_count=actual_row_count,
                validation_mode=expected_result.validation_mode,
                error_message=f"Unknown validation mode: {expected_result.validation_mode}",
            )

    def _validate_exact(self, query_id: str, expected_count: int | None, actual_count: int) -> ValidationResult:
        """Validate that row count matches exactly.

        Args:
            query_id: Query identifier
            expected_count: Expected row count
            actual_count: Actual row count

        Returns:
            ValidationResult
        """
        if expected_count is None:
            return ValidationResult(
                is_valid=False,
                query_id=query_id,
                expected_row_count=None,
                actual_row_count=actual_count,
                validation_mode=ValidationMode.EXACT,
                error_message=f"Expected count is None for query '{query_id}' in EXACT validation mode",
            )

        is_valid = expected_count == actual_count

        if is_valid:
            return ValidationResult(
                is_valid=True,
                query_id=query_id,
                expected_row_count=expected_count,
                actual_row_count=actual_count,
                validation_mode=ValidationMode.EXACT,
            )
        else:
            difference = actual_count - expected_count
            difference_percent = (difference / expected_count * 100.0) if expected_count > 0 else 0.0

            return ValidationResult(
                is_valid=False,
                query_id=query_id,
                expected_row_count=expected_count,
                actual_row_count=actual_count,
                validation_mode=ValidationMode.EXACT,
                error_message=(
                    f"Query validation FAILED: {query_id}\n"
                    f"  Expected: {expected_count:,} rows\n"
                    f"  Actual:   {actual_count:,} rows\n"
                    f"  Difference: {difference:+,} row(s) ({difference_percent:+.1f}%)\n"
                    f"  This indicates the query did not execute correctly."
                ),
                difference=difference,
                difference_percent=difference_percent,
            )

    def _validate_range(
        self, query_id: str, min_count: int | None, max_count: int | None, actual_count: int
    ) -> ValidationResult:
        """Validate that row count is within an acceptable range.

        Args:
            query_id: Query identifier
            min_count: Minimum acceptable row count
            max_count: Maximum acceptable row count
            actual_count: Actual row count

        Returns:
            ValidationResult
        """
        if min_count is None or max_count is None:
            return ValidationResult(
                is_valid=False,
                query_id=query_id,
                expected_row_count=None,
                actual_row_count=actual_count,
                validation_mode=ValidationMode.RANGE,
                error_message=f"Min/max counts not defined for query '{query_id}' in RANGE validation mode",
            )

        is_valid = min_count <= actual_count <= max_count

        if is_valid:
            return ValidationResult(
                is_valid=True,
                query_id=query_id,
                expected_row_count=None,  # No single expected count for ranges
                actual_row_count=actual_count,
                validation_mode=ValidationMode.RANGE,
            )
        else:
            if actual_count < min_count:
                difference = actual_count - min_count
                difference_percent = (difference / min_count * 100.0) if min_count > 0 else 0.0
                error_msg = (
                    f"Query validation FAILED: {query_id}\n"
                    f"  Expected: {min_count:,}-{max_count:,} rows (non-deterministic)\n"
                    f"  Actual:   {actual_count:,} rows\n"
                    f"  Difference: {difference:+,} rows (below minimum by {abs(difference_percent):.1f}%)"
                )
            else:  # actual_count > max_count
                difference = actual_count - max_count
                difference_percent = (difference / max_count * 100.0) if max_count > 0 else 0.0
                error_msg = (
                    f"Query validation FAILED: {query_id}\n"
                    f"  Expected: {min_count:,}-{max_count:,} rows (non-deterministic)\n"
                    f"  Actual:   {actual_count:,} rows\n"
                    f"  Difference: {difference:+,} rows (exceeds maximum by {difference_percent:.1f}%)"
                )

            return ValidationResult(
                is_valid=False,
                query_id=query_id,
                expected_row_count=None,
                actual_row_count=actual_count,
                validation_mode=ValidationMode.RANGE,
                error_message=error_msg,
                difference=difference,
                difference_percent=difference_percent,
            )
