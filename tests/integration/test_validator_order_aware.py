"""Fast, no-DB guards for the order-aware comparator + None-safe sort (w2/BS2).

The shared :class:`~benchbox.core.tpchavoc.validation.ResultValidator` gained an
opt-in ``order_aware`` mode (used by the cross-surface SQL<->DataFrame gates for
any query that declares an ``ORDER BY`` whose key maps to result-column
positions) and a None-safe sort surrogate. These guards pin the two halves of
BS2 WITHOUT a database so a regression is caught in the fast lane:

* ORDER-BY blindness: a reversed ``ORDER BY`` over a multi-row result must be a
  MISMATCH (previously it passed silently because both sides were full-row
  sorted), while a legitimate tie-group reshuffle and a truncated-LIMIT boundary
  swap must still PASS (the tie-aware fix must not regress).
* The None/non-None ``sorted()`` crash: a result column mixing ``None`` with a
  value must yield a clean MISMATCH (if it differs) or a clean pass (if equal),
  never a ``TypeError`` that the gate would mislabel as an ``error:``.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

from benchbox.core.tpchavoc.validation import ResultValidator, ValidationError

pytestmark = [
    pytest.mark.integration,
    pytest.mark.tpchavoc,
    pytest.mark.fast,
]


def _validator() -> ResultValidator:
    return ResultValidator(tolerance=1e-10)


# --- Order-aware: a reversed ORDER BY is now CAUGHT ------------------------------


def test_order_aware_reversed_order_is_a_mismatch():
    """A reversed ORDER BY over a multi-row result is reported (the BS2 fix)."""
    validator = _validator()
    # ORDER BY col0 ASC, col1 DESC -> order key columns [0, 1].
    reference = [(1, 100, "a"), (1, 90, "b"), (2, 50, "c"), (3, 10, "d")]
    order_by = [0, 1]
    # Identical order passes.
    assert validator.validate_results_exact(reference, list(reference), 3, 1, order_aware=True, order_by=order_by)
    # Reversed order is a MISMATCH (it would have passed under the full-row sort).
    with pytest.raises(ValidationError) as exc_info:
        validator.validate_results_exact(
            reference, list(reversed(reference)), 3, 1, order_aware=True, order_by=order_by, tie_aware=True
        )
    assert "ORDER BY" in str(exc_info.value)


def test_order_aware_passes_under_legacy_full_row_sort():
    """The same reversed result passes the old order-insensitive comparison.

    Pins that the catch is genuinely the NEW order-aware path, not a pre-existing
    property: without ``order_aware`` the comparator full-row-sorts and the
    reversed result (same multiset) still passes.
    """
    validator = _validator()
    reference = [(1, 100, "a"), (1, 90, "b"), (2, 50, "c"), (3, 10, "d")]
    assert validator.validate_results_exact(reference, list(reversed(reference)), 3, 1)


# --- Order-aware: legitimate tie reshuffles and boundary swaps still PASS --------


def test_order_aware_tie_group_reshuffle_is_not_flagged():
    """Rows sharing an order-key value are a multiset; reshuffling them passes."""
    validator = _validator()
    # ORDER BY col0 ASC; the last group (col0 == 2) ties over rows b and c.
    reference = [(1, "a"), (2, "b"), (2, "c")]
    reshuffled = [(1, "a"), (2, "c"), (2, "b")]
    order_by = [0]
    assert validator.validate_results_exact(reference, reshuffled, 3, 1, order_aware=True, order_by=order_by)


def test_order_aware_truncated_limit_boundary_swap_is_not_flagged():
    """A trailing-LIMIT boundary tie swap on the final group still passes."""
    validator = _validator()
    # ORDER BY col0 DESC ... LIMIT 3 over rows tied at the boundary value 5:
    # each surface keeps a different but equally-valid subset of the tied rows.
    reference = [(9, "x"), (5, "a"), (5, "b")]
    variant = [(9, "x"), (5, "a"), (5, "c")]
    order_by = [0]
    assert validator.validate_results_exact(
        reference,
        variant,
        3,
        1,
        order_aware=True,
        order_by=order_by,
        tie_aware=True,
        final_key_tied_beyond_limit=True,
    )


def test_order_aware_complete_final_tie_group_value_bug_is_caught():
    """A complete multi-row final tie must match; row count alone is not enough."""
    validator = _validator()
    # ORDER BY col0 DESC LIMIT 3 over exactly these three rows. The final key 5 is
    # tied in the visible result, but no key-5 row exists beyond the LIMIT, so this
    # is a complete final tie group. A different tied member is a real value bug.
    reference = [(9, "x"), (5, "a"), (5, "b")]
    bug = [(9, "x"), (5, "a"), (5, "c")]
    order_by = [0]
    with pytest.raises(ValidationError):
        validator.validate_results_exact(reference, bug, 3, 1, order_aware=True, order_by=order_by, tie_aware=True)


def test_order_aware_multi_row_final_tie_group_accepts_only_with_probe():
    """A multi-row final tie swap is accepted only when the probe proves truncation."""
    validator = _validator()
    reference = [(9, "x"), (5, "a"), (5, "b")]
    variant = [(9, "x"), (5, "a"), (5, "c")]
    order_by = [0]
    assert validator.validate_results_exact(
        reference,
        variant,
        3,
        1,
        order_aware=True,
        order_by=order_by,
        tie_aware=True,
        final_key_tied_beyond_limit=True,
    )


def test_order_aware_value_bug_in_non_tie_row_is_caught():
    """A value bug in a deterministically-ordered (non-tie) row is still a MISMATCH."""
    validator = _validator()
    reference = [(1, 100, "a"), (2, 90, "b"), (3, 50, "c")]
    bug = [(1, 100, "a"), (2, 90, "WRONG"), (3, 50, "c")]
    order_by = [0]
    with pytest.raises(ValidationError):
        validator.validate_results_exact(reference, bug, 3, 1, order_aware=True, order_by=order_by, tie_aware=True)


# --- Order-aware: one-visible-row boundary tie vs unique-final-key value bug ------


def test_order_aware_single_row_final_group_value_bug_is_caught():
    """A value change on a UNIQUE final order-key row is caught, not masked as a tie.

    The final-group tie relaxation only applies to a genuine tie (>= 2 visible rows
    sharing the final key, OR a probe confirming the key ties past the LIMIT). When
    the final key is unique and no probe says otherwise, its single row is
    deterministic, so a non-key value change there (``good`` -> ``bad``) is a real
    regression and must still raise even with ``tie_aware``. This pins #878's intent
    (the single-row final group is no longer unconditionally accepted).
    """
    validator = _validator()
    reference = [(1, "ok"), (2, "good")]
    bug = [(1, "ok"), (2, "bad")]
    order_by = [0]
    with pytest.raises(ValidationError):
        validator.validate_results_exact(reference, bug, 3, 1, order_aware=True, order_by=order_by, tie_aware=True)


def test_order_aware_one_visible_row_boundary_tie_accepted_only_with_probe():
    """A one-visible-row final tie is accepted ONLY when the probe says it ties past LIMIT.

    Keys ``10, 5, 5`` with ``LIMIT 2`` return ``[10, 5]`` - exactly one row of the
    boundary tie (key 5) stays visible, so two surfaces picking different ``5`` rows
    is valid SQL. That single-visible-row final group is structurally identical to a
    genuine unique-final-key value bug in the truncated result, so it is accepted
    ONLY when ``final_key_tied_beyond_limit`` (the cross-surface boundary-tie probe)
    confirms the key 5 recurs past the cutoff; without that signal the same diff
    stays a CAUGHT mismatch (the conservative default).
    """
    validator = _validator()
    reference = [(10, "x"), (5, "a")]
    variant = [(10, "x"), (5, "b")]  # the lone visible boundary-tie member differs
    order_by = [0]
    # Probe confirms key 5 is tied beyond LIMIT 2 -> the swap is a valid boundary pick.
    assert validator.validate_results_exact(
        reference,
        variant,
        3,
        1,
        order_aware=True,
        order_by=order_by,
        tie_aware=True,
        final_key_tied_beyond_limit=True,
    )
    # Default (no probe signal): the same single-row difference is CAUGHT, so a genuine
    # unique-final-key value bug is never masked.
    with pytest.raises(ValidationError):
        validator.validate_results_exact(reference, variant, 3, 1, order_aware=True, order_by=order_by, tie_aware=True)


def test_order_aware_dropped_column_is_a_clean_column_count_mismatch():
    """A narrower candidate (dropped projection) reports a column-count MISMATCH.

    The order-key columns index into every row, so a too-narrow candidate must
    surface as a clean MISMATCH, not an IndexError the gate would mislabel
    ``error:``.
    """
    validator = _validator()
    reference = [(1, 100, "a"), (2, 90, "b")]
    dropped = [(100, "a"), (90, "b")]  # leading column dropped
    order_by = [0]
    with pytest.raises(ValidationError) as exc_info:
        validator.validate_results_exact(reference, dropped, 3, 1, order_aware=True, order_by=order_by)
    assert "Column count mismatch" in str(exc_info.value)


def test_order_aware_falls_back_when_no_order_key():
    """``order_aware`` with an empty/None key uses the order-insensitive path."""
    validator = _validator()
    reference = [(2, "b"), (1, "a")]
    same_multiset_reordered = [(1, "a"), (2, "b")]
    # No order key supplied -> falls back to the order-insensitive comparison,
    # which passes the reordered multiset (never claims an order check it lacks).
    assert validator.validate_results_exact(reference, same_multiset_reordered, 3, 1, order_aware=True, order_by=None)
    assert validator.validate_results_exact(reference, same_multiset_reordered, 3, 1, order_aware=True, order_by=[])


def test_order_aware_out_of_range_key_falls_back_without_indexerror():
    """An order-key index past the result width falls back, never raises IndexError.

    If the caller's SQL-derived column position ever exceeds the actual result
    width, the order-aware path must NOT index a missing column (an IndexError the
    gate would mislabel ``error:``); it falls back to the order-insensitive
    comparison instead.
    """
    validator = _validator()
    reference = [(1, "a"), (2, "b")]  # width 2; index 5 is out of range
    # Identical -> clean pass via the fallback, no IndexError.
    assert validator.validate_results_exact(reference, list(reference), 3, 1, order_aware=True, order_by=[5])
    # A reversed order with an out-of-range key is NOT caught (fallback is
    # order-insensitive) - but crucially it does not raise.
    assert validator.validate_results_exact(reference, list(reversed(reference)), 3, 1, order_aware=True, order_by=[5])


# --- None-safe sort: a NULL-mixed column never raises from sorted() --------------


def test_none_mixed_column_equal_passes_without_crashing():
    """A column mixing None and a value compares equal without a sorted() TypeError."""
    validator = _validator()
    rows = [(1, None), (2, 5), (3, None)]
    # A bare ``sorted`` on these rows would raise (None < int); the None-safe
    # surrogate makes it a clean pass.
    assert validator.validate_results_exact(rows, list(rows), 3, 1)


def test_none_mixed_column_difference_is_a_clean_mismatch_not_an_error():
    """A genuine None-vs-value difference is a MISMATCH, never an execution error."""
    validator = _validator()
    reference = [(1, None), (2, 5)]
    variant = [(1, 7), (2, 5)]  # None -> 7 on the first row
    with pytest.raises(ValidationError) as exc_info:
        validator.validate_results_exact(reference, variant, 3, 1)
    message = str(exc_info.value)
    assert "mismatch" in message.lower()
    assert "error:" not in message


def test_mixed_type_column_does_not_raise_typeerror():
    """A column mixing types (int and str) sorts without raising TypeError."""
    validator = _validator()
    # Equal multisets with a type-mixed column: must compare without crashing.
    rows = [(1, "x"), (2, 7)]
    assert validator.validate_results_exact(rows, list(reversed(rows)), 3, 1)
