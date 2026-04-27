"""Unit tests for the result integrity validator."""

from __future__ import annotations

import copy
import glob
import json
import os
from pathlib import Path
from typing import Any

import pytest

from benchbox.core.results.benchmark_specs import LEGACY_ALIASES, get_spec
from benchbox.core.results.integrity_validator import (
    CheckCategory,
    CheckStatus,
    IntegrityReport,
    ResultIntegrityValidator,
    validate_directory,
    validate_file,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RESULTS_DIR = Path("benchmark_runs/results")


def _make_valid_tpch_result(**overrides: Any) -> dict[str, Any]:
    """Build a minimal but complete TPC-H result dict that passes all checks."""
    queries = []
    for qid in range(1, 23):
        for iteration in range(3):
            queries.append(
                {
                    "id": str(qid),
                    "ms": 100.0 + qid * 10 + iteration,
                    "rows": 100,
                    "iter": iteration,
                    "stream": 0,
                    "run_type": "measurement" if iteration > 0 else "warmup",
                    "status": "SUCCESS",
                }
            )

    result: dict[str, Any] = {
        "version": "2.1",
        "run": {
            "id": "test-001",
            "timestamp": "2026-01-01T12:00:00",
            "total_duration_ms": 5000.0,
            "query_time_ms": 4000.0,
            "iterations": 3,
            "streams": 1,
        },
        "benchmark": {
            "id": "tpch",
            "name": "TPC-H",
            "scale_factor": 1.0,
        },
        "platform": {"name": "DuckDB"},
        "config": {"mode": "standard"},
        "summary": {
            "queries": {"total": 66, "passed": 66, "failed": 0},
            "timing": {
                "total_ms": 5000.0,
                "avg_ms": 150.0,
                "min_ms": 110.0,
                "max_ms": 330.0,
                "geometric_mean_ms": 145.0,
                "p90_ms": 280.0,
                "p95_ms": 300.0,
                "p99_ms": 320.0,
                "stdev_ms": 50.0,
            },
            "tpc_metrics": {"power_at_size": 50000.0},
        },
        "phases": {
            "data_generation": {"status": "SUCCESS"},
            "schema_creation": {"status": "SUCCESS"},
            "data_loading": {"status": "SUCCESS", "duration_ms": 1200.0},
            "power_test": {"status": "COMPLETED"},
        },
        "queries": queries,
        "tables": [
            {"name": "customer", "rows": 150000},
            {"name": "lineitem", "rows": 6001215},
            {"name": "nation", "rows": 25},
            {"name": "orders", "rows": 1500000},
            {"name": "part", "rows": 200000},
            {"name": "partsupp", "rows": 800000},
            {"name": "region", "rows": 5},
            {"name": "supplier", "rows": 10000},
        ],
        "execution": {"type": "sql"},
        "environment": {"os": "linux"},
        "export": {"format": "json"},
    }
    for key, value in overrides.items():
        result[key] = value
    return result


def _find_latest_per_benchmark() -> dict[str, Path]:
    """Return {canonical_benchmark_id: latest_file_path} for DuckDB SF1 runs."""
    files = glob.glob(str(RESULTS_DIR / "*_sf1_duckdb_*_2026*.json"))
    benchmarks: dict[str, Path] = {}
    for f in files:
        path = Path(f)
        with open(path, encoding="utf-8") as fp:
            data = json.load(fp)
        bid = data.get("benchmark", {}).get("id", "unknown")
        canonical = LEGACY_ALIASES.get(bid, bid)
        if canonical not in benchmarks or os.path.getmtime(f) > os.path.getmtime(str(benchmarks[canonical])):
            benchmarks[canonical] = path
    return benchmarks


# Cache discovery at module level for parametrization
_LATEST_BY_BENCHMARK = _find_latest_per_benchmark() if RESULTS_DIR.is_dir() else {}


def _reference_file_ids() -> list[str]:
    """Return sorted list of canonical benchmark IDs with reference files."""
    return sorted(_LATEST_BY_BENCHMARK.keys())


# ---------------------------------------------------------------------------
# TestIntegrityValidatorReferenceFiles
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not RESULTS_DIR.is_dir(),
    reason="benchmark_runs/results/ not present",
)
class TestIntegrityValidatorReferenceFiles:
    """Tests against real DuckDB SF1 reference result files."""

    @pytest.mark.parametrize("benchmark_id", _reference_file_ids())
    def test_reference_file_does_not_fail(self, benchmark_id: str) -> None:
        """Each DuckDB SF1 reference file must produce overall_status != FAIL."""
        path = _LATEST_BY_BENCHMARK[benchmark_id]
        report = validate_file(path)
        assert report.overall_status != CheckStatus.FAIL, f"{path.name} ({benchmark_id}) has FAILs: " + "; ".join(
            c.message for c in report.checks if c.status == CheckStatus.FAIL
        )

    def test_tpch_passes_sf1_row_counts(self) -> None:
        """TPC-H reference file should pass the sf1_row_counts believability check."""
        path = _LATEST_BY_BENCHMARK.get("tpch")
        if path is None:
            pytest.skip("No tpch reference file")
        report = validate_file(path)
        row_check = next((c for c in report.checks if c.name == "sf1_row_counts"), None)
        assert row_check is not None, "sf1_row_counts check not found"
        assert row_check.status == CheckStatus.PASS

    def test_transaction_primitives_passes_despite_failures(self) -> None:
        """transaction_primitives has high failure rate but should still pass."""
        path = _LATEST_BY_BENCHMARK.get("transaction_primitives")
        if path is None:
            pytest.skip("No transaction_primitives reference file")
        report = validate_file(path)
        assert report.overall_status != CheckStatus.FAIL
        rate_check = next((c for c in report.checks if c.name == "success_rate"), None)
        assert rate_check is not None
        assert rate_check.status == CheckStatus.PASS

    def test_legacy_alias_resolves_to_correct_spec(self) -> None:
        """Legacy aliases should resolve to the correct canonical spec."""
        # Directly test alias resolution rather than relying on file benchmark.id
        for alias, canonical in LEGACY_ALIASES.items():
            spec = get_spec(alias)
            assert spec is not None, f"No spec found for alias {alias}"
            assert spec.benchmark_id == canonical, (
                f"Alias {alias} resolved to {spec.benchmark_id}, expected {canonical}"
            )


# ---------------------------------------------------------------------------
# TestIntegrityValidatorSyntheticData
# ---------------------------------------------------------------------------


class TestIntegrityValidatorSyntheticData:
    """Tests with synthetic data to validate specific failure modes."""

    # --- Structural checks ---

    def test_missing_required_key(self) -> None:
        """Removing 'queries' key should produce a structural FAIL."""
        data = _make_valid_tpch_result()
        del data["queries"]
        validator = ResultIntegrityValidator()
        report = validator.validate(data)
        assert report.overall_status == CheckStatus.FAIL
        schema_check = next(c for c in report.checks if c.name == "schema_v2")
        assert schema_check.status == CheckStatus.FAIL

    def test_query_count_math_wrong(self) -> None:
        """passed + failed != total should FAIL."""
        data = _make_valid_tpch_result()
        data["summary"]["queries"] = {"total": 100, "passed": 50, "failed": 30}
        validator = ResultIntegrityValidator()
        report = validator.validate(data)
        check = next(c for c in report.checks if c.name == "query_count_math")
        assert check.status == CheckStatus.FAIL

    def test_negative_timing(self) -> None:
        """Negative avg_ms should FAIL."""
        data = _make_valid_tpch_result()
        data["summary"]["timing"]["avg_ms"] = -1.0
        validator = ResultIntegrityValidator()
        report = validator.validate(data)
        check = next(c for c in report.checks if c.name == "timing_non_negative")
        assert check.status == CheckStatus.FAIL

    def test_percentile_inversion(self) -> None:
        """p95 < p90 should FAIL."""
        data = _make_valid_tpch_result()
        data["summary"]["timing"]["p90_ms"] = 300.0
        data["summary"]["timing"]["p95_ms"] = 200.0  # Inverted!
        data["summary"]["timing"]["p99_ms"] = 320.0
        validator = ResultIntegrityValidator()
        report = validator.validate(data)
        check = next(c for c in report.checks if c.name == "percentile_ordering")
        assert check.status == CheckStatus.FAIL

    def test_invalid_phase_status(self) -> None:
        """An invalid phase status value should FAIL."""
        data = _make_valid_tpch_result()
        data["phases"]["power_test"]["status"] = "INVALID"
        validator = ResultIntegrityValidator()
        report = validator.validate(data)
        check = next(c for c in report.checks if c.name == "phase_status_values")
        assert check.status == CheckStatus.FAIL

    def test_query_entry_missing_field(self) -> None:
        """Query entry missing 'ms' field should FAIL."""
        data = _make_valid_tpch_result()
        del data["queries"][0]["ms"]
        validator = ResultIntegrityValidator()
        report = validator.validate(data)
        check = next(c for c in report.checks if c.name == "query_entry_fields")
        assert check.status == CheckStatus.FAIL

    def test_query_ms_negative(self) -> None:
        """Query with negative ms should FAIL."""
        data = _make_valid_tpch_result()
        data["queries"][0]["ms"] = -5.0
        validator = ResultIntegrityValidator()
        report = validator.validate(data)
        check = next(c for c in report.checks if c.name == "query_ms_non_negative")
        assert check.status == CheckStatus.FAIL

    # --- Completeness checks ---

    def test_missing_query_ids(self) -> None:
        """Removing 50% of TPC-H query IDs should FAIL expected_query_ids."""
        data = _make_valid_tpch_result()
        # Keep only queries with id 1-11 (remove 12-22)
        data["queries"] = [q for q in data["queries"] if int(q["id"]) <= 11]
        validator = ResultIntegrityValidator()
        report = validator.validate(data)
        check = next(c for c in report.checks if c.name == "expected_query_ids")
        assert check.status == CheckStatus.FAIL

    def test_no_measurement_queries(self) -> None:
        """All entries with iter=0 and no measurement run_type should FAIL."""
        data = _make_valid_tpch_result()
        for q in data["queries"]:
            q["iter"] = 0
            q["run_type"] = "warmup"
        validator = ResultIntegrityValidator()
        report = validator.validate(data)
        check = next(c for c in report.checks if c.name == "measurement_queries_present")
        assert check.status == CheckStatus.FAIL

    def test_missing_tables_object(self) -> None:
        """TPC-H spec requires tables - missing should WARN."""
        data = _make_valid_tpch_result()
        del data["tables"]
        validator = ResultIntegrityValidator()
        report = validator.validate(data)
        check = next(c for c in report.checks if c.name == "tables_object")
        assert check.status == CheckStatus.WARN

    def test_power_phase_failed(self) -> None:
        """Power test phase with FAILED status should WARN."""
        data = _make_valid_tpch_result()
        data["phases"]["power_test"]["status"] = "FAILED"
        validator = ResultIntegrityValidator()
        report = validator.validate(data)
        check = next(c for c in report.checks if c.name == "power_phase_completed")
        assert check.status == CheckStatus.WARN

    def test_tpc_metrics_missing(self) -> None:
        """TPC-H result without tpc_metrics should be INFO (not WARN - unofficial runs never have QphH)."""
        data = _make_valid_tpch_result()
        del data["summary"]["tpc_metrics"]
        validator = ResultIntegrityValidator()
        report = validator.validate(data)
        check = next(c for c in report.checks if c.name == "tpc_metrics")
        assert check.status == CheckStatus.INFO
        # Must not elevate overall status
        assert report.overall_status == CheckStatus.PASS

    # --- Believability checks ---

    def test_avg_exceeds_max(self) -> None:
        """avg_ms > max_ms should FAIL."""
        data = _make_valid_tpch_result()
        data["summary"]["timing"]["avg_ms"] = 500.0
        data["summary"]["timing"]["max_ms"] = 330.0
        validator = ResultIntegrityValidator()
        report = validator.validate(data)
        check = next(c for c in report.checks if c.name == "avg_between_min_max")
        assert check.status == CheckStatus.FAIL

    def test_geomean_outside_range(self) -> None:
        """geometric_mean_ms < min_ms should FAIL."""
        data = _make_valid_tpch_result()
        data["summary"]["timing"]["geometric_mean_ms"] = 50.0  # Below min_ms=110
        validator = ResultIntegrityValidator()
        report = validator.validate(data)
        check = next(c for c in report.checks if c.name == "geomean_plausible")
        assert check.status == CheckStatus.FAIL

    def test_wrong_sf1_row_counts(self) -> None:
        """Wrong lineitem row count at SF=1 should FAIL (benchmark ran against incorrect data)."""
        data = _make_valid_tpch_result()
        # Set lineitem to a wildly wrong count
        for t in data["tables"]:
            if t["name"] == "lineitem":
                t["rows"] = 1000
        validator = ResultIntegrityValidator()
        report = validator.validate(data)
        check = next(c for c in report.checks if c.name == "sf1_row_counts")
        assert check.status == CheckStatus.FAIL

    def test_sf1_missing_tables_fails(self) -> None:
        """Missing expected tables from tables metadata should FAIL."""
        data = _make_valid_tpch_result()
        # Remove lineitem from tables list
        data["tables"] = [t for t in data["tables"] if t["name"] != "lineitem"]
        validator = ResultIntegrityValidator()
        report = validator.validate(data)
        check = next(c for c in report.checks if c.name == "sf1_row_counts")
        assert check.status == CheckStatus.FAIL
        assert "missing" in check.message.lower()

    def test_timing_outlier(self) -> None:
        """Query exceeding 30 minutes should WARN."""
        data = _make_valid_tpch_result()
        data["queries"][0]["ms"] = 2_000_000  # ~33 minutes
        validator = ResultIntegrityValidator()
        report = validator.validate(data)
        check = next(c for c in report.checks if c.name == "timing_outliers")
        assert check.status == CheckStatus.WARN

    def test_load_time_zero(self) -> None:
        """Load time of 0ms should WARN."""
        data = _make_valid_tpch_result()
        data["phases"]["data_loading"]["duration_ms"] = 0
        validator = ResultIntegrityValidator()
        report = validator.validate(data)
        check = next(c for c in report.checks if c.name == "load_time_nonzero")
        assert check.status == CheckStatus.WARN

    def test_high_failure_exempt(self) -> None:
        """transaction_primitives with 95% failure should still PASS success_rate."""
        data = _make_valid_tpch_result()
        data["benchmark"]["id"] = "transaction_primitives"
        data["summary"]["queries"] = {"total": 100, "passed": 5, "failed": 95}
        validator = ResultIntegrityValidator()
        report = validator.validate(data)
        check = next(c for c in report.checks if c.name == "success_rate")
        assert check.status == CheckStatus.PASS

    def test_duplicate_execution(self) -> None:
        """Duplicate (id, iter, stream) should WARN."""
        data = _make_valid_tpch_result()
        # Add a duplicate entry
        dupe = copy.deepcopy(data["queries"][0])
        data["queries"].append(dupe)
        validator = ResultIntegrityValidator()
        report = validator.validate(data)
        check = next(c for c in report.checks if c.name == "no_duplicate_executions")
        assert check.status == CheckStatus.WARN

    # --- Report utility methods ---

    def test_passed_method(self) -> None:
        """IntegrityReport.passed() returns True when overall_status is PASS."""
        data = _make_valid_tpch_result()
        validator = ResultIntegrityValidator()
        report = validator.validate(data)
        assert report.passed()

    def test_has_warnings_method(self) -> None:
        """IntegrityReport.has_warnings() detects WARN checks."""
        data = _make_valid_tpch_result()
        del data["tables"]  # Will trigger tables_object WARN
        validator = ResultIntegrityValidator()
        report = validator.validate(data)
        assert report.has_warnings()

    # --- Convenience functions ---

    def test_validate_file(self, tmp_path: Path) -> None:
        """validate_file() loads and validates a JSON file."""
        data = _make_valid_tpch_result()
        filepath = tmp_path / "test_result.json"
        filepath.write_text(json.dumps(data))
        report = validate_file(filepath)
        assert report.passed()
        assert report.file == str(filepath)

    def test_validate_directory(self, tmp_path: Path) -> None:
        """validate_directory() processes multiple files."""
        for i in range(3):
            data = _make_valid_tpch_result()
            filepath = tmp_path / f"result_{i}.json"
            filepath.write_text(json.dumps(data))
        # Also create a .plans.json file that should be excluded
        (tmp_path / "result_0.plans.json").write_text("{}")
        reports = validate_directory(tmp_path)
        assert len(reports) == 3
        assert all(r.passed() for r in reports)

    def test_validate_directory_bad_json(self, tmp_path: Path) -> None:
        """validate_directory() handles unparseable files gracefully."""
        (tmp_path / "bad.json").write_text("not json")
        reports = validate_directory(tmp_path)
        assert len(reports) == 1
        assert reports[0].overall_status == CheckStatus.FAIL

    def test_validate_file_bad_json(self, tmp_path: Path) -> None:
        """validate_file() handles unparseable files gracefully."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json")
        report = validate_file(bad_file)
        assert report.overall_status == CheckStatus.FAIL
        assert report.checks[0].name == "file_readable"
