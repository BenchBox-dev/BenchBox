"""Tests for result exporter serialization helpers."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

import benchbox.core.results.exporter as exporter_module
from benchbox.core.results.canonical_json import canonical_json_bytes
from benchbox.core.results.exporter import ResultExporter
from benchbox.core.results.models import (
    BenchmarkResults,
    DataGenerationPhase,
    ExecutionPhases,
    SchemaCreationPhase,
    SetupPhase,
    StatisticsGatheringPhase,
    TableCreationStats,
)
from benchbox.validation.bundle import ValidationResult, _validate_bundle

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _minimal_result(platform: str) -> BenchmarkResults:
    return BenchmarkResults(
        benchmark_name="TPCH",
        platform=platform,
        scale_factor=0.01,
        execution_id=f"cost-{platform}",
        timestamp=datetime(2026, 5, 3),
        duration_seconds=1.0,
        total_queries=1,
        successful_queries=1,
        failed_queries=0,
        query_results=[{"query_id": "Q1", "execution_time_ms": 1, "rows_returned": 1, "status": "SUCCESS"}],
    )


def _export_payload(tmp_path, result: BenchmarkResults) -> dict:
    exported = ResultExporter(output_dir=tmp_path, anonymize=False).export_result(result, formats=["json"])
    with open(exported["json"], encoding="utf-8") as handle:
        return json.load(handle)


def _assert_submission_valid(payload: dict) -> None:
    vr = ValidationResult("export")
    _validate_bundle(payload, vr)
    assert vr.ok, vr.errors


def _eof_fixed(data: bytes) -> bytes:
    return data.rstrip(b"\n") + b"\n"


def _assert_canonical_json_file(path: Path) -> None:
    raw = path.read_bytes()
    assert raw.endswith(b"\n")
    assert not raw.endswith(b"\n\n")
    assert raw == _eof_fixed(raw)
    assert raw == canonical_json_bytes(json.loads(raw))


def test_exporter_serializes_execution_phases(tmp_path):
    """JSON export should handle execution phases via v2.0 schema.

    In v2.0, execution phases are processed but not exported directly.
    Instead, relevant data (like errors, table stats) is extracted and
    placed in appropriate v2.0 sections.
    """
    exporter = ResultExporter(output_dir=tmp_path, anonymize=False)

    phases = ExecutionPhases(
        setup=SetupPhase(
            data_generation=DataGenerationPhase(
                duration_ms=10,
                status="SUCCESS",
                tables_generated=1,
                total_rows_generated=100,
                total_data_size_bytes=1024,
                per_table_stats={},
            ),
            schema_creation=SchemaCreationPhase(
                duration_ms=5,
                status="SUCCESS",
                tables_created=1,
                constraints_applied=0,
                indexes_created=0,
                per_table_creation={
                    "lineitem": TableCreationStats(
                        creation_time_ms=3,
                        status="SUCCESS",
                        constraints_applied=0,
                        indexes_created=0,
                    )
                },
            ),
        )
    )

    result = BenchmarkResults(
        benchmark_name="TPCH",
        platform="duckdb",
        scale_factor=0.01,
        execution_id="test-run",
        timestamp=datetime.now(),
        duration_seconds=0.5,
        total_queries=1,
        successful_queries=1,
        failed_queries=0,
        query_results=[{"query_id": "Q1", "execution_time_ms": 1, "rows_returned": 4, "status": "SUCCESS"}],
        execution_phases=phases,
    )

    exported = exporter.export_result(result, formats=["json"])
    json_path = exported["json"]

    with open(json_path, encoding="utf-8") as f:
        payload = json.load(f)

    # v2.0 schema has version, run, benchmark, platform, summary, queries
    assert payload["version"] == "2.1"
    assert payload["run"]["id"] == "test-run"
    assert payload["benchmark"]["id"] == "tpch"
    assert payload["platform"]["name"] == "duckdb"
    # Successful phases won't create errors
    assert "errors" not in payload


def test_exporter_serializes_statistics_phase(tmp_path):
    """The opt-in statistics phase exports under phases.statistics with stats_mode."""
    exporter = ResultExporter(output_dir=tmp_path, anonymize=False)

    phases = ExecutionPhases(
        setup=SetupPhase(
            statistics_gathering=StatisticsGatheringPhase(
                duration_ms=42,
                status="COMPLETED",
                stats_mode="explicit",
                tables_analyzed=21,
            ),
        )
    )
    result = BenchmarkResults(
        benchmark_name="TPCH",
        platform="duckdb",
        scale_factor=0.01,
        execution_id="stats-run",
        timestamp=datetime.now(),
        duration_seconds=0.5,
        total_queries=1,
        successful_queries=1,
        failed_queries=0,
        query_results=[{"query_id": "Q1", "execution_time_ms": 1, "rows_returned": 4, "status": "SUCCESS"}],
        execution_phases=phases,
    )

    with open(exporter.export_result(result, formats=["json"])["json"], encoding="utf-8") as f:
        payload = json.load(f)

    assert payload["phases"]["statistics"] == {
        "status": "COMPLETED",
        "duration_ms": 42,
        "stats_mode": "explicit",
        "tables_analyzed": 21,
    }


def test_exporter_omits_statistics_phase_when_not_run(tmp_path):
    """Legacy runs (no statistics phase) must not grow a statistics block."""
    payload = _export_payload(tmp_path, _minimal_result("duckdb"))

    assert "statistics" not in payload["phases"]


def test_canonical_bundle_export_serializes_primary_and_companions(monkeypatch, tmp_path):
    monkeypatch.setattr(
        exporter_module,
        "build_plans_payload",
        lambda _result: {"zeta": 1, "alpha": {"b": 2}},
    )
    monkeypatch.setattr(
        exporter_module,
        "build_tuning_payload",
        lambda _result: {"zeta": 2, "alpha": 1},
    )

    exported = ResultExporter(output_dir=tmp_path, anonymize=False).export_result(
        _minimal_result("duckdb"),
        formats=["json"],
    )
    primary_path = exported["json"]

    _assert_canonical_json_file(primary_path)
    _assert_canonical_json_file(tmp_path / f"{primary_path.stem}.plans.json")
    _assert_canonical_json_file(tmp_path / f"{primary_path.stem}.tuning.json")


def test_canonical_bundle_export_anonymizes_plans_raw_explain_output(monkeypatch, tmp_path):
    """qpc-07 w3: the plans companion bypassed anonymization entirely, so
    raw_explain_output (opaque per-platform EXPLAIN text that can embed
    absolute paths/hostnames/usernames) leaked verbatim even when
    anonymize=True. It must be stripped from an anonymized export.
    """
    monkeypatch.setattr(
        exporter_module,
        "build_plans_payload",
        lambda _result: {
            "version": "2.1",
            "run_id": "cost-duckdb",
            "plans_captured": 1,
            "capture_failures": 0,
            "queries": {
                "1": {
                    "fingerprint": "a" * 64,
                    "plan": {
                        "query_id": "1",
                        "platform": "duckdb",
                        "logical_root": None,
                        "raw_explain_output": "SEQ_SCAN /Users/alice/data/lineitem.parquet",
                    },
                }
            },
        },
    )

    exported = ResultExporter(output_dir=tmp_path, anonymize=True).export_result(
        _minimal_result("duckdb"),
        formats=["json"],
    )
    primary_path = exported["json"]
    plans_path = tmp_path / f"{primary_path.stem}.plans.json"

    with open(plans_path, encoding="utf-8") as handle:
        plans_data = json.load(handle)

    assert plans_data["queries"]["1"]["plan"]["raw_explain_output"] is None


def test_canonical_bundle_export_keeps_plans_raw_explain_output_when_not_anonymized(monkeypatch, tmp_path):
    """Companion behavior is unchanged for non-anonymized exports (the common
    local-dev path): raw_explain_output round-trips verbatim."""
    monkeypatch.setattr(
        exporter_module,
        "build_plans_payload",
        lambda _result: {
            "version": "2.1",
            "run_id": "cost-duckdb",
            "plans_captured": 1,
            "capture_failures": 0,
            "queries": {
                "1": {
                    "fingerprint": "a" * 64,
                    "plan": {
                        "query_id": "1",
                        "platform": "duckdb",
                        "logical_root": None,
                        "raw_explain_output": "SEQ_SCAN /Users/alice/data/lineitem.parquet",
                    },
                }
            },
        },
    )

    exported = ResultExporter(output_dir=tmp_path, anonymize=False).export_result(
        _minimal_result("duckdb"),
        formats=["json"],
    )
    primary_path = exported["json"]
    plans_path = tmp_path / f"{primary_path.stem}.plans.json"

    with open(plans_path, encoding="utf-8") as handle:
        plans_data = json.load(handle)

    assert plans_data["queries"]["1"]["plan"]["raw_explain_output"] == "SEQ_SCAN /Users/alice/data/lineitem.parquet"


def test_canonical_bundle_export_anonymizes_operator_platform_metadata(monkeypatch, tmp_path):
    """#1024 review: the same raw EXPLAIN text raw_explain_output-stripping
    guards against also gets copied verbatim into each operator node's
    structured physical_operator.platform_metadata by many parsers (e.g.
    Spark FileScan `details`, DuckDB `extra_info`). An anonymized export must
    strip it there too, at every depth of the logical_root tree, not just
    the top-level raw_explain_output.
    """
    monkeypatch.setattr(
        exporter_module,
        "build_plans_payload",
        lambda _result: {
            "version": "2.1",
            "run_id": "cost-spark",
            "plans_captured": 1,
            "capture_failures": 0,
            "queries": {
                "1": {
                    "fingerprint": "a" * 64,
                    "plan": {
                        "query_id": "1",
                        "platform": "spark",
                        "raw_explain_output": None,
                        "logical_root": {
                            "operator_id": "1",
                            "operator_type": "Join",
                            "children": [
                                {
                                    "operator_id": "2",
                                    "operator_type": "Scan",
                                    "children": [],
                                    "physical_operator": {
                                        "operator_type": "FileScan",
                                        "operator_id": "2",
                                        "properties": {},
                                        "platform_metadata": {
                                            "details": "Location: /Users/alice/data/lineitem, PartitionFilters: []"
                                        },
                                    },
                                }
                            ],
                            "physical_operator": None,
                        },
                    },
                }
            },
        },
    )

    exported = ResultExporter(output_dir=tmp_path, anonymize=True).export_result(
        _minimal_result("spark"),
        formats=["json"],
    )
    primary_path = exported["json"]
    plans_path = tmp_path / f"{primary_path.stem}.plans.json"

    with open(plans_path, encoding="utf-8") as handle:
        plans_data = json.load(handle)

    scan_node = plans_data["queries"]["1"]["plan"]["logical_root"]["children"][0]
    assert scan_node["physical_operator"]["platform_metadata"] == {}


def test_canonical_bundle_export_keeps_operator_platform_metadata_when_not_anonymized(monkeypatch, tmp_path):
    """Companion behavior is unchanged for non-anonymized exports: operator
    platform_metadata round-trips verbatim."""
    monkeypatch.setattr(
        exporter_module,
        "build_plans_payload",
        lambda _result: {
            "version": "2.1",
            "run_id": "cost-spark",
            "plans_captured": 1,
            "capture_failures": 0,
            "queries": {
                "1": {
                    "fingerprint": "a" * 64,
                    "plan": {
                        "query_id": "1",
                        "platform": "spark",
                        "raw_explain_output": None,
                        "logical_root": {
                            "operator_id": "2",
                            "operator_type": "Scan",
                            "children": [],
                            "physical_operator": {
                                "operator_type": "FileScan",
                                "operator_id": "2",
                                "properties": {},
                                "platform_metadata": {"details": "Location: /Users/alice/data/lineitem"},
                            },
                        },
                    },
                }
            },
        },
    )

    exported = ResultExporter(output_dir=tmp_path, anonymize=False).export_result(
        _minimal_result("spark"),
        formats=["json"],
    )
    primary_path = exported["json"]
    plans_path = tmp_path / f"{primary_path.stem}.plans.json"

    with open(plans_path, encoding="utf-8") as handle:
        plans_data = json.load(handle)

    root = plans_data["queries"]["1"]["plan"]["logical_root"]
    assert root["physical_operator"]["platform_metadata"] == {"details": "Location: /Users/alice/data/lineitem"}


def test_exporter_records_plan_history_when_dir_configured(tmp_path):
    """qpc-08 w2: `add_run` had zero production callers -- `_export_json_v2`
    is now the single wired call site, gated behind an opt-in
    `plan_history_dir` so default export behavior (no history recording) is
    unchanged.
    """
    history_dir = tmp_path / "history"
    result = _minimal_result("duckdb")

    ResultExporter(output_dir=tmp_path / "results", anonymize=False, plan_history_dir=history_dir).export_result(
        result, formats=["json"]
    )

    history_file = history_dir / f"{result.execution_id}.json"
    assert history_file.exists()
    with open(history_file, encoding="utf-8") as handle:
        entry = json.load(handle)
    assert entry["run_id"] == result.execution_id


def test_exporter_records_plan_history_from_env_var(tmp_path, monkeypatch):
    """The BENCHBOX_PLAN_HISTORY_DIR env var is an equivalent opt-in to the
    constructor arg, for callers that can't easily thread a new parameter
    through (e.g. existing CLI entry points)."""
    history_dir = tmp_path / "history"
    monkeypatch.setenv("BENCHBOX_PLAN_HISTORY_DIR", str(history_dir))
    result = _minimal_result("duckdb")

    ResultExporter(output_dir=tmp_path / "results", anonymize=False).export_result(result, formats=["json"])

    assert (history_dir / f"{result.execution_id}.json").exists()


def test_exporter_does_not_record_plan_history_by_default(tmp_path):
    """No plan_history_dir configured (the default) -- no history directory
    should be created at all."""
    result = _minimal_result("duckdb")

    ResultExporter(output_dir=tmp_path / "results", anonymize=False).export_result(result, formats=["json"])

    assert not (tmp_path / "history").exists()


def test_exporter_omits_direct_total_for_unavailable_normalized_cost(tmp_path):
    payload = _export_payload(tmp_path, _minimal_result("snowflake"))

    assert payload["normalized_cost"]["cost_status"] == "unavailable"
    assert payload["normalized_cost"]["normalized_cost_usd"] is None
    assert "total_usd" not in payload.get("cost", {})
    _assert_submission_valid(payload)


def test_exporter_preserves_local_zero_total_with_normalized_provenance(tmp_path):
    payload = _export_payload(tmp_path, _minimal_result("duckdb"))

    assert payload["normalized_cost"]["cost_status"] == "not_applicable_local"
    assert payload["normalized_cost"]["normalized_cost_usd"] == "0"
    assert payload["cost"]["total_usd"] == 0
    _assert_submission_valid(payload)


def test_exporter_rejects_unsupported_type(tmp_path, caplog) -> None:
    """Exporter should handle unsupported types gracefully by logging error."""

    exporter = ResultExporter(output_dir=tmp_path, anonymize=False)

    class LegacyResult:
        timestamp = datetime.now()

    # Exporter catches exceptions and logs them instead of raising
    result = exporter.export_result(LegacyResult(), formats=["json"])  # type: ignore[arg-type]

    # Should return empty dict (no files exported)
    assert result == {}

    # Error should be logged - check for any error message indicating failure
    assert any("Failed to export" in record.message or "Error" in record.levelname for record in caplog.records)
