"""TPC-Havoc result validation utilities.

This module provides functionality to validate that query variants produce
identical results to the original TPC-H queries.

Copyright 2026 Joe Harris / BenchBox Project

This implementation is derived from TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import hashlib
import math
from collections.abc import Sequence
from typing import Any, Optional, Union


def calculate_checksum(results: list[tuple[Any, ...]]) -> str:
    """Calculate an order-normalized MD5 digest of a single result set.

    This is the canonical single-result digest primitive for BenchBox. Rows are
    sorted before hashing so unordered queries hash stably, and each cell is
    rendered with ``str`` (``None`` -> ``"NULL"``). It backs both the TPC-Havoc
    equivalence comparators (:meth:`ResultValidator.validate_results_checksum`)
    and the bounded correctness gate's value-digest oracle, so SQL results and
    the gate share exactly one digest definition.

    Callers that need cross-build numeric stability (e.g. the gate, which stores
    a reference digest) should normalize numeric precision *before* calling this
    (see :func:`benchbox.core.results.result_digest.compute_result_digest`).

    Args:
        results: Result set as a list of row tuples.

    Returns:
        Hex-encoded MD5 digest string.
    """
    # Convert results to a consistent string representation. Sort on the None-safe
    # surrogate so a NULL-bearing or mixed-type column never raises TypeError here
    # (a caller would otherwise mislabel that as an execution "error:").
    result_str = ""
    for row in sorted(results, key=_row_sort_key):
        row_str = "|".join(str(val) if val is not None else "NULL" for val in row)
        result_str += row_str + "\n"

    return hashlib.md5(result_str.encode("utf-8")).hexdigest()


def _cell_sort_key(value: Any) -> tuple[Any, ...]:
    """A None-safe, type-safe sort surrogate for one result cell.

    Python ``sorted`` raises ``TypeError`` on a column mixing ``None`` with a value
    or mixing types. This maps every cell to a ``(type_rank, type_name, value)``
    triple so ordering is total and never raises: ``None`` sorts first, and values
    of different types group by a stable type name rather than comparing across
    types. ``bool`` folds into the numeric bucket (it subclasses ``int``) so it
    sorts consistently with equality (``True == 1``). Used only to impose a stable
    order; it never changes a match/mismatch verdict.
    """
    if value is None:
        return (0, "", 0.0)
    if isinstance(value, (int, float)):  # includes bool (subclass of int)
        return (1, "num", float(value))
    return (1, type(value).__name__, str(value))


def _row_sort_key(row: tuple[Any, ...]) -> tuple[Any, ...]:
    """A total, never-raising sort key for a result row (see :func:`_cell_sort_key`)."""
    return tuple(_cell_sort_key(value) for value in row)


class ValidationError(Exception):
    """Exception raised when query variant validation fails."""


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
        *,
        tie_aware: bool = False,
        order_aware: bool = False,
        order_by: Sequence[int] | None = None,
        final_key_tied_beyond_limit: bool = False,
    ) -> bool:
        """Validate exact result matching between original and variant.

        Args:
            original_results: Results from original TPC-H query
            variant_results: Results from variant query
            query_id: The query ID being validated
            variant_id: The variant ID being validated
            tie_aware: When True, additionally accept a divergence that is purely
                a tie-ambiguous top-N boundary (an ``ORDER BY <col> ... LIMIT N``
                whose ties span the LIMIT cutoff, so each surface keeps a
                different but equally-valid subset of the tied rows). Off by
                default, so the strict comparison is unchanged for existing
                callers (e.g. the TPC-Havoc gates, which strip the LIMIT and have
                no truncated boundary). The relaxation only engages AFTER the
                strict comparison fails and only when the deterministic
                (non-boundary) rows still match exactly, so genuine
                value-misplacement bugs are still caught - it is NOT whole-row
                set-equality.
            order_aware: When True (and ``order_by`` resolves the query's
                ``ORDER BY`` key to result-column positions), compare the rows in
                RETURNED order instead of full-row-sorting both sides. The
                sequence of distinct order-key values must match exactly (so a
                reversed ``ORDER BY`` is CAUGHT), while rows that share an
                order-key value - an engine-arbitrary tie group - are compared as
                a multiset (so a legitimate tie reshuffle is NOT flagged). The
                final tie group additionally tolerates a truncated-``LIMIT``
                boundary swap (the ``tie_aware`` relaxation), so tie false
                positives stay fixed. Off by default, so the strict comparison is
                unchanged for callers that do not opt in (the TPC-Havoc gates).
            order_by: Sequence of RESULT-row column indices forming the query's
                ``ORDER BY`` key, in key order (resolved by the caller, e.g.
                ``cross_surface._order_by_result_key``). Only the columns matter,
                not the sort DIRECTION: the comparator catches a reversed
                ``ORDER BY`` by detecting that the RETURNED sequence of distinct
                key values differs, which is direction-independent. Required for
                ``order_aware`` to engage; an empty/None key (no ``ORDER BY``, or
                an ``ORDER BY`` whose key is not present in the projected columns)
                falls back to the order-insensitive comparison, never silently
                claiming an order check it cannot perform.
            final_key_tied_beyond_limit: A boundary-tie probe result for the
                order-aware path, supplied by the caller (e.g.
                ``cross_surface._final_key_tied_beyond_limit``, which re-runs the
                trailing-``LIMIT`` query one row wider). True when the reference's
                FINAL ``ORDER BY`` key value genuinely recurs PAST the ``LIMIT``
                cutoff, so a final tie group that shows only ONE visible row is a
                truncated boundary tie (one arbitrary pick among rows tied at the
                worst-kept key) rather than a deterministic last row. It only
                RELAXES the order-aware final-group check, and only for a
                single-visible-row group: a final group with >= 2 visible tied rows
                is already accepted as a boundary swap, and a single-visible-row
                group whose key does NOT tie past the cutoff stays a CAUGHT mismatch
                (so a unique-final-key value bug like ``(2,"good")`` vs
                ``(2,"bad")`` is still reported). Off by default, so callers that do
                not run the probe keep the strict single-row behavior.

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

        # Order-aware engages only when a non-empty key is supplied AND every key
        # column is in range for the actual result width on both sides. An
        # out-of-range index (e.g. the caller's SQL-derived projection count ever
        # disagreeing with the materialized result width) would make ``row[c]``
        # raise IndexError - which a caller would mislabel as an execution "error:"
        # rather than a clean verdict - so we fall back to the order-insensitive
        # comparison instead of indexing a column that does not exist. The
        # order-insensitive path is the sound default when the order key cannot be
        # located in the result (the same stance _order_by_result_key takes for an
        # unmappable ORDER BY).
        if order_aware and order_by and self._order_key_in_range(order_by, original_results, variant_results):
            return self._validate_order_aware(
                original_results,
                variant_results,
                query_id,
                variant_id,
                order_by,
                tie_aware=tie_aware,
                final_key_tied_beyond_limit=final_key_tied_beyond_limit,
            )

        # Sort both result sets to handle potential ordering differences
        # (though TPC-H queries should have deterministic ordering). A NULL-bearing
        # or mixed-type column cannot be ordered by Python ``sorted`` directly, so
        # sort on a None-safe surrogate rather than the raw row (a bare ``sorted``
        # would raise TypeError, which a caller would then mislabel as an execution
        # "error:" instead of a clean MISMATCH/match - see _row_sort_key).
        original_sorted = sorted(original_results, key=self._row_sort_key)
        variant_sorted = sorted(variant_results, key=self._row_sort_key)

        detail = self._first_positional_mismatch(original_sorted, variant_sorted, query_id, variant_id)
        if detail is None:
            return True

        if tie_aware and self._is_boundary_tie_equivalent(original_results, variant_results, query_id, variant_id):
            return True

        raise ValidationError(detail)

    def _first_column_count_mismatch(
        self,
        original: list[tuple[Any, ...]],
        variant: list[tuple[Any, ...]],
        query_id: int,
        variant_id: int,
    ) -> str | None:
        """Return the first row whose two sides differ in column count, or None.

        Assumes equal row counts (the caller checked). Used by the order-aware path
        to surface a projection-width change (e.g. a dropped GROUP BY key) as a
        clean column-count MISMATCH before indexing the order-key columns, rather
        than letting an out-of-range index raise.
        """
        for i, (orig_row, var_row) in enumerate(zip(original, variant)):
            if len(orig_row) != len(var_row):
                return (
                    f"Q{query_id}.{variant_id}: Column count mismatch at row {i}. "
                    f"Original: {len(orig_row)}, Variant: {len(var_row)}"
                )
        return None

    @staticmethod
    def _order_key_in_range(
        key_columns: Sequence[int],
        original: list[tuple[Any, ...]],
        variant: list[tuple[Any, ...]],
    ) -> bool:
        """True if every order-key column index is valid for every row on both sides.

        Guards the order-aware path from an ``IndexError`` when the caller's
        SQL-derived column positions ever exceed the actual result width (so an
        unsound mapping falls back to the order-insensitive comparison instead of
        crashing into a mislabeled ``error:``). An empty result trivially satisfies
        this (there is no row to index).
        """
        if not key_columns:
            return False
        max_index = max(key_columns)
        if max_index < 0:
            return False
        return all(len(row) > max_index for row in original) and all(len(row) > max_index for row in variant)

    def _validate_order_aware(
        self,
        original: list[tuple[Any, ...]],
        variant: list[tuple[Any, ...]],
        query_id: int,
        variant_id: int,
        key_columns: Sequence[int],
        *,
        tie_aware: bool,
        final_key_tied_beyond_limit: bool = False,
    ) -> bool:
        """Compare two results in RETURNED order, tolerating only tie-group reshuffles.

        ``original`` is the trusted reference in its ``ORDER BY`` order. The key is
        ``key_columns`` (positions into the result row). Rows are partitioned, in
        returned order, into consecutive runs sharing the same order-key value (a
        tie group). The COMPARISON:

          1. The sequence of order-key values must be identical between the two
             results (same values, same order). A reversed ``ORDER BY`` produces a
             reversed key sequence and is therefore CAUGHT here - this is the BS2
             fix.
          2. Within each tie group the row ORDER is engine-arbitrary, so the two
             groups are compared as MULTISETS (full-row), not positionally. A
             legitimate tie reshuffle passes; a value bug inside a group still
             fails the multiset check.
          3. The FINAL tie group may be truncated by a trailing ``LIMIT`` that
             cuts across the tie, so when ``tie_aware`` is set its membership is
             allowed to differ as an ambiguous boundary swap - but ONLY when the
             group is genuinely a tie at the cutoff, not a deterministic last row:
               * >= 2 visible rows share the final order key, so a real tie is
                 present in the result and a membership swap among them is an
                 equally-valid boundary pick; OR
               * exactly ONE visible row remains, but ``final_key_tied_beyond_limit``
                 (the caller's boundary-tie probe) confirms the final key genuinely
                 ties PAST the ``LIMIT`` cutoff, so the lone row is one arbitrary
                 pick among rows tied at the worst-kept key.
             A single visible row whose key does NOT tie beyond the cutoff is a
             deterministic last row: a difference there is a real value change
             (e.g. ``(2,"good")`` vs ``(2,"bad")``) and is still CAUGHT. This is
             sound because the group is keyed by the ACTUAL ``ORDER BY`` value and
             the total row count already matched, so an accepted difference can only
             be an equally-valid tie pick across the cutoff - not a reordering of
             distinct order-key values.

        Raises ``ValidationError`` on the first divergence, mirroring the strict
        path's contract.
        """
        # Column-count guard. The order-key columns index into every row, so a
        # candidate row that is too NARROW (e.g. a dropped GROUP BY key shrank the
        # projection) must surface as a clean column-count MISMATCH here, not as an
        # IndexError that the harness would mislabel as an execution "error:". Check
        # both sides positionally up front; a width difference is a real divergence.
        detail = self._first_column_count_mismatch(original, variant, query_id, variant_id)
        if detail is not None:
            raise ValidationError(detail)

        original_groups = self._group_by_order_key(original, key_columns)
        variant_groups = self._group_by_order_key(variant, key_columns)

        if len(original_groups) != len(variant_groups):
            raise ValidationError(
                f"Q{query_id}.{variant_id}: ORDER BY tie-group count mismatch. "
                f"Original: {len(original_groups)}, Variant: {len(variant_groups)} "
                f"(order-key columns {key_columns}) - the returned order differs."
            )

        last_index = len(original_groups) - 1
        for i, ((orig_key, orig_rows), (var_key, var_rows)) in enumerate(zip(original_groups, variant_groups)):
            if not self._order_keys_equal(orig_key, var_key):
                raise ValidationError(
                    f"Q{query_id}.{variant_id}: ORDER BY key mismatch at position {i}. "
                    f"Original key: {orig_key}, Variant key: {var_key} "
                    f"(order-key columns {key_columns}) - the returned order differs "
                    f"(e.g. a reversed ORDER BY)."
                )
            if self._multisets_equal(orig_rows, var_rows):
                continue
            # The FINAL group under a trailing LIMIT can be a truncated boundary
            # tie: all its rows share the order key (that is what defines the group)
            # and the total row count already matched, so a membership difference can
            # be an equally-valid tie pick across the cutoff. Accept it ONLY when the
            # group is genuinely a tie at the boundary, not a deterministic last row:
            #   * >= 2 visible rows share the final key (a real tie is present in the
            #     result, so a swap among them is an ambiguous boundary pick), OR
            #   * exactly one visible row but the caller's boundary-tie probe says
            #     that key ties PAST the LIMIT (final_key_tied_beyond_limit).
            # A single visible row whose key does NOT tie beyond the cutoff is
            # deterministic, so a difference there (e.g. (2,"good") vs (2,"bad")) is a
            # real value change and falls through to be CAUGHT below. This is sound
            # because the group is keyed by the actual ORDER BY value, so a
            # genuinely-ordered row is never mistaken for a boundary tie. Earlier
            # groups are complete windows and must match as multisets, so a value bug
            # there is still caught. (Residual limitation, inherited from the #872/#878
            # design: the >= 2 branch accepts a final-group multiset difference even
            # when the LIMIT did not truncate that tie - e.g. a complete, table-
            # exhausted final group. The boundary-tie probe only refines the
            # single-visible-row case it was scoped to; it is NOT the order-blind
            # path's stronger boundary-value+extreme proof.)
            if i == last_index and tie_aware and (len(orig_rows) >= 2 or final_key_tied_beyond_limit):
                continue
            detail = self._first_positional_mismatch(
                sorted(orig_rows, key=self._row_sort_key),
                sorted(var_rows, key=self._row_sort_key),
                query_id,
                variant_id,
            )
            raise ValidationError(
                detail
                or (
                    f"Q{query_id}.{variant_id}: ORDER BY tie group at position {i} differs as a multiset "
                    f"(order-key {orig_key})."
                )
            )
        return True

    def _group_by_order_key(
        self, rows: list[tuple[Any, ...]], key_columns: list[int]
    ) -> list[tuple[tuple[Any, ...], list[tuple[Any, ...]]]]:
        """Partition ``rows`` (in returned order) into consecutive same-key runs.

        Returns a list of ``(order_key_tuple, rows_in_that_group)`` preserving the
        returned order of the groups. Consecutive rows whose order-key columns are
        equal (via :meth:`_values_equal`, so float tolerance / NULL handling match
        the rest of the comparator) form one group.
        """
        groups: list[tuple[tuple[Any, ...], list[tuple[Any, ...]]]] = []
        for row in rows:
            key = tuple(row[c] for c in key_columns)
            if groups and self._order_keys_equal(groups[-1][0], key):
                groups[-1][1].append(row)
            else:
                groups.append((key, [row]))
        return groups

    def _order_keys_equal(self, a: tuple[Any, ...], b: tuple[Any, ...]) -> bool:
        """Element-wise order-key equality using the comparator's value semantics."""
        return len(a) == len(b) and all(self._values_equal(x, y) for x, y in zip(a, b))

    def _multisets_equal(self, left: list[tuple[Any, ...]], right: list[tuple[Any, ...]]) -> bool:
        """True if ``left`` and ``right`` are equal as full-row multisets.

        Sorts both on the None-safe :meth:`_row_sort_key` (so a NULL-mixed column
        never raises) and compares positionally with :meth:`_values_equal`, so the
        float tolerance and NULL handling stay identical to the strict path.
        """
        if len(left) != len(right):
            return False
        left_sorted = sorted(left, key=self._row_sort_key)
        right_sorted = sorted(right, key=self._row_sort_key)
        return all(self._order_keys_equal(lhs, rhs) for lhs, rhs in zip(left_sorted, right_sorted))

    def _row_sort_key(self, row: tuple[Any, ...]) -> tuple[Any, ...]:
        """A total, never-raising sort key for a result row.

        Python ``sorted`` raises ``TypeError`` on a column mixing ``None`` with a
        value (``None < 1`` is unorderable) and on a column mixing types. This
        surrogate replaces every cell with a ``(type_rank, type_name, value)``
        triple so ordering is deterministic and total without raising: ``None``
        sorts before any value, and values of different types are grouped by a
        stable type name rather than compared across types. It is used ONLY to
        impose a stable order for positional comparison; equality is still decided
        by :meth:`_values_equal`, so this never changes a match/mismatch verdict -
        it only stops a NULL-bearing or mixed-type column from raising (which a
        caller would otherwise mislabel as an execution ``error:`` rather than a
        clean MISMATCH).

        Delegates to the module-level :func:`_row_sort_key` so the comparator and
        the value-digest primitive (:func:`calculate_checksum`) share exactly one
        sort definition.
        """
        return _row_sort_key(row)

    @staticmethod
    def _cell_sort_key(value: Any) -> tuple[Any, ...]:
        """A None-safe, type-safe sort surrogate for one cell (see _row_sort_key).

        Thin wrapper over the module-level :func:`_cell_sort_key`; ``bool`` folds
        into the numeric bucket so it sorts CONSISTENTLY with :meth:`_values_equal`
        (``True == 1``).
        """
        return _cell_sort_key(value)

    def _first_positional_mismatch(
        self,
        original_sorted: list[tuple[Any, ...]],
        variant_sorted: list[tuple[Any, ...]],
        query_id: int,
        variant_id: int,
    ) -> str | None:
        """Return the first row/column mismatch detail, or None if equal.

        Assumes the two lists have equal length and are already sorted. Reused by
        both the strict path and the tie-aware deterministic-remainder check so
        the comparison semantics (``_values_equal`` tolerance) stay identical.
        """
        for i, (orig_row, var_row) in enumerate(zip(original_sorted, variant_sorted)):
            if len(orig_row) != len(var_row):
                return (
                    f"Q{query_id}.{variant_id}: Column count mismatch at row {i}. "
                    f"Original: {len(orig_row)}, Variant: {len(var_row)}"
                )
            for j, (orig_val, var_val) in enumerate(zip(orig_row, var_row)):
                if not self._values_equal(orig_val, var_val):
                    return (
                        f"Q{query_id}.{variant_id}: Value mismatch at row {i}, column {j}. "
                        f"Original: {orig_val}, Variant: {var_val}"
                    )
        return None

    def _is_boundary_tie_equivalent(
        self,
        original: list[tuple[Any, ...]],
        variant: list[tuple[Any, ...]],
        query_id: int,
        variant_id: int,
    ) -> bool:
        """True if the only difference is an ambiguous top-N boundary tie.

        ``original`` is the trusted reference in its query (``ORDER BY``) order. A
        top-N whose order-key value ties across the ``LIMIT`` cutoff lets each
        surface keep a different but equally-valid subset of the tied rows. This
        accepts that case - and ONLY that case - deterministically:

          1. The differing rows are the multiset difference each way (the swapped
             tie members); the rest are byte-identical and thus deterministic.
          2. There must be an order-key column ``c`` - one that is monotonic
             across the reference result (the ``ORDER BY`` key is; a grouped
             non-key column generally is not) - whose value on EVERY swapped row
             (both sides) equals the reference's boundary value ``original[-1][c]``
             (stable run to run even when tied rows reorder), and that boundary
             value is an extreme (min/max) of the column. Then the swap is exactly
             an ambiguous selection among rows tied at the worst-kept order key.

        A real value-misplacement bug outside the tie puts a non-boundary value
        into the swapped set (or breaks the shared remainder), so no qualifying
        column exists and it still fails - this is NOT whole-row set-equality.
        """
        if not original or not variant or len(original[0]) != len(variant[0]):
            return False

        from collections import Counter

        try:
            only_original = list((Counter(original) - Counter(variant)).elements())
            only_variant = list((Counter(variant) - Counter(original)).elements())
        except TypeError:
            # Unhashable cell -> cannot reason about ties safely; stay strict.
            return False

        if not only_original or not only_variant:
            return False  # identical multisets would have passed the strict check

        swapped = only_original + only_variant
        candidate_cols = self._monotonic_columns(original)
        # A constant column carries no ordering information, so a literal/constant
        # result column (e.g. ClickBench Q35's ``SELECT 1``) must not serve as the
        # tie-boundary key while a genuinely-ordered column exists - otherwise an
        # arbitrary swap that perturbs the real order key would be masked. Prefer
        # varying monotonic columns; fall back to constant ones ONLY when no
        # monotonic column varies (a fully-tied top-N window, e.g. ORDER BY c DESC
        # LIMIT 10 where every kept row has c=1, whose constant order key IS the
        # legitimate boundary).
        varying_cols = [c for c in candidate_cols if not self._column_is_constant(original, c)]
        boundary_cols = varying_cols or candidate_cols
        for c in boundary_cols:
            boundary_value = original[-1][c]
            if boundary_value is None:
                continue
            column = [row[c] for row in original]
            # A genuine boundary tie needs >= 2 reference rows sharing the worst-kept
            # value; a unique boundary row is deterministic and must still match.
            if sum(1 for v in column if self._values_equal(v, boundary_value)) < 2:
                continue
            if any(not self._values_equal(row[c], boundary_value) for row in swapped):
                continue  # a swapped row is NOT at the boundary order-key value
            present = [v for v in column if v is not None]
            try:
                at_extreme = self._values_equal(boundary_value, min(present)) or self._values_equal(
                    boundary_value, max(present)
                )
            except TypeError:
                continue
            if at_extreme:
                return True
        return False

    def _monotonic_columns(self, rows: list[tuple[Any, ...]]) -> list[int]:
        """Column indices whose values are monotonic across ``rows`` (in order).

        A top-N result is sorted by its order key, so the order-key column is
        monotonic (non-decreasing or non-increasing, constant counts as both); a
        grouped non-key column generally is not. A column with an unorderable or
        NULL-mixed value is treated as non-monotonic (excluded), which only makes
        the boundary split finer (stricter), never weaker. Constant columns are
        retained here (a fully-tied top-N window has a constant order key);
        ``_is_boundary_tie_equivalent`` decides when a constant column may serve as
        the boundary key.
        """
        if len(rows) < 2:
            return []
        width = len(rows[0])
        result: list[int] = []
        for c in range(width):
            non_decreasing = True
            non_increasing = True
            for left, right in zip(rows, rows[1:]):
                order = self._safe_compare(left[c], right[c])
                if order is None:
                    non_decreasing = non_increasing = False
                    break
                if order < 0:
                    non_increasing = False
                elif order > 0:
                    non_decreasing = False
            if non_decreasing or non_increasing:
                result.append(c)
        return result

    def _column_is_constant(self, rows: list[tuple[Any, ...]], c: int) -> bool:
        """True if every row shares the same value in column ``c`` (NULLs included)."""
        if not rows:
            return True
        first = rows[0][c]
        return all(self._values_equal(row[c], first) for row in rows)

    def _safe_compare(self, a: Any, b: Any) -> int | None:
        """Return -1/0/1 for an orderable pair, or None if not orderable.

        Uses ``_values_equal`` for equality (so float tolerance and NULL handling
        match the rest of the comparator) and a plain ``<`` otherwise.
        """
        if self._values_equal(a, b):
            return 0
        if a is None or b is None:
            return None
        try:
            return -1 if a < b else 1
        except TypeError:
            return None

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

        # Sort both result sets on the None-safe surrogate so a NULL-bearing or
        # mixed-type column never raises TypeError (see _row_sort_key).
        original_sorted = sorted(original_results, key=self._row_sort_key)
        variant_sorted = sorted(variant_results, key=self._row_sort_key)

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
        """Calculate MD5 checksum of result set.

        Thin instance wrapper over the promoted module-level
        :func:`calculate_checksum`; kept for API stability of existing callers.
        Both sort on the None-safe surrogate (:func:`_row_sort_key`) so a
        NULL-bearing or mixed-type column never raises ``TypeError`` here (matching
        the order-insensitive comparison path).
        """
        return calculate_checksum(results)

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
