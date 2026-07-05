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
