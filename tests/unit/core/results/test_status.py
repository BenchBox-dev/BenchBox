"""Tests for shared result status policy."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from benchbox.core.results.status import bundle_failed_query_count, bundle_is_clean_pass, result_failed_query_count

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_bundle_skipped_queries_are_not_failures() -> None:
    data = {
        "summary": {"queries": {"total": 2, "passed": 1, "failed": 0, "skipped": 1}},
        "queries": [
            {"id": "Q1", "status": "SUCCESS", "run_type": "measurement"},
            {"id": "Q2", "status": "SKIPPED", "run_type": "measurement"},
        ],
    }

    assert bundle_failed_query_count(data) == 0
    assert bundle_is_clean_pass(data) is True


def test_result_failed_query_count_trusts_explicit_zero_failed_count() -> None:
    result = SimpleNamespace(total_queries=2, successful_queries=1, failed_queries=0)

    assert result_failed_query_count(result) == 0
