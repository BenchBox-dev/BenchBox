"""Tests for shared result status policy."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from benchbox.core.results.status import (
    bundle_failed_query_count,
    bundle_is_clean_pass,
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


@pytest.mark.parametrize("status", ["NOT_RUN", "UNCERTAIN", "NOT_VALIDATED", "UNKNOWN"])
def test_result_unchecked_validation_statuses_are_not_clean(status: str) -> None:
    result = SimpleNamespace(total_queries=1, successful_queries=1, failed_queries=0, validation_status=status)

    assert result_is_clean_pass(result) is False
