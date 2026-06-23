"""TPC-Havoc result validation utilities.

This module provides functionality to validate that query variants produce
identical results to the original TPC-H queries.

Copyright 2026 Joe Harris / BenchBox Project

This implementation is derived from TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import hashlib
import math
from typing import Any, Optional, Union


class ValidationError(Exception):
    """Exception raised when query variant validation fails."""


def _none_safe_sort_key(row: tuple[Any, ...]) -> tuple[Any, ...]:
    """A total, crash-free sort key for a result row.

    Python ``sorted()`` raises when a column mixes ``None`` with non-None values
    (``None`` is not orderable against ``int``/``str``). This keys each value as
    ``(is_none, type_name, value)`` so ``None`` sorts deterministically and values
    of different types never compare directly. For None-free, single-type columns
    the induced order matches natural tuple ordering, so existing comparisons are
    unaffected.
    """
    return tuple((value is None, type(value).__name__, value if value is not None else 0) for value in row)


class ResultValidator:
    """Validates that query variants produce identical results."""

    def __init__(self, tolerance: float = 1e-10) -> None:
        """Initialize result validator.

        Args:
            tolerance: Tolerance for floating-point comparisons
        """
        self.tolerance = tolerance

    def validate_results_exact(
        self,
        original_results: list[tuple[Any, ...]],
        variant_results: list[tuple[Any, ...]],
        query_id: int,
        variant_id: int,
    ) -> bool:
        """Validate exact result matching between original and variant.

        Args:
            original_results: Results from original TPC-H query
            variant_results: Results from variant query
            query_id: The query ID being validated
            variant_id: The variant ID being validated

        Returns:
            True if results match exactly

        Raises:
            ValidationError: If results don't match
        """
        if len(original_results) != len(variant_results):
            raise ValidationError(
                f"Q{query_id}.{variant_id}: Row count mismatch. "
                f"Original: {len(original_results)}, Variant: {len(variant_results)}"
            )

        # Sort both result sets to handle potential ordering differences
        # (though TPC-H queries should have deterministic ordering). The
        # None-safe key keeps a NULL-bearing column from raising in sorted().
        original_sorted = sorted(original_results, key=_none_safe_sort_key)
        variant_sorted = sorted(variant_results, key=_none_safe_sort_key)

        for i, (orig_row, var_row) in enumerate(zip(original_sorted, variant_sorted)):
            if len(orig_row) != len(var_row):
                raise ValidationError(
                    f"Q{query_id}.{variant_id}: Column count mismatch at row {i}. "
                    f"Original: {len(orig_row)}, Variant: {len(var_row)}"
                )

            for j, (orig_val, var_val) in enumerate(zip(orig_row, var_row)):
                if not self._values_equal(orig_val, var_val):
                    raise ValidationError(
                        f"Q{query_id}.{variant_id}: Value mismatch at row {i}, column {j}. "
                        f"Original: {orig_val}, Variant: {var_val}"
                    )

        return True

    def validate_results_ordered(
        self,
        reference_results: list[tuple[Any, ...]],
        candidate_results: list[tuple[Any, ...]],
        query_id: Any,
        *,
        order_key: list[int],
        has_limit: bool,
    ) -> bool:
        """Order-aware, tie-tolerant comparison against an ordered reference.

        ``reference_results`` is authoritative: it was executed in the SQL
        ``ORDER BY`` order. ``order_key`` lists the output-column indices the
        ``ORDER BY`` sorts on (empty => no ``ORDER BY``). The comparison:

        * verifies the order-key VALUE sequence matches (so a reversed or missing
          ``ORDER BY`` on the candidate is caught), then
        * compares each tie group (rows sharing one order-key value) as a MULTISET
          (so two equally-valid orderings within a tie are NOT a divergence), and
        * tolerates only the FINAL tie group under a ``LIMIT`` (its members are
          ambiguous because ``LIMIT`` truncates a tie arbitrarily), checking just
          its size and key — interior groups are matched exactly so value/group
          bugs are still caught.

        A query with no ``ORDER BY`` under a ``LIMIT`` is an arbitrary slice, so
        only the row count is checkable (already asserted by the caller path).
        """
        if len(reference_results) != len(candidate_results):
            raise ValidationError(
                f"Q{query_id}: Row count mismatch. "
                f"Reference: {len(reference_results)}, Candidate: {len(candidate_results)}"
            )

        if not order_key:
            # No ORDER BY: a LIMIT yields an arbitrary slice (nothing more to
            # check); without a LIMIT the full result is one order-insensitive set.
            if not has_limit:
                self._assert_multiset_equal(reference_results, candidate_results, query_id)
            return True

        ref_groups = self._group_by_order_key(reference_results, order_key)
        cand_groups = self._group_by_order_key(candidate_results, order_key)

        if len(ref_groups) != len(cand_groups):
            raise ValidationError(
                f"Q{query_id}: ORDER BY tie-group count mismatch "
                f"({len(ref_groups)} vs {len(cand_groups)}) - ordering not respected."
            )

        last = len(ref_groups) - 1
        for gi, ((ref_key, ref_rows), (cand_key, cand_rows)) in enumerate(zip(ref_groups, cand_groups)):
            if not self._rows_equal(ref_key, cand_key):
                raise ValidationError(
                    f"Q{query_id}: ORDER BY key mismatch at group {gi}. "
                    f"Reference: {ref_key}, Candidate: {cand_key} - ordering not respected."
                )
            if len(ref_rows) != len(cand_rows):
                raise ValidationError(
                    f"Q{query_id}: tie-group size mismatch at group {gi} "
                    f"(key {ref_key}): {len(ref_rows)} vs {len(cand_rows)}."
                )
            # The final group under a LIMIT is a truncated tie: its specific
            # members are ambiguous, so size+key (already checked) is the most we
            # can assert. Every interior group must match exactly.
            if not (has_limit and gi == last):
                self._assert_multiset_equal(ref_rows, cand_rows, query_id)

        return True

    def _group_by_order_key(
        self, rows: list[tuple[Any, ...]], order_key: list[int]
    ) -> list[tuple[tuple[Any, ...], list[tuple[Any, ...]]]]:
        """Partition ordered rows into consecutive runs sharing one order-key value."""
        groups: list[tuple[tuple[Any, ...], list[tuple[Any, ...]]]] = []
        for row in rows:
            key = tuple(row[i] for i in order_key)
            if groups and self._rows_equal(groups[-1][0], key):
                groups[-1][1].append(row)
            else:
                groups.append((key, [row]))
        return groups

    def _rows_equal(self, row1: tuple[Any, ...], row2: tuple[Any, ...]) -> bool:
        """Element-wise equality using the validator's tolerant value comparison."""
        if len(row1) != len(row2):
            return False
        return all(self._values_equal(a, b) for a, b in zip(row1, row2))

    def _assert_multiset_equal(
        self, reference_rows: list[tuple[Any, ...]], candidate_rows: list[tuple[Any, ...]], query_id: Any
    ) -> None:
        """Assert two row collections are equal as multisets (order-insensitive)."""
        ref_sorted = sorted(reference_rows, key=_none_safe_sort_key)
        cand_sorted = sorted(candidate_rows, key=_none_safe_sort_key)
        for ref_row, cand_row in zip(ref_sorted, cand_sorted):
            if not self._rows_equal(ref_row, cand_row):
                raise ValidationError(
                    f"Q{query_id}: result rows differ (order-insensitive). "
                    f"Reference row {ref_row} has no match in the candidate."
                )

    def validate_results_checksum(
        self,
        original_results: list[tuple[Any, ...]],
        variant_results: list[tuple[Any, ...]],
        query_id: int,
        variant_id: int,
    ) -> bool:
        """Validate results using checksums for large result sets.

        Args:
            original_results: Results from original TPC-H query
            variant_results: Results from variant query
            query_id: The query ID being validated
            variant_id: The variant ID being validated

        Returns:
            True if checksums match

        Raises:
            ValidationError: If checksums don't match
        """
        original_checksum = self._calculate_checksum(original_results)
        variant_checksum = self._calculate_checksum(variant_results)

        if original_checksum != variant_checksum:
            raise ValidationError(
                f"Q{query_id}.{variant_id}: Checksum mismatch. "
                f"Original: {original_checksum}, Variant: {variant_checksum}"
            )

        return True

    def validate_aggregation_results(
        self,
        original_results: list[tuple[Any, ...]],
        variant_results: list[tuple[Any, ...]],
        query_id: int,
        variant_id: int,
        aggregation_columns: Optional[list[int]] = None,
    ) -> bool:
        """Validate results with special handling for aggregation queries.

        Args:
            original_results: Results from original TPC-H query
            variant_results: Results from variant query
            query_id: The query ID being validated
            variant_id: The variant ID being validated
            aggregation_columns: Indices of columns containing aggregated values

        Returns:
            True if results match within tolerance

        Raises:
            ValidationError: If results don't match
        """
        if len(original_results) != len(variant_results):
            raise ValidationError(
                f"Q{query_id}.{variant_id}: Row count mismatch in aggregation. "
                f"Original: {len(original_results)}, Variant: {len(variant_results)}"
            )

        # Sort both result sets
        original_sorted = sorted(original_results)
        variant_sorted = sorted(variant_results)

        for i, (orig_row, var_row) in enumerate(zip(original_sorted, variant_sorted)):
            if len(orig_row) != len(var_row):
                raise ValidationError(
                    f"Q{query_id}.{variant_id}: Column count mismatch at row {i}. "
                    f"Original: {len(orig_row)}, Variant: {len(var_row)}"
                )

            for j, (orig_val, var_val) in enumerate(zip(orig_row, var_row)):
                # Use tolerance for aggregation columns if specified
                if aggregation_columns and j in aggregation_columns:
                    if not self._numeric_values_equal(orig_val, var_val):
                        raise ValidationError(
                            f"Q{query_id}.{variant_id}: Aggregation value mismatch at row {i}, column {j}. "
                            f"Original: {orig_val}, Variant: {var_val}, Tolerance: {self.tolerance}"
                        )
                else:
                    if not self._values_equal(orig_val, var_val):
                        raise ValidationError(
                            f"Q{query_id}.{variant_id}: Value mismatch at row {i}, column {j}. "
                            f"Original: {orig_val}, Variant: {var_val}"
                        )

        return True

    def _values_equal(self, val1: Any, val2: Any) -> bool:
        """Check if two values are equal with appropriate handling for different types."""
        # Handle None values
        if val1 is None and val2 is None:
            return True
        if val1 is None or val2 is None:
            return False

        # Handle numeric values with tolerance
        if isinstance(val1, (int, float)) and isinstance(val2, (int, float)):
            return self._numeric_values_equal(val1, val2)

        # Handle string values
        if isinstance(val1, str) and isinstance(val2, str):
            return val1.strip() == val2.strip()

        # Default equality check
        return val1 == val2

    def _numeric_values_equal(self, val1: Union[int, float], val2: Union[int, float]) -> bool:
        """Check if two numeric values are equal within tolerance.

        Normalizes "missing" operands first: SQL ``NULL`` arrives as ``None`` from
        most engines but as ``float('nan')`` from ClickHouse's Arrow/pandas decode.
        Two missing values compare equal and a missing-vs-present pair does not, so
        a both-NULL aggregate is not reported as a spurious divergence and a
        NULL-vs-number stays a real one (this also keeps ``float(...)`` below from
        ever seeing ``None``/``NaN``).

        Then coerces both operands to ``float`` so a mixed-type comparison (e.g. a
        ``decimal.Decimal`` from one engine vs a ``float`` from another) is compared
        on a common type rather than raising ``TypeError`` on the ``val1 - val2``
        below. ClickHouse, for instance, returns ``Decimal`` for a
        ``SUM(decimal)/COUNT`` average where canonical ``AVG`` returns ``Float64``;
        without coercion the comparator would crash instead of reporting a clean
        match or mismatch. This is engine-agnostic robustness, not an engine-specific
        path.
        """
        val1_missing = val1 is None or (isinstance(val1, float) and math.isnan(val1))
        val2_missing = val2 is None or (isinstance(val2, float) and math.isnan(val2))
        if val1_missing or val2_missing:
            return val1_missing and val2_missing

        val1 = float(val1)
        val2 = float(val2)
        if val1 == val2:
            return True

        # For very small numbers, use absolute difference
        if abs(val1) < 1e-10 and abs(val2) < 1e-10:
            return abs(val1 - val2) < self.tolerance

        # For larger numbers, use relative difference
        try:
            relative_diff = abs(val1 - val2) / max(abs(val1), abs(val2))
            return relative_diff < self.tolerance
        except ZeroDivisionError:
            return abs(val1 - val2) < self.tolerance

    def _calculate_checksum(self, results: list[tuple[Any, ...]]) -> str:
        """Calculate MD5 checksum of result set."""
        # Convert results to a consistent string representation
        result_str = ""
        for row in sorted(results):
            row_str = "|".join(str(val) if val is not None else "NULL" for val in row)
            result_str += row_str + "\n"

        return hashlib.md5(result_str.encode("utf-8")).hexdigest()

    def validate_query1_results(
        self,
        original_results: list[tuple[Any, ...]],
        variant_results: list[tuple[Any, ...]],
        variant_id: int,
    ) -> bool:
        """Specialized validation for Query 1 results.

        Query 1 has specific aggregation columns that need special handling.

        Args:
            original_results: Results from original TPC-H Query 1
            variant_results: Results from Query 1 variant
            variant_id: The variant ID being validated

        Returns:
            True if results match

        Raises:
            ValidationError: If results don't match
        """
        # Query 1 result columns:
        # 0: l_returnflag (string)
        # 1: l_linestatus (string)
        # 2: sum_qty (numeric aggregation)
        # 3: sum_base_price (numeric aggregation)
        # 4: sum_disc_price (numeric aggregation)
        # 5: sum_charge (numeric aggregation)
        # 6: avg_qty (numeric aggregation)
        # 7: avg_price (numeric aggregation)
        # 8: avg_disc (numeric aggregation)
        # 9: count_order (integer count)

        aggregation_columns = [
            2,
            3,
            4,
            5,
            6,
            7,
            8,
        ]  # All numeric aggregations except count

        return self.validate_aggregation_results(
            original_results,
            variant_results,
            query_id=1,
            variant_id=variant_id,
            aggregation_columns=aggregation_columns,
        )


class ValidationReport:
    """Generates validation reports for query variants."""

    def __init__(self) -> None:
        """Initialize validation report generator."""
        self.results: dict[str, dict[str, Any]] = {}

    def add_validation_result(
        self,
        query_id: int,
        variant_id: int,
        success: bool,
        error_message: Optional[str] = None,
        execution_time_original: Optional[float] = None,
        execution_time_variant: Optional[float] = None,
    ) -> None:
        """Add a validation result to the report.

        Args:
            query_id: The query ID
            variant_id: The variant ID
            success: Whether validation succeeded
            error_message: Error message if validation failed
            execution_time_original: Execution time for original query
            execution_time_variant: Execution time for variant query
        """
        key = f"Q{query_id}.{variant_id}"
        self.results[key] = {
            "query_id": query_id,
            "variant_id": variant_id,
            "success": success,
            "error_message": error_message,
            "execution_time_original": execution_time_original,
            "execution_time_variant": execution_time_variant,
            "performance_ratio": (
                execution_time_variant / execution_time_original
                if execution_time_original and execution_time_variant and execution_time_original > 0
                else None
            ),
        }

    def get_summary(self) -> dict[str, Any]:
        """Get summary of validation results.

        Returns:
            Dictionary containing validation summary statistics
        """
        total_tests = len(self.results)
        successful_tests = sum(1 for result in self.results.values() if result["success"])
        failed_tests = total_tests - successful_tests

        return {
            "total_tests": total_tests,
            "successful_tests": successful_tests,
            "failed_tests": failed_tests,
            "success_rate": successful_tests / total_tests if total_tests > 0 else 0.0,
            "failed_queries": [
                f"Q{result['query_id']}.{result['variant_id']}"
                for result in self.results.values()
                if not result["success"]
            ],
        }

    def get_performance_summary(self) -> dict[str, Any]:
        """Get performance comparison summary.

        Returns:
            Dictionary containing performance statistics
        """
        performance_ratios = [
            result["performance_ratio"] for result in self.results.values() if result["performance_ratio"] is not None
        ]

        if not performance_ratios:
            return {"message": "No performance data available"}

        return {
            "min_ratio": min(performance_ratios),
            "max_ratio": max(performance_ratios),
            "avg_ratio": sum(performance_ratios) / len(performance_ratios),
            "variants_faster": sum(1 for ratio in performance_ratios if ratio < 1.0),
            "variants_slower": sum(1 for ratio in performance_ratios if ratio > 1.0),
            "variants_similar": sum(1 for ratio in performance_ratios if 0.9 <= ratio <= 1.1),
        }

    def generate_report(self) -> str:
        """Generate a formatted validation report.

        Returns:
            Formatted string report
        """
        summary = self.get_summary()
        perf_summary = self.get_performance_summary()

        report = f"""
TPC-Havoc Validation Report
===========================

Summary:
--------
Total Tests: {summary["total_tests"]}
Successful: {summary["successful_tests"]}
Failed: {summary["failed_tests"]}
Success Rate: {summary["success_rate"]:.2%}

"""

        if summary["failed_tests"] > 0:
            report += f"Failed Queries: {', '.join(summary['failed_queries'])}\n\n"

        if "message" not in perf_summary:
            report += f"""Performance Summary:
-------------------
Fastest Variant Ratio: {perf_summary["min_ratio"]:.2f}x
Slowest Variant Ratio: {perf_summary["max_ratio"]:.2f}x
Average Ratio: {perf_summary["avg_ratio"]:.2f}x
Variants Faster: {perf_summary["variants_faster"]}
Variants Slower: {perf_summary["variants_slower"]}
Variants Similar: {perf_summary["variants_similar"]}

"""

        report += "Detailed Results:\n"
        report += "-----------------\n"
        for key, result in sorted(self.results.items()):
            status = "✅" if result["success"] else "❌"
            report += f"{status} {key}: {result.get('error_message', 'Success')}\n"

        return report
