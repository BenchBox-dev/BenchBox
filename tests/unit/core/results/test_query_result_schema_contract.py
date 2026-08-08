"""Tests for QueryResult and compact query serialization contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from benchbox.core.results.loader import reconstruct_benchmark_results
from benchbox.core.results.models import BenchmarkResults
from benchbox.core.results.schema import build_result_payload
from benchbox.core.schemas import QueryResult

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_query_result_accepts_canonical_execution_time_seconds() -> None:
    result = QueryResult(
        query_id="Q1",
        query_name="Query 1",
        sql_text="SELECT 1",
        execution_time_seconds=1.25,
        rows_returned=1,
        status="SUCCESS",
    )

    assert isinstance(result.execution_time_seconds, float)
    assert result.execution_time_seconds == 1.25
    assert result.execution_time_ms == 1250.0


def test_query_result_derives_seconds_from_legacy_ms() -> None:
    result = QueryResult(
        query_id="Q1",
        query_name="Query 1",
        sql_text="SELECT 1",
        execution_time_ms=1500,
        rows_returned=1,
        status="SUCCESS",
    )

    assert result.execution_time_seconds == 1.5
    assert result.execution_time_ms == 1500.0


def _result_with_row_fields(row_fields: dict[str, Any]) -> BenchmarkResults:
    return BenchmarkResults(
        benchmark_name="TPC-H",
        platform="duckdb",
        scale_factor=0.01,
        execution_id="row-count-contract",
        timestamp=datetime(2026, 8, 8, 12, 0, 0),
        duration_seconds=1.0,
        total_queries=1,
        successful_queries=1,
        failed_queries=0,
        query_results=[
            {
                "query_id": "Q1",
                "status": "SUCCESS",
                "execution_time_ms": 1.0,
                **row_fields,
            }
        ],
    )


@pytest.mark.parametrize(
    ("row_fields", "expected_rows"),
    [
        pytest.param({"rows_returned": 0}, 0, id="canonical-zero"),
        pytest.param({"rows": 0}, 0, id="compact-alias-zero"),
        pytest.param({"result_count": 0}, 0, id="legacy-alias-zero"),
        pytest.param({"rows_returned": 7}, 7, id="canonical-positive"),
        pytest.param({"rows": 8}, 8, id="compact-alias-positive"),
        pytest.param({"result_count": 9}, 9, id="legacy-alias-positive"),
        pytest.param({"rows_returned": None, "rows": 10}, 10, id="canonical-null-falls-back"),
        pytest.param({"rows_returned": None, "rows": None, "result_count": 11}, 11, id="null-aliases-fall-back"),
        pytest.param({"rows_returned": 0, "rows": 12, "result_count": 13}, 0, id="canonical-zero-wins"),
        pytest.param({"rows_returned": 14, "rows": 15, "result_count": 16}, 14, id="canonical-positive-wins"),
        pytest.param({"rows_returned": None, "rows": 0, "result_count": 17}, 0, id="compact-zero-wins"),
        pytest.param({"rows_returned": None, "rows": 18, "result_count": 19}, 18, id="compact-positive-wins"),
    ],
)
def test_result_export_preserves_non_none_row_count_alias_precedence(
    row_fields: dict[str, Any], expected_rows: int
) -> None:
    payload = build_result_payload(_result_with_row_fields(row_fields))

    assert payload["queries"][0]["rows"] == expected_rows


@pytest.mark.parametrize(
    "row_fields",
    [
        pytest.param({}, id="missing"),
        pytest.param({"rows_returned": None}, id="canonical-null"),
        pytest.param(
            {"rows_returned": None, "rows": None, "result_count": None},
            id="all-aliases-null",
        ),
    ],
)
def test_result_export_omits_missing_or_null_row_count(row_fields: dict[str, Any]) -> None:
    payload = build_result_payload(_result_with_row_fields(row_fields))

    assert "rows" not in payload["queries"][0]


@pytest.mark.parametrize(
    ("row_fields", "expected_rows"),
    [
        pytest.param({"rows_returned": 0}, 0, id="canonical-zero"),
        pytest.param({"rows_returned": 20}, 20, id="canonical-positive"),
        pytest.param({"rows": 0}, 0, id="compact-alias-zero"),
        pytest.param({"rows": 21}, 21, id="compact-alias-positive"),
        pytest.param({"result_count": 0}, 0, id="legacy-alias-zero"),
        pytest.param({"result_count": 22}, 22, id="legacy-alias-positive"),
    ],
)
def test_row_count_survives_export_load_reexport_round_trip(row_fields: dict[str, Any], expected_rows: int) -> None:
    payload = build_result_payload(_result_with_row_fields(row_fields))
    reconstructed = reconstruct_benchmark_results(payload)
    round_trip = build_result_payload(reconstructed)

    assert payload["queries"][0]["rows"] == expected_rows
    assert reconstructed.query_results[0]["rows_returned"] == expected_rows
    assert round_trip["queries"][0]["rows"] == expected_rows


@pytest.mark.parametrize(
    "row_fields",
    [
        pytest.param({}, id="missing"),
        pytest.param({"rows_returned": None}, id="canonical-null"),
        pytest.param(
            {"rows_returned": None, "rows": None, "result_count": None},
            id="all-aliases-null",
        ),
    ],
)
def test_missing_or_null_row_count_stays_unset_across_round_trip(row_fields: dict[str, Any]) -> None:
    payload = build_result_payload(_result_with_row_fields(row_fields))
    reconstructed = reconstruct_benchmark_results(payload)
    round_trip = build_result_payload(reconstructed)

    assert "rows" not in payload["queries"][0]
    assert reconstructed.query_results[0]["rows_returned"] is None
    assert "rows" not in round_trip["queries"][0]
