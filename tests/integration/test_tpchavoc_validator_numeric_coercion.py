"""Fast, no-DB guard for the TPC-Havoc validator's numeric coercion.

The cross-dialect equivalence oracle compares variant results to canonical
TPC-H across engines that return numbers with DIFFERENT Python types: DuckDB and
Postgres hand back ``float`` for averages, while ClickHouse returns ``Decimal``
for a ``SUM(decimal)/COUNT`` average (and ``Float64`` for native ``AVG``). The
shared comparator (``ResultValidator._numeric_values_equal``) must compare these
on a common type rather than raising ``TypeError`` on ``float - Decimal``;
otherwise the ClickHouse sample would crash on Q1 instead of reporting a clean
value match/mismatch, and any future engine returning ``Decimal`` aggregates
would regress the same way.

This guard pins that coercion WITHOUT a database so a regression is caught in the
fast lane (the live ClickHouse sweep is slow-marked and only runs in the
non-blocking clickhouse-integration CI job). It is engine-agnostic: it exercises
the reused comparator, never a per-engine fork.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from benchbox.core.tpchavoc.validation import ResultValidator, ValidationError

pytestmark = [
    pytest.mark.integration,
    pytest.mark.tpchavoc,
    pytest.mark.fast,
]


def test_numeric_equal_handles_float_vs_decimal_without_crashing():
    """A float and an equal Decimal compare equal (no TypeError on subtraction)."""
    validator = ResultValidator(tolerance=1e-10)
    assert validator._numeric_values_equal(25.0, Decimal("25.0"))
    assert validator._numeric_values_equal(Decimal("25.0"), 25.0)


def test_numeric_equal_float_vs_decimal_within_tolerance():
    """Tiny float/Decimal representation differences stay within tolerance."""
    validator = ResultValidator(tolerance=1e-6)
    assert validator._numeric_values_equal(25.537587, Decimal("25.537587"))


def test_numeric_equal_float_vs_decimal_reports_real_mismatch():
    """A genuine difference (ClickHouse Decimal truncation) still reports unequal.

    Mirrors TPC-Havoc Q1.4 on ClickHouse: canonical AVG returns the full-precision
    float 25.5375..., the variant's SUM/COUNT returns Decimal('25.53'); coercion
    must NOT mute this real divergence.
    """
    validator = ResultValidator(tolerance=1e-10)
    assert not validator._numeric_values_equal(25.537587116854997, Decimal("25.53"))


def test_aggregation_results_report_clean_mismatch_for_decimal_truncation():
    """The validator surfaces a ValidationError (not a TypeError) on float vs Decimal."""
    validator = ResultValidator(tolerance=1e-10)
    original = [("A", "F", 25.537587116854997)]
    variant = [("A", "F", Decimal("25.53"))]
    with pytest.raises(ValidationError, match="value mismatch"):
        validator.validate_aggregation_results(original, variant, query_id=1, variant_id=4, aggregation_columns=[2])


def test_numeric_equal_treats_nan_and_none_as_missing():
    """SQL NULL arrives as None (most engines) or float('nan') (ClickHouse decode).

    Two missing values must compare equal (no spurious divergence), a
    missing-vs-present pair must compare unequal, and neither path may raise.
    """
    validator = ResultValidator(tolerance=1e-10)
    nan = float("nan")
    assert validator._numeric_values_equal(nan, nan)
    assert validator._numeric_values_equal(None, None)
    assert validator._numeric_values_equal(nan, None)
    assert not validator._numeric_values_equal(nan, 0)
    assert not validator._numeric_values_equal(0, nan)
    assert not validator._numeric_values_equal(None, 5.0)
