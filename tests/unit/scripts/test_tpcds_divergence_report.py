"""Tests for the cause labels in scripts/tpcds_divergence_report.py (canned detail text, no data)."""

from __future__ import annotations

import pytest
from tpcds_divergence_report import (
    DECIMAL_FLOAT,
    ERROR,
    FLAKY,
    NULL_ORDER,
    PARAMETER_DRIFT,
    ROW_COUNT_LOGIC,
    UNBOUND,
    UNCLASSIFIED,
    Cell,
    classify_cell,
    label_detail,
    render_markdown,
)

pytestmark = [pytest.mark.unit, pytest.mark.medium, pytest.mark.tpcds]

ORDER_KEY_NULL = (
    "Q71.0: ORDER BY key mismatch at position 0. Original key: (None, 7008009), "
    "Variant key: (3023.76, 7008009) (order-key columns [4, 0]) - the returned order differs"
)
ORDER_KEY_NOISE = (
    "Q36.0: ORDER BY key mismatch at position 4. Original key: (-0.7541713805310839, 0), "
    "Variant key: (-0.7541713805310837, 0) (order-key columns [2, 1]) - the returned order differs"
)
ORDER_KEY_OTHER = (
    "Q4.0: ORDER BY key mismatch at position 0. Original key: ('a', 1), "
    "Variant key: ('b', 1) (order-key columns [0, 1]) - the returned order differs"
)


@pytest.mark.parametrize(
    ("detail", "cause"),
    [
        ("Q39.0: Column count mismatch at row 0. Original: 10, Variant: 8", ROW_COUNT_LOGIC),
        ("Q10.0: Row count mismatch. Original: 2, Variant: 6", ROW_COUNT_LOGIC),
        (ORDER_KEY_NULL, NULL_ORDER),
        (ORDER_KEY_NOISE, DECIMAL_FLOAT),
        (ORDER_KEY_OTHER, UNCLASSIFIED),
        ("Q5.0: Value mismatch at row 0, column 3. Original: None, Variant: 0.0, Tolerance: 1e-10", NULL_ORDER),
        ("Q66.0: Value mismatch at row 0, column 8. Original: 8288141.53, Variant: 238632.13", ROW_COUNT_LOGIC),
        ("Q9.0: Value mismatch at row 0, column 1. Original: 100.0000000001, Variant: 100.0000000002", DECIMAL_FLOAT),
        ("Q44.0: Value mismatch at row 0, column 1. Original: n 1, Variant: n 2", UNCLASSIFIED),
        ("something else entirely", UNCLASSIFIED),
    ],
)
def test_detail_text_gets_the_cause_it_shows(detail, cause):
    assert label_detail(detail)[0] == cause


def test_a_null_in_the_first_differing_key_cell_is_found_even_after_equal_cells():
    detail = (
        "Q1.0: ORDER BY key mismatch at position 2. Original key: ('x', 5, 'a, b'), "
        "Variant key: ('x', 5, None) (order-key columns [0, 1, 2]) - the returned order differs"
    )

    assert label_detail(detail)[0] == NULL_ORDER


def test_a_query_without_an_adapter_is_unbound_unless_the_text_shows_null_placement():
    assert classify_cell("Q10.0: Row count mismatch. Original: 2, Variant: 6", adapted=False)["cause"] == UNBOUND
    record = classify_cell("Q10.0: Row count mismatch. Original: 2, Variant: 6", adapted=False)
    assert record["secondary"] == ROW_COUNT_LOGIC
    assert classify_cell(ORDER_KEY_NULL, adapted=False)["cause"] == NULL_ORDER


def test_a_query_with_an_adapter_keeps_the_label_the_text_shows():
    assert classify_cell("Q39.0: Column count mismatch at row 0. Original: 10, Variant: 8", adapted=True)["cause"] == (
        ROW_COUNT_LOGIC
    )


def test_a_cell_the_adapter_fixed_is_parameter_drift():
    assert classify_cell("", adapted=True, drift_fixed=True)["cause"] == PARAMETER_DRIFT


def test_runs_that_disagree_make_a_cell_flaky_whatever_the_text_says():
    record = classify_cell(ORDER_KEY_NOISE, adapted=True, outcomes=["", ORDER_KEY_NOISE, ""])

    assert record["cause"] == FLAKY
    assert classify_cell(ORDER_KEY_NOISE, adapted=True, outcomes=[ORDER_KEY_NOISE] * 3)["cause"] == DECIMAL_FLOAT


def test_an_error_is_reported_as_an_error():
    assert classify_cell("", adapted=True, error="ValueError: boom")["cause"] == ERROR


def test_the_report_lists_each_cell_with_its_full_evidence():
    cell = Cell(
        scale=0.1,
        backend="pandas",
        query="11",
        status="divergent",
        cause=ROW_COUNT_LOGIC,
        why="88 rows against 0",
        evidence="Q11.0: Row count mismatch. Original: 88, Variant: 0 | pipe",
    )

    report = render_markdown([cell])

    assert "## Scale factor 0.1" in report
    assert "| Q11 | pandas | divergent | row count/logic | 88 rows against 0 |" in report
    assert "Original: 88, Variant: 0 \\| pipe" in report
