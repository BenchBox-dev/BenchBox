"""Schema timing contract tests for canonical execution_time_seconds."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from benchbox.core.results.schema import build_result_payload

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _result_with_queries(query_results: list[dict[str, Any]], execution_id: str = "run_1") -> SimpleNamespace:
    return SimpleNamespace(
        query_results=query_results,
        total_rows_loaded=0,
        data_loading_time=0.0,
        validation_status=None,
        execution_id=execution_id,
        timestamp=datetime(2026, 2, 12),
        duration_seconds=1.5,
        query_subset=None,
        benchmark_name="TPC-H Benchmark",
        benchmark_id="tpch",
        scale_factor=0.01,
        test_execution_type="power",
        platform="duckdb",
        platform_info=None,
        system_profile=None,
        table_statistics=None,
        execution_phases=None,
        cost_summary=None,
        execution_context=None,
        execution_metadata=None,
        tuning_config=None,
        power_at_size=None,
        throughput_at_size=None,
        qph_at_size=None,
        throughput_qph=None,
        composite_qph=None,
        geometric_mean_execution_time=None,
        tunings_applied=None,
        tuning_source_file=None,
        tuning_config_hash=None,
    )


def test_build_result_payload_prefers_execution_time_seconds() -> None:
    result = _result_with_queries(
        [
            {
                "query_id": "Q1",
                "status": "SUCCESS",
                "execution_time_seconds": 1.25,
                "execution_time": 9.99,
                "execution_time_ms": None,
                "rows_returned": 10,
                "iteration": 1,
                "stream_id": 0,
                "run_type": "measurement",
            }
        ]
    )

    payload = build_result_payload(result)
    assert payload["queries"][0]["ms"] == 1250.0


def test_build_result_payload_preserves_positive_sub_ms_measurements() -> None:
    result = _result_with_queries(
        [
            {
                "query_id": "Q1",
                "status": "SUCCESS",
                "execution_time_seconds": 0.00004,
                "rows_returned": 1,
                "iteration": 1,
                "stream_id": 0,
                "run_type": "measurement",
            }
        ],
        execution_id="run_sub_ms",
    )

    payload = build_result_payload(result)

    assert payload["queries"][0]["ms"] == 0.04
    assert payload["summary"]["timing"]["min_ms"] == 0.04
    assert payload["summary"]["timing"]["max_ms"] == 0.04


def test_build_result_payload_run_type_contract_and_compat_fallback() -> None:
    result = _result_with_queries(
        [
            {
                "query_id": "Q1",
                "status": "SUCCESS",
                "execution_time_seconds": 1.25,
                "rows_returned": 10,
                "iteration": 1,
                "stream_id": 0,
                "run_type": "warmup",
            },
            {
                "query_id": "Q2",
                "status": "SUCCESS",
                "execution_time_seconds": 1.0,
                "rows_returned": 8,
                "iteration": 0,
                "stream_id": 0,
            },
        ],
        execution_id="run_2",
    )

    payload = build_result_payload(result)
    queries = {q["id"]: q for q in payload["queries"]}

    # Explicit producer tagging is preserved as-is.
    assert queries["1"]["run_type"] == "warmup"
    # Missing run_type uses compatibility fallback.
    assert queries["2"]["run_type"] == "warmup"
