"""Rows tied up to float noise must pair the same way on both sides of a comparison.

A ``ROLLUP`` produces a detail row and a subtotal row with the same total. Two engines can
sum the same values in a different order and differ in the last digit of that total. The
comparator accepts the difference, but if it sorted on the exact float the two rows could
land in opposite orders on the two sides and be paired with the wrong partner.
"""

from __future__ import annotations

import pytest

from benchbox.core.tpchavoc.validation import ResultValidator, ValidationError, calculate_checksum

pytestmark = [pytest.mark.unit, pytest.mark.medium]

TOTAL = -0.7541713805310839
ULP_NOISE = 2e-16


@pytest.mark.parametrize("noise", [ULP_NOISE, -ULP_NOISE])
def test_rows_tied_up_to_float_noise_pair_by_their_other_columns(noise):
    original = [(TOTAL, 0, "detail"), (TOTAL, 1, "subtotal")]
    variant = [(TOTAL + noise, 0, "detail"), (TOTAL, 1, "subtotal")]

    assert ResultValidator().validate_results_exact(original, variant, query_id=36, variant_id=1)


@pytest.mark.parametrize("noise", [ULP_NOISE, -ULP_NOISE])
def test_the_same_holds_for_the_multiset_comparison(noise):
    original = [(TOTAL, 0), (TOTAL, 1)]
    variant = [(TOTAL + noise, 0), (TOTAL, 1)]

    assert ResultValidator()._multisets_equal(original, variant)


def test_a_real_difference_still_mismatches():
    original = [(TOTAL, 0), (TOTAL, 1)]
    variant = [(TOTAL + 1e-6, 0), (TOTAL, 1)]

    with pytest.raises(ValidationError, match="Value mismatch"):
        ResultValidator().validate_results_exact(original, variant, query_id=36, variant_id=1)


def test_rows_with_no_float_cells_order_as_before():
    validator = ResultValidator()
    rows = [("b", 2), ("a", 3), ("a", 1)]

    assert sorted(rows, key=validator._pairing_sort_key) == sorted(rows)


def test_the_value_digest_still_sorts_on_the_exact_float():
    """Reference digests are committed, so the digest's sort must not change."""
    low, high = TOTAL, TOTAL + ULP_NOISE
    rows = [(high, 1), (low, 0)]

    assert calculate_checksum(rows) == calculate_checksum([(low, 0), (high, 1)])
