"""Cross-platform parity tests for TPC tuned templates."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchbox.cli.config import ConfigManager
from benchbox.core.results.models import BenchmarkResults
from benchbox.core.results.schema import build_result_payload, build_tuning_payload
from benchbox.core.tuning.interface import TuningColumn, UnifiedTuningConfiguration
from benchbox.core.tuning.profile_validation import (
    build_tuning_profile_metadata,
    validate_tuning_template,
)
from benchbox.core.tuning.workload_profiles import load_tpc_tuning_profile

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[4]
TUNING_ROOT = REPO_ROOT / "examples" / "tunings"


@pytest.mark.parametrize(
    ("platform", "benchmark_id"),
    [
        ("databricks", "tpch"),
        ("databricks", "tpcds"),
        ("duckdb", "tpch"),
        ("duckdb", "tpcds"),
    ],
)
def test_tpc_tuned_templates_map_required_logical_profile_candidates(platform: str, benchmark_id: str) -> None:
    tuning_config = _load_tuning(platform, benchmark_id)
    result = validate_tuning_template(
        profile=load_tpc_tuning_profile(),
        benchmark=benchmark_id,
        platform=platform,
        tuning_config=tuning_config,
    )

    assert result.is_valid, [issue.to_dict() for issue in result.issues]
    assert result.mapped_count == result.required_count
    assert result.unsupported_count == 0
    assert result.waived_count == 0


def test_duckdb_maps_logical_profile_to_sorting_not_databricks_clustering() -> None:
    tuning_config = _load_tuning("duckdb", "tpch")
    result = validate_tuning_template(
        profile=load_tpc_tuning_profile(),
        benchmark="tpch",
        platform="duckdb",
        tuning_config=tuning_config,
    )

    supplier_key = next(mapping for mapping in result.mappings if mapping.candidate_key == "tpch.LINEITEM.L_SUPPKEY")
    assert supplier_key.mapped_tuning_types == ("sorting",)
    assert "sorting" in supplier_key.platform_mapping.physical_mechanisms
    assert "z_order" not in supplier_key.platform_mapping.physical_mechanisms


def test_dropped_low_evidence_candidates_fail_when_reintroduced() -> None:
    tuning_config = _load_tuning("duckdb", "tpcds")
    tuning_config.table_tunings["WEB_RETURNS"].sorting.append(
        TuningColumn(name="WR_WEB_PAGE_SK", type="INTEGER", order=2)
    )

    result = validate_tuning_template(
        profile=load_tpc_tuning_profile(),
        benchmark="tpcds",
        platform="duckdb",
        tuning_config=tuning_config,
    )

    assert not result.is_valid
    assert any(issue.candidate_key == "tpcds.WEB_RETURNS.WR_WEB_PAGE_SK" for issue in result.issues)


@pytest.mark.parametrize(
    ("platform", "benchmark_id", "expected_mechanism"),
    [
        ("databricks", "tpch", "z_order"),
        ("duckdb", "tpch", "sorting"),
    ],
)
def test_tuning_profile_metadata_exposes_comparison_semantics(
    platform: str,
    benchmark_id: str,
    expected_mechanism: str,
) -> None:
    metadata = build_tuning_profile_metadata(
        benchmark=benchmark_id,
        platform=platform,
        tuning_config=_load_tuning(platform, benchmark_id),
    )

    assert metadata is not None
    assert metadata["logical_tuning_profile_id"] == "tpc-v1"
    assert expected_mechanism in metadata["platform_physical_tuning_mechanisms"]
    assert (
        metadata["logical_profile_coverage"]["mapped_count"] == metadata["logical_profile_coverage"]["required_count"]
    )
    assert metadata["unmapped_logical_candidates"] == []


def test_tuning_profile_metadata_is_omitted_for_basic_constraints_fallback() -> None:
    metadata = build_tuning_profile_metadata(
        benchmark="tpch",
        platform="duckdb",
        tuning_config=UnifiedTuningConfiguration(),
    )

    assert metadata is None


def test_tuning_companion_payload_carries_logical_profile_metadata() -> None:
    metadata = build_tuning_profile_metadata(
        benchmark="tpch",
        platform="duckdb",
        tuning_config=_load_tuning("duckdb", "tpch"),
    )
    result = SimpleNamespace(
        execution_id="run-1",
        tunings_applied={"configuration": {"tuning_mode": "tuned"}},
        tuning_source_file="examples/tunings/duckdb/tpch_tuned.yaml",
        tuning_config_hash="abc123",
        tuning_validation_status="PASSED",
        execution_metadata={"tuning_profile": metadata},
    )

    payload = build_tuning_payload(result)

    assert payload is not None
    assert payload["logical_profile"]["logical_tuning_profile_id"] == "tpc-v1"
    assert payload["logical_profile"]["logical_profile_coverage"]["unmapped_count"] == 0


def test_result_payload_platform_tuning_summary_carries_logical_profile_metadata() -> None:
    metadata = build_tuning_profile_metadata(
        benchmark="tpch",
        platform="duckdb",
        tuning_config=_load_tuning("duckdb", "tpch"),
    )
    result = BenchmarkResults(
        benchmark_name="tpch",
        platform="duckdb",
        scale_factor=0.01,
        execution_id="run-1",
        timestamp=datetime(2026, 5, 26),
        duration_seconds=1.0,
        total_queries=1,
        successful_queries=1,
        failed_queries=0,
        query_results=[
            {
                "query_id": "Q1",
                "status": "SUCCESS",
                "execution_time_seconds": 0.1,
                "rows_returned": 1,
                "run_type": "measurement",
            }
        ],
        tunings_applied={"configuration": {"tuning_mode": "tuned"}},
        tuning_source_file="examples/tunings/duckdb/tpch_tuned.yaml",
        tuning_config_hash="abc123",
        tuning_validation_status="PASSED",
        execution_metadata={"tuning_profile": metadata},
    )

    payload = build_result_payload(result)

    logical_profile = payload["platform"]["tuning"]["logical_profile"]
    assert logical_profile["id"] == "tpc-v1"
    assert "sorting" in logical_profile["physical_mechanisms"]
    assert logical_profile["coverage"]["unmapped_count"] == 0


def _load_tuning(platform: str, benchmark: str):
    return ConfigManager().load_unified_tuning_config(
        TUNING_ROOT / platform / f"{benchmark}_tuned.yaml",
        platform=platform,
    )
