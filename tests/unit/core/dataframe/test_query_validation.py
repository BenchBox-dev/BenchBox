"""Tests for DataFrame row-count validation evidence."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from benchbox.core.dataframe.query_validation import validate_dataframe_query_results

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _measurement(query_id: str = "Q1", rows: int | None = 4, status: str = "SUCCESS") -> dict[str, object]:
    result: dict[str, object] = {
        "query_id": query_id,
        "status": status,
        "run_type": "measurement",
        "stream_id": 3,
        "iteration": 2,
    }
    if rows is not None:
        result["rows_returned"] = rows
    return result


def test_tpch_reference_result_records_real_pass_evidence() -> None:
    warmup = {**_measurement(rows=999), "run_type": "warmup"}
    measurement = _measurement()

    summary = validate_dataframe_query_results(
        [warmup, measurement],
        benchmark_name="tpch",
        scale_factor=1.0,
    )

    assert summary.status == "PASSED"
    assert summary.details == {
        "provider": "tpc_expected_row_counts",
        "benchmark": "tpch",
        "checked": 1,
        "passed": 1,
        "failed": 0,
        "skipped": 0,
        "errors": 0,
    }
    assert "row_count_validation" not in warmup
    assert measurement["row_count_validation"] == {"expected": 4, "actual": 4, "status": "PASSED"}


def test_skipped_warmup_is_not_validation_evidence() -> None:
    warmup = {**_measurement(query_id="Q2", rows=None, status="SKIPPED"), "run_type": "warmup"}

    summary = validate_dataframe_query_results(
        [warmup, _measurement()],
        benchmark_name="tpch",
        scale_factor=1.0,
    )

    assert summary.status == "PASSED"
    assert summary.details["skipped"] == 0
    assert "row_count_validation" not in warmup


def test_tpch_mismatch_marks_the_query_and_run_failed() -> None:
    measurement = _measurement(rows=3)

    summary = validate_dataframe_query_results(
        [measurement],
        benchmark_name="TPC-H",
        scale_factor=1.0,
    )

    assert summary.status == "FAILED"
    assert summary.details["failed"] == 1
    assert measurement["status"] == "FAILED"
    assert measurement["row_count_validation"]["status"] == "FAILED"  # type: ignore[index]


def test_tpcds_is_uncertain_until_its_parameters_are_seed_aligned() -> None:
    measurement = _measurement(rows=1)

    summary = validate_dataframe_query_results(
        [measurement],
        benchmark_name="tpcds",
        scale_factor=1.0,
    )

    assert summary.status == "UNCERTAIN"
    assert summary.details["checked"] == 0
    assert summary.details["skipped"] == 1
    assert measurement["status"] == "SUCCESS"
    assert measurement["row_count_validation"]["status"] == "SKIPPED"  # type: ignore[index]


@pytest.mark.parametrize(
    ("benchmark_name", "scale_factor", "seed", "expected_status"),
    [
        ("ssb", 1.0, None, "NOT_RUN"),
        ("tpch", 0.01, None, "UNCERTAIN"),
        ("tpch", 1.0, 123, "UNCERTAIN"),
    ],
)
def test_unsupported_or_unaligned_oracles_never_claim_passed(
    benchmark_name: str,
    scale_factor: float,
    seed: int | None,
    expected_status: str,
) -> None:
    summary = validate_dataframe_query_results(
        [_measurement()],
        benchmark_name=benchmark_name,
        scale_factor=scale_factor,
        seed=seed,
    )

    assert summary.status == expected_status
    assert summary.details["checked"] == 0


def test_disabled_validation_is_not_run() -> None:
    measurement = _measurement()

    summary = validate_dataframe_query_results(
        [measurement],
        benchmark_name="tpch",
        scale_factor=1.0,
        validation_mode="disabled",
    )

    assert summary.status == "NOT_RUN"
    assert "row_count_validation" not in measurement


def test_unsupported_validation_mode_is_uncertain() -> None:
    measurement = _measurement()

    summary = validate_dataframe_query_results(
        [measurement],
        benchmark_name="tpch",
        scale_factor=1.0,
        validation_mode="loose",
    )

    assert summary.status == "UNCERTAIN"
    assert measurement["row_count_validation"]["status"] == "SKIPPED"  # type: ignore[index]


def test_missing_row_count_is_a_failed_success_contract() -> None:
    measurement = _measurement(rows=None)

    summary = validate_dataframe_query_results(
        [measurement],
        benchmark_name="tpch",
        scale_factor=1.0,
    )

    assert summary.status == "FAILED"
    assert summary.details["errors"] == 1
    assert measurement["status"] == "FAILED"
    assert measurement["row_count_validation"]["status"] == "ERROR"  # type: ignore[index]


def test_oracle_error_makes_the_run_uncertain_without_condemning_the_result() -> None:
    measurement = _measurement()

    with patch(
        "benchbox.core.dataframe.query_validation.QueryValidator.validate_query_result",
        side_effect=RuntimeError("oracle unavailable"),
    ):
        summary = validate_dataframe_query_results(
            [measurement],
            benchmark_name="tpch",
            scale_factor=1.0,
        )

    assert summary.status == "UNCERTAIN"
    assert summary.details["errors"] == 1
    assert measurement["status"] == "SUCCESS"
    assert measurement["row_count_validation"]["status"] == "ERROR"  # type: ignore[index]


def test_oracle_error_evidence_is_bounded() -> None:
    measurement = _measurement()

    with patch(
        "benchbox.core.dataframe.query_validation.QueryValidator.validate_query_result",
        side_effect=RuntimeError("x" * 2_000),
    ):
        validate_dataframe_query_results(
            [measurement],
            benchmark_name="tpch",
            scale_factor=1.0,
        )

    error = measurement["row_count_validation"]["error"]  # type: ignore[index]
    assert len(error) == 500
    assert error.endswith("...")


def test_oracle_initialization_error_is_uncertain() -> None:
    measurement = _measurement()

    with patch("benchbox.core.dataframe.query_validation.QueryValidator", side_effect=RuntimeError("no registry")):
        summary = validate_dataframe_query_results(
            [measurement],
            benchmark_name="tpch",
            scale_factor=1.0,
        )

    assert summary.status == "UNCERTAIN"
    assert summary.details["errors"] == 1
    assert measurement["status"] == "SUCCESS"
    assert measurement["row_count_validation"]["status"] == "ERROR"  # type: ignore[index]


def test_execution_failure_keeps_an_unvalidated_run_partial() -> None:
    failed = _measurement(rows=None, status="FAILED")

    summary = validate_dataframe_query_results(
        [failed],
        benchmark_name="ssb",
        scale_factor=1.0,
    )

    assert summary.status == "PARTIAL"


def test_selected_dataframe_skip_prevents_a_clean_pass() -> None:
    skipped = {
        "query_id": "Q2",
        "status": "SKIPPED",
        "run_type": "metadata",
    }

    summary = validate_dataframe_query_results(
        [_measurement(), skipped],
        benchmark_name="tpch",
        scale_factor=1.0,
    )

    assert summary.status == "UNCERTAIN"
    assert summary.details["checked"] == 1
    assert summary.details["skipped"] == 1
