"""Tests for shared result status policy."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from benchbox.core.results.status import (
    bundle_failed_query_count,
    bundle_is_clean_pass,
    result_cli_failure_reason,
    result_failed_query_count,
    result_is_clean_pass,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_bundle_skipped_queries_are_not_failures() -> None:
    data = {
        "summary": {"validation": "passed", "queries": {"total": 2, "passed": 1, "failed": 0, "skipped": 1}},
        "queries": [
            {"id": "Q1", "status": "SUCCESS", "run_type": "measurement"},
            {"id": "Q2", "status": "SKIPPED", "run_type": "measurement"},
        ],
    }

    assert bundle_failed_query_count(data) == 0
    assert bundle_is_clean_pass(data) is True


def test_result_failed_query_count_trusts_explicit_zero_failed_count() -> None:
    result = SimpleNamespace(total_queries=2, successful_queries=1, failed_queries=0, validation_status="PASSED")

    assert result_failed_query_count(result) == 0


@pytest.mark.parametrize("status", ["not_run", "uncertain", "not_validated", "unknown"])
def test_bundle_unchecked_validation_statuses_are_not_clean(status: str) -> None:
    data = {
        "summary": {"validation": status, "queries": {"total": 1, "passed": 1, "failed": 0}},
        "queries": [{"id": "Q1", "status": "SUCCESS", "run_type": "measurement"}],
    }

    assert bundle_is_clean_pass(data) is False


@pytest.mark.parametrize("status", ["fallback", "failed"])
def test_bundle_non_clean_translation_statuses_are_not_clean(status: str) -> None:
    data = {
        "summary": {"validation": "passed", "queries": {"total": 1, "passed": 1, "failed": 0}},
        "execution": {"translation": {"status": status}},
        "queries": [{"id": "Q1", "status": "SUCCESS", "run_type": "measurement"}],
    }

    assert bundle_is_clean_pass(data) is False


@pytest.mark.parametrize("status", ["NOT_RUN", "UNCERTAIN", "NOT_VALIDATED", "UNKNOWN"])
def test_result_unchecked_validation_statuses_are_not_clean(status: str) -> None:
    result = SimpleNamespace(total_queries=1, successful_queries=1, failed_queries=0, validation_status=status)

    assert result_is_clean_pass(result) is False


@pytest.mark.parametrize("status", ["fallback", "failed"])
def test_result_non_clean_translation_statuses_are_not_clean(status: str) -> None:
    result = SimpleNamespace(
        total_queries=1,
        successful_queries=1,
        failed_queries=0,
        validation_status="PASSED",
        execution_metadata={"translation": {"status": status}},
    )

    assert result_is_clean_pass(result) is False


@pytest.mark.parametrize("status", ["not_run", "NOT_RUN", "not_validated", "uncertain", "unknown"])
def test_unexecuted_validation_is_not_a_cli_failure(status: str) -> None:
    """Validation that never ran keeps the result non-clean for publication
    but must not fail the CLI invocation (v0.3.0 exit semantics)."""
    result = SimpleNamespace(total_queries=1, successful_queries=1, failed_queries=0, validation_status=status)
    assert not result_is_clean_pass(result)
    assert result_cli_failure_reason(result) is None


@pytest.mark.parametrize("status", ["failed", "interrupted", "partial", "error"])
def test_executed_validation_failures_are_cli_failures(status: str) -> None:
    result = SimpleNamespace(total_queries=1, successful_queries=1, failed_queries=0, validation_status=status)
    assert result_cli_failure_reason(result) == f"validation_status={status}"


def test_failed_queries_are_cli_failures_regardless_of_validation() -> None:
    result = SimpleNamespace(total_queries=2, successful_queries=1, failed_queries=1, validation_status="not_run")
    assert result_cli_failure_reason(result) == "1 failed query"


def test_translation_fallback_is_a_cli_failure() -> None:
    result = SimpleNamespace(
        total_queries=1,
        successful_queries=1,
        failed_queries=0,
        validation_status="passed",
        execution_metadata={"translation": {"status": "fallback"}},
    )
    assert result_cli_failure_reason(result) == "translation_status=fallback"
