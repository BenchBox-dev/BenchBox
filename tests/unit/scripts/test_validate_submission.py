"""Tests for public submission bundle validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import benchbox.validation.bundle as bundle_module
from benchbox.validation.bundle import (
    SUBMISSION_NOTES_MAX_LEN,
    ValidationResult,
    _validate_bundle,
    _validate_manifest_hash,
    _validate_manifest_provenance,
    discover_bundles,
    format_pr_comment,
    format_summary,
    validate_bundles,
)
from scripts.validate_submission import main

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestManifestProvenance:
    """Provenance/funding validation + vendor-label governance (item 3)."""

    def _run(self, manifest: dict, bundle_name: str = "tpch_result.json", subdir: str = "bundles") -> ValidationResult:
        vr = ValidationResult("test")
        primary_path = Path("/repo") / "results-data" / subdir / bundle_name
        _validate_manifest_provenance(manifest, primary_path, vr)
        return vr

    def test_absent_provenance_fields_ok(self):
        assert self._run({"bundle_file": "x", "bundle_hash": "y"}).ok

    def test_valid_funding_ok(self):
        assert self._run({"funding": "free-trial"}).ok

    def test_invalid_funding_rejected(self):
        vr = self._run({"funding": "crowdfunded"})
        assert not vr.ok
        assert any("funding" in e for e in vr.errors)

    def test_notes_too_long_rejected(self):
        vr = self._run({"submission_notes": "x" * (SUBMISSION_NOTES_MAX_LEN + 1)})
        assert not vr.ok
        assert any("submission_notes" in e for e in vr.errors)

    def test_notes_non_string_rejected(self):
        vr = self._run({"submission_notes": 123})
        assert not vr.ok

    def test_notes_at_limit_ok(self):
        assert self._run({"submission_notes": "x" * SUBMISSION_NOTES_MAX_LEN}).ok

    def test_community_source_ok(self):
        assert self._run({"result_source": "community"}).ok

    def test_internal_source_ok(self):
        assert self._run({"result_source": "internal"}).ok

    def test_invalid_source_rejected(self):
        vr = self._run({"result_source": "partner"})
        assert not vr.ok
        assert any("result_source" in e for e in vr.errors)

    def test_self_asserted_vendor_outside_vendor_subtree_rejected(self):
        # The core governance check: a community bundle cannot claim vendor.
        vr = self._run({"result_source": "vendor"}, subdir="bundles")
        assert not vr.ok
        assert any("vendor" in e and "self-assert" in e for e in vr.errors)

    def test_vendor_allowed_under_vendor_subtree(self):
        vr = self._run({"result_source": "vendor"}, subdir="bundles/vendor")
        assert vr.ok


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _minimal_bundle() -> dict:
    """Return a minimal valid schema-v2 bundle dict."""
    return {
        "version": "2.1",
        "run": {
            "id": "abc123",
            "timestamp": "2026-04-01T12:00:00",
            "total_duration_ms": 5000,
        },
        "benchmark": {
            "id": "tpch",
            "name": "TPC-H",
            "scale_factor": 0.01,
        },
        "platform": {
            "name": "DuckDB",
            "version": "1.4.3",
        },
        "summary": {
            "validation": "passed",
            "queries": {"total": 22, "passed": 22, "failed": 0},
        },
        "phases": {"validation": {"status": "PASSED"}},
        "queries": [{"id": f"Q{i}", "ms": 100 + i * 10, "status": "SUCCESS"} for i in range(1, 23)],
    }


def _normalized_cost_block(cost: str | None = "1.25", status: str = "normalized") -> dict:
    """Return a minimal valid BenchBox normalized-cost provenance block."""
    # "node_hour" matches this block's Redshift-like deployment and is in the
    # NORMALIZED_COST_BILLING_UNITS vocabulary the bundle validator enforces.
    billing_unit = "node_hour" if status == "normalized" else "not_applicable"
    pricing_region = "us-east-1" if status == "normalized" else "not_applicable"
    return {
        "normalized_cost_usd": cost,
        "cost_model_version": "2026.05.0",
        "cost_model_source": "benchbox.core.cost.pricing",
        "cost_scope": "compute_only",
        "cost_status": status,
        "billing_unit": billing_unit,
        "pricing_region": pricing_region,
        "deployment": {
            "cloud_provider": "aws" if status == "normalized" else None,
            "cloud_region": "us-east-1" if status == "normalized" else None,
            "instance_type": "r7i.4xlarge" if status == "normalized" else None,
            "node_count": 2 if status == "normalized" else None,
        },
    }


@pytest.fixture
def valid_bundle_file(tmp_path: Path) -> Path:
    """Write a valid bundle to a temp file."""
    p = tmp_path / "tpch_result.json"
    p.write_text(json.dumps(_minimal_bundle()), encoding="utf-8")
    return p


@pytest.fixture
def bundle_dir(tmp_path: Path) -> Path:
    """Create a temp directory with a valid bundle."""
    d = tmp_path / "bundles"
    d.mkdir()
    (d / "tpch_result.json").write_text(json.dumps(_minimal_bundle()), encoding="utf-8")
    return d


def test_checked_in_corpus_satisfies_public_integrity_policy() -> None:
    """Policy and checked-in corpus must change together, never drift apart."""
    repo_root = Path(__file__).resolve().parents[3]
    paths = discover_bundles(repo_root / "results-data" / "bundles")
    results = validate_bundles(paths, allow_partial_validation=True)
    failures = {result.path: result.errors for result in results if not result.ok}

    assert not failures


# ---------------------------------------------------------------------------
# _validate_bundle
# ---------------------------------------------------------------------------


class TestValidateBundle:
    def test_valid_bundle_passes(self):
        vr = ValidationResult("test")
        _validate_bundle(_minimal_bundle(), vr)
        assert vr.ok
        assert len(vr.errors) == 0

    def _databricks_bundle(self) -> dict:
        data = _minimal_bundle()
        data["platform"] = {"name": "databricks"}
        return data

    def test_pre_cutoff_untuned_z_order_warns(self):
        data = self._databricks_bundle()
        data["platform"]["config"] = {"databricks_clustering_strategy": "z_order"}
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert vr.ok, vr.errors
        assert any("provenance cutoff" in warning for warning in vr.warnings)

    @pytest.mark.parametrize(
        "platform",
        [
            {
                "name": "databricks",
                "config": {"databricks_clustering_strategy": "z_order"},
                "tuning": {"tuning_source": "explicit_file"},
            },
            {"name": "databricks", "config": {"databricks_clustering_strategy": "none"}},
            {"name": "duckdb", "config": {"databricks_clustering_strategy": "z_order"}},
        ],
    )
    def test_cutoff_warn_only_for_untuned_pre_provenance_z_order(self, platform):
        data = _minimal_bundle()
        data["platform"] = platform
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert vr.ok, vr.errors
        assert not any("provenance cutoff" in warning for warning in vr.warnings)

    def test_post_cutoff_z_order_does_not_warn(self):
        data = self._databricks_bundle()
        data["platform"]["config"] = {"databricks_clustering_strategy": "z_order"}
        data["export"] = {"benchbox_version": "0.5.0"}
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert vr.ok, vr.errors
        assert not any("provenance cutoff" in warning for warning in vr.warnings)

    def test_valid_schema_2_2_row_count_validation_passes(self):
        data = _minimal_bundle()
        data["version"] = "2.2"
        data["queries"][0].update(
            {
                "rows": 4,
                "row_count_validation": {"status": "PASSED", "expected": 4, "actual": 4},
            }
        )
        vr = ValidationResult("test")

        _validate_bundle(data, vr)

        assert vr.ok, vr.errors

    def test_row_count_validation_requires_schema_2_2(self):
        data = _minimal_bundle()
        data["queries"][0].update(
            {
                "rows": 4,
                "row_count_validation": {"status": "PASSED", "expected": 4, "actual": 4},
            }
        )
        vr = ValidationResult("test")

        _validate_bundle(data, vr)

        assert not vr.ok
        assert any("row_count_validation requires schema version 2.2" in error for error in vr.errors)

    @pytest.mark.parametrize(
        "evidence",
        [
            [],
            {"status": "PASSED", "expected": 4},
            {"status": "PASSED", "expected": 4, "actual": 4, "unexpected": True},
            {"status": "UNKNOWN", "expected": 4, "actual": 4},
            {"status": "PASSED", "expected": -1, "actual": 4},
            {"status": "PASSED", "expected": 4.0, "actual": 4},
            {"status": "PASSED", "expected": 4, "actual": 3},
            {"status": "PASSED", "expected": 5, "actual": 4},
            {"status": "PASSED", "expected": 4, "actual": 4, "warning": "x" * 501},
        ],
    )
    def test_malformed_row_count_validation_is_rejected(self, evidence):
        data = _minimal_bundle()
        data["version"] = "2.2"
        data["queries"][0].update({"rows": 4, "row_count_validation": evidence})
        vr = ValidationResult("test")

        _validate_bundle(data, vr)

        assert not vr.ok
        assert any("row_count_validation" in error for error in vr.errors)

    @pytest.mark.parametrize("status", ["FAILED", "SKIPPED", "ERROR"])
    def test_non_passed_row_count_validation_rejected_when_summary_validation_passed(self, status: str):
        data = _minimal_bundle()
        data["version"] = "2.2"
        data["summary"]["validation"] = "passed"
        data["queries"][0].update(
            {
                "rows": 4,
                "row_count_validation": {"status": status, "expected": None, "actual": 4},
            }
        )
        vr = ValidationResult("test")

        _validate_bundle(data, vr)

        assert not vr.ok
        assert any("summary.validation='passed' contradicts" in error for error in vr.errors)

    def test_absent_optional_extension_blocks_pass(self):
        vr = ValidationResult("test")
        _validate_bundle(_minimal_bundle(), vr)
        assert vr.ok, vr.errors

    @pytest.mark.parametrize(
        "environment",
        [
            {
                "client_link": {
                    "collection_status": "available",
                    "source": "observed",
                    "client_region": "us-east-1",
                    "client_cloud": "aws",
                    "statement_overhead_ms": {"samples": 5, "min": 1.42, "median": 1.68},
                }
            },
            {"client_link": {"collection_status": "unavailable"}},
            {"other": 1},
        ],
    )
    def test_well_formed_client_link_passes(self, environment):
        data = _minimal_bundle()
        data["environment"] = environment
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert vr.ok, vr.errors

    @pytest.mark.parametrize(
        "environment",
        [
            "not-a-dict",
            {"client_link": "not-a-dict"},
            {"client_link": {}},
            {"client_link": {"collection_status": 42}},
            {"client_link": {"collection_status": "available", "client_region": 42}},
            {
                "client_link": {
                    "collection_status": "available",
                    "statement_overhead_ms": {"samples": "five"},
                }
            },
            {
                "client_link": {
                    "collection_status": "available",
                    "statement_overhead_ms": {"samples": -1, "min": -0.5},
                }
            },
        ],
    )
    def test_malformed_client_link_is_rejected(self, environment):
        data = _minimal_bundle()
        data["environment"] = environment
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert not vr.ok

    def test_unknown_collection_status_warns_only(self):
        data = _minimal_bundle()
        data["environment"] = {"client_link": {"collection_status": "future-status"}}
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert vr.ok, vr.errors
        assert any("collection_status" in warning for warning in vr.warnings)

    @pytest.mark.parametrize(
        "tables",
        [
            {"orders": {"rows": 10, "load_ms": 12.5}},
            {"orders": {"rows": 10, "load_ms": 0}},
            {"orders": {"rows": 10}},
        ],
    )
    def test_well_formed_tables_block_passes(self, tables):
        data = _minimal_bundle()
        data["tables"] = tables
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert vr.ok, vr.errors

    @pytest.mark.parametrize(
        "tables",
        [
            "not-a-dict",
            {"orders": "not-a-dict"},
            {"orders": {"rows": "many"}},
            {"orders": {"rows": -1}},
            {"orders": {"load_ms": "fast"}},
            {"orders": {"load_ms": True}},
            {"orders": {"load_ms": -1}},
        ],
    )
    def test_malformed_tables_block_is_rejected(self, tables):
        data = _minimal_bundle()
        data["tables"] = tables
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert not vr.ok

    def test_unknown_clustering_strategy_warns_only(self):
        data = _minimal_bundle()
        data["platform"]["config"] = {"databricks_clustering_strategy": "future-strategy"}
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert vr.ok, vr.errors
        assert any("databricks_clustering_strategy" in warning for warning in vr.warnings)

    @pytest.mark.parametrize(
        "config",
        [
            "not-a-dict",
            {"databricks_clustering_strategy": 42},
        ],
    )
    def test_malformed_platform_config_clustering_is_rejected(self, config):
        data = _minimal_bundle()
        data["platform"]["config"] = config
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert not vr.ok

    def test_public_private_path_is_rejected_by_cli_boundary(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        bundle_path = tmp_path / "tpch_result.json"
        payload = _minimal_bundle()
        payload["platform"]["working_dir"] = "/Users/alice/private-run"
        bundle_path.write_text(json.dumps(payload), encoding="utf-8")

        assert main([str(bundle_path)]) == 1
        output = capsys.readouterr().out
        assert "FAIL" in output
        assert "Users/alice" not in output
        assert "working_dir" in output

    def test_missing_top_level_keys(self):
        data = {"version": "2.1"}  # Missing everything else
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert not vr.ok
        assert any("Missing required top-level keys" in e for e in vr.errors)

    def test_result_schema_version_accepted_without_legacy_version(self):
        data = _minimal_bundle()
        del data["version"]
        data["result_schema_version"] = "2.2"
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert vr.ok

    def test_missing_result_schema_version_and_legacy_version_rejected(self):
        data = _minimal_bundle()
        del data["version"]
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert not vr.ok
        assert any("Missing required top-level keys" in e and "result_schema_version" in e for e in vr.errors)

    def test_both_result_schema_version_and_legacy_version_accepted(self):
        data = _minimal_bundle()
        data["result_schema_version"] = "2.2"
        data["version"] = "2.2"
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert vr.ok

    def test_bad_version(self):
        data = _minimal_bundle()
        data["version"] = "1.0"
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert not vr.ok
        assert any("Unsupported schema version" in e for e in vr.errors)

    def test_missing_run_keys(self):
        data = _minimal_bundle()
        data["run"] = {"id": "x"}  # Missing timestamp and total_duration_ms
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert not vr.ok
        assert any("Missing keys in 'run'" in e for e in vr.errors)

    def test_negative_total_duration(self):
        data = _minimal_bundle()
        data["run"]["total_duration_ms"] = -100
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert not vr.ok
        assert any("Negative total_duration_ms" in e for e in vr.errors)

    def test_missing_benchmark_keys(self):
        data = _minimal_bundle()
        data["benchmark"] = {"name": "TPC-H"}  # Missing id and scale_factor
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert not vr.ok
        assert any("Missing keys in 'benchmark'" in e for e in vr.errors)

    def test_negative_scale_factor(self):
        data = _minimal_bundle()
        data["benchmark"]["scale_factor"] = -1
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert not vr.ok
        assert any("scale_factor must be positive" in e for e in vr.errors)

    def test_missing_platform_name(self):
        data = _minimal_bundle()
        data["platform"] = {"version": "1.0"}  # Missing name
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert not vr.ok
        assert any("Missing keys in 'platform'" in e for e in vr.errors)

    def test_unknown_benchmark_warns(self):
        data = _minimal_bundle()
        data["benchmark"]["id"] = "my-custom-bench"
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert vr.ok  # warning, not error
        assert any("Unknown benchmark id" in w for w in vr.warnings)

    @pytest.mark.parametrize("benchmark_id", ["flightdata", "tsbs_devops", "tpcdi"])
    def test_current_benchmark_ids_do_not_warn(self, benchmark_id: str):
        data = _minimal_bundle()
        data["benchmark"]["id"] = benchmark_id
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert vr.ok
        assert not any("Unknown benchmark id" in w for w in vr.warnings)

    def test_unknown_platform_warns(self):
        data = _minimal_bundle()
        data["platform"]["name"] = "MyNewDB"
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert vr.ok
        assert any("Unknown platform name" in w for w in vr.warnings)

    @pytest.mark.parametrize("platform_name", ["pg_duckdb", "pg_mooncake"])
    def test_current_pg_extension_platform_names_do_not_warn(self, platform_name: str):
        data = _minimal_bundle()
        data["platform"]["name"] = platform_name
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert vr.ok
        assert not any("Unknown platform name" in w for w in vr.warnings)

    def test_missing_public_validation_status_fails(self):
        data = _minimal_bundle()
        del data["summary"]["validation"]
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert not vr.ok
        assert any("summary.validation is required" in e for e in vr.errors)

    @pytest.mark.parametrize("status", ["not_run", "uncertain", "unknown", "partial"])
    def test_non_clean_public_validation_status_fails(self, status: str):
        data = _minimal_bundle()
        data["summary"]["validation"] = status
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert not vr.ok
        assert any("summary.validation must be 'passed'" in e for e in vr.errors)

    def test_partial_validation_allowed_only_when_flagged(self):
        """Trusted mirror path may accept seed partials; community path may not."""
        data = _minimal_bundle()
        data["summary"]["validation"] = "partial"
        community = ValidationResult("community")
        _validate_bundle(data, community)
        assert not community.ok
        mirror = ValidationResult("mirror")
        _validate_bundle(data, mirror, allow_partial_validation=True)
        assert mirror.ok, mirror.errors
        failed = ValidationResult("failed")
        data_failed = _minimal_bundle()
        data_failed["summary"]["validation"] = "failed"
        _validate_bundle(data_failed, failed, allow_partial_validation=True)
        assert not failed.ok

    def test_not_run_validation_allowed_only_for_trusted_mirror(self):
        data = _minimal_bundle()
        data["summary"]["validation"] = "not_run"
        community = ValidationResult("community")
        _validate_bundle(data, community)
        assert not community.ok
        mirror = ValidationResult("mirror")
        _validate_bundle(data, mirror, allow_partial_validation=True)
        assert mirror.ok, mirror.errors

    def test_passed_validation_rejects_summary_failed_measurements(self):
        data = _minimal_bundle()
        data["summary"]["queries"] = {"total": 2, "passed": 1, "failed": 1}
        vr = ValidationResult("test")

        _validate_bundle(data, vr)

        assert not vr.ok
        assert any("contradicts 1 failed measurement query" in error for error in vr.errors)

    def test_passed_validation_rejects_failed_measurement_row(self):
        data = _minimal_bundle()
        data["queries"][0]["status"] = "FAILED"
        vr = ValidationResult("test")

        _validate_bundle(data, vr)

        assert not vr.ok
        assert any("contradicts 1 failed measurement query" in error for error in vr.errors)

    def test_validation_claim_rejects_unrun_validation_phase(self):
        data = _minimal_bundle()
        data["phases"] = {"validation": {"status": "NOT_RUN"}}
        vr = ValidationResult("test")

        _validate_bundle(data, vr)

        assert not vr.ok
        assert any(
            "summary.validation='passed' contradicts phases.validation.status='not_run'" in error for error in vr.errors
        )

    def test_validation_claim_allows_absent_optional_phases(self):
        data = _minimal_bundle()
        del data["phases"]
        vr = ValidationResult("test")

        _validate_bundle(data, vr)

        assert vr.ok, vr.errors

    @pytest.mark.parametrize(
        "phases",
        [None, {}, {"validation": {}}, {"validation": "NOT_RUN"}, {"validation": {"status": []}}],
        ids=["non_dict", "missing_validation", "missing_status", "non_dict_validation", "non_string_status"],
    )
    def test_validation_claim_rejects_malformed_or_incomplete_phases(self, phases):
        data = _minimal_bundle()
        data["phases"] = phases
        vr = ValidationResult("test")

        _validate_bundle(data, vr)

        assert not vr.ok
        assert any(
            "summary.validation='passed' contradicts phases.validation.status='unknown'" in error for error in vr.errors
        )

    @pytest.mark.parametrize(
        "phase_status",
        ["FAILED", "PARTIAL", "COMPLETED"],
        ids=["failed", "incompatible_partial", "unrecognized"],
    )
    def test_passed_validation_claim_rejects_non_clean_phase_status(self, phase_status: str):
        data = _minimal_bundle()
        data["phases"]["validation"]["status"] = phase_status
        vr = ValidationResult("test")

        _validate_bundle(data, vr)

        assert not vr.ok
        assert any(
            f"summary.validation='passed' contradicts phases.validation.status={phase_status.lower()!r}" in error
            for error in vr.errors
        )

    @pytest.mark.parametrize("phase_status", ["PASSED", "PARTIAL"])
    def test_partial_claim_accepts_compatible_validation_phase_on_trusted_mirror(self, phase_status: str):
        data = _minimal_bundle()
        data["summary"]["validation"] = "partial"
        data["phases"]["validation"]["status"] = phase_status
        vr = ValidationResult("mirror")

        _validate_bundle(data, vr, allow_partial_validation=True)

        assert vr.ok, vr.errors

    def test_partial_claim_rejects_non_dict_validation_phase_on_trusted_mirror(self):
        data = _minimal_bundle()
        data["summary"]["validation"] = "partial"
        data["phases"]["validation"] = "NOT_RUN"
        vr = ValidationResult("mirror")

        _validate_bundle(data, vr, allow_partial_validation=True)

        assert not vr.ok
        assert any(
            "summary.validation='partial' contradicts phases.validation.status='unknown'" in error
            for error in vr.errors
        )

    def test_partial_claim_rejects_unrun_validation_phase_on_trusted_mirror(self):
        data = _minimal_bundle()
        data["summary"]["validation"] = "partial"
        data["phases"] = {"validation": {"status": "not_run"}}
        vr = ValidationResult("mirror")

        _validate_bundle(data, vr, allow_partial_validation=True)

        assert not vr.ok
        assert any(
            "summary.validation='partial' contradicts phases.validation.status='not_run'" in error
            for error in vr.errors
        )

    def test_failed_warmup_does_not_contradict_successful_measurements(self):
        data = _minimal_bundle()
        data["summary"]["queries"] = {"total": 23, "passed": 23, "failed": 0}
        data["queries"] = [
            {"id": "Q1", "ms": 0, "status": "FAILED", "run_type": "warmup"},
        ] + [{"id": f"Q{i}", "ms": 100, "status": "SUCCESS", "run_type": "measurement"} for i in range(1, 23)]
        vr = ValidationResult("test")

        _validate_bundle(data, vr)

        assert vr.ok, vr.errors

    def test_warmup_only_bundle_is_not_a_public_measurement(self):
        data = _minimal_bundle()
        data["summary"]["queries"] = {"total": 1, "passed": 1, "failed": 0}
        data["queries"] = [{"id": "Q1", "ms": 100, "status": "SUCCESS", "run_type": "warmup"}]
        vr = ValidationResult("test")

        _validate_bundle(data, vr)

        assert not vr.ok
        assert any("at least one positive measurement timing" in error for error in vr.errors)

    def test_trusted_partial_allows_failed_measurements(self):
        data = _minimal_bundle()
        data["summary"]["validation"] = "partial"
        data["summary"]["queries"] = {"total": 2, "passed": 1, "failed": 1}
        data["queries"][0]["status"] = "FAILED"
        vr = ValidationResult("test")

        _validate_bundle(data, vr, allow_partial_validation=True)

        assert vr.ok, vr.errors

    def test_translation_fallback_fails_public_submission(self):
        data = _minimal_bundle()
        data["execution"] = {"translation": {"status": "fallback", "strict_mode": False}}
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert not vr.ok
        assert any("execution.translation.status='fallback'" in e for e in vr.errors)

    def test_all_zero_timings_fails(self):
        data = _minimal_bundle()
        data["queries"] = [
            {"id": "Q1", "ms": 0, "status": "SUCCESS"},
            {"id": "Q2", "ms": 0, "status": "SUCCESS"},
        ]
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert not vr.ok
        assert any("All query timings are 0ms" in e for e in vr.errors)

    def test_all_zero_failed_and_skipped_timings_fail(self):
        data = _minimal_bundle()
        data["summary"]["queries"] = {"total": 3, "passed": 0, "failed": 3}
        data["queries"] = [
            {"id": "Q1", "ms": 0, "status": "FAILED"},
            {"id": "Q2", "ms": 0, "status": "SKIPPED"},
            {"id": "Q3", "ms": 0, "status": "SUCCESS"},
        ]
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert not vr.ok
        assert any("All query timings are 0ms" in e for e in vr.errors)

    def test_positive_sub_millisecond_timing_passes(self):
        data = _minimal_bundle()
        data["queries"] = [{"id": f"Q{i}", "ms": 0.04, "status": "SUCCESS"} for i in range(1, 23)]
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert vr.ok

    def test_negative_query_duration_fails(self):
        data = _minimal_bundle()
        data["queries"][0]["ms"] = -50
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert not vr.ok
        assert any("negative duration" in e for e in vr.errors)

    def test_missing_query_keys_fails(self):
        data = _minimal_bundle()
        data["queries"] = [{"id": "Q1"}]  # Missing ms
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert not vr.ok
        assert any("missing keys" in e for e in vr.errors)

    def test_empty_queries_fail(self):
        data = _minimal_bundle()
        data["summary"]["queries"] = {"total": 0, "passed": 0, "failed": 0}
        data["queries"] = []
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert not vr.ok
        assert any("queries array must not be empty" in error for error in vr.errors)
        assert any("summary.queries.total must be greater than 0" in error for error in vr.errors)

    def test_user_supplied_cost_total_without_normalized_provenance_fails(self):
        data = _minimal_bundle()
        data["cost"] = {"total_usd": 1.25, "model": "manual"}

        vr = ValidationResult("test")
        _validate_bundle(data, vr)

        assert not vr.ok
        assert any("cost.total_usd" in e and "normalized_cost provenance" in e for e in vr.errors)

    def test_cost_total_with_matching_normalized_provenance_passes(self):
        data = _minimal_bundle()
        data["normalized_cost"] = _normalized_cost_block(cost="1.25")
        data["cost"] = {"total_usd": 1.25, "model": "estimated"}

        vr = ValidationResult("test")
        _validate_bundle(data, vr)

        assert vr.ok

    def test_cost_total_must_match_normalized_cost(self):
        data = _minimal_bundle()
        data["normalized_cost"] = _normalized_cost_block(cost="1.25")
        data["cost"] = {"total_usd": 1.50, "model": "estimated"}

        vr = ValidationResult("test")
        _validate_bundle(data, vr)

        assert not vr.ok
        assert any("must match normalized_cost.normalized_cost_usd" in e for e in vr.errors)

    def test_cost_total_with_unavailable_normalized_cost_fails(self):
        data = _minimal_bundle()
        data["normalized_cost"] = _normalized_cost_block(cost=None, status="unavailable")
        data["cost"] = {"total_usd": 0, "model": "estimated"}

        vr = ValidationResult("test")
        _validate_bundle(data, vr)

        assert not vr.ok
        assert any("cannot accompany cost_status 'unavailable'" in e for e in vr.errors)

    def test_local_zero_cost_total_with_not_applicable_provenance_passes(self):
        data = _minimal_bundle()
        data["normalized_cost"] = _normalized_cost_block(cost="0", status="not_applicable_local")
        data["cost"] = {"total_usd": 0, "model": "estimated"}

        vr = ValidationResult("test")
        _validate_bundle(data, vr)

        assert vr.ok

    def test_non_benchbox_normalized_cost_source_fails(self):
        data = _minimal_bundle()
        data["normalized_cost"] = _normalized_cost_block(cost="1.25")
        data["normalized_cost"]["cost_model_source"] = "manual"
        data["cost"] = {"total_usd": 1.25, "model": "manual"}

        vr = ValidationResult("test")
        _validate_bundle(data, vr)

        assert not vr.ok
        assert any("cost_model_source" in e and "benchbox.core.cost.pricing" in e for e in vr.errors)

    def test_normalized_cost_total_requires_deployment_metadata(self):
        data = _minimal_bundle()
        data["normalized_cost"] = _normalized_cost_block(cost="1.25")
        del data["normalized_cost"]["deployment"]
        data["cost"] = {"total_usd": 1.25, "model": "estimated"}

        vr = ValidationResult("test")
        _validate_bundle(data, vr)

        assert not vr.ok
        assert any("requires deployment metadata" in e for e in vr.errors)

    def test_normalized_cost_accepts_tib_scanned(self):
        """BigQuery's per-tebibyte unit is in the validator vocabulary."""
        data = _minimal_bundle()
        data["normalized_cost"] = _normalized_cost_block(cost="1.25")
        data["normalized_cost"]["billing_unit"] = "tib_scanned"
        data["cost"] = {"total_usd": 1.25, "model": "estimated"}

        vr = ValidationResult("test")
        _validate_bundle(data, vr)

        assert vr.ok, vr.errors

    def test_normalized_cost_accepts_legacy_tb_scanned(self):
        """Pre-ADR BigQuery bundles recorded as tb_scanned still validate."""
        data = _minimal_bundle()
        data["normalized_cost"] = _normalized_cost_block(cost="1.25")
        data["normalized_cost"]["billing_unit"] = "tb_scanned"
        data["cost"] = {"total_usd": 1.25, "model": "estimated"}

        vr = ValidationResult("test")
        _validate_bundle(data, vr)

        assert vr.ok, vr.errors

    def test_normalized_cost_rejects_unit_outside_vocabulary(self):
        """A fictional billing_unit cannot back normalized cost."""
        data = _minimal_bundle()
        data["normalized_cost"] = _normalized_cost_block(cost="1.25")
        data["normalized_cost"]["billing_unit"] = "bogus_unit"
        data["cost"] = {"total_usd": 1.25, "model": "estimated"}

        vr = ValidationResult("test")
        _validate_bundle(data, vr)

        assert not vr.ok
        assert any("concrete billing_unit" in e for e in vr.errors)


# ---------------------------------------------------------------------------
# timing plausibility warnings (C1-C4; warnings only, never refuse)
# ---------------------------------------------------------------------------


def _timing_bundle(
    per_query_ms,
    *,
    benchmark="tpch",
    platform="Snowflake",
    scale_factor=0.1,
    geomean_ms=None,
    rows_loaded=866602,
    validation="passed",
):
    """Build a bundle with explicit per-query timings.

    ``per_query_ms`` maps query id to ms (single value or list of samples).
    Archived shapes mirror the September cloud TPC-H runs that motivated
    these gates.
    """
    queries = []
    for qid, ms in per_query_ms.items():
        for sample in ms if isinstance(ms, list) else [ms]:
            queries.append({"id": qid, "ms": sample, "status": "SUCCESS"})
    total = len(queries)
    timing = {"total_ms": sum(q["ms"] for q in queries)}
    if geomean_ms is not None:
        timing["geometric_mean_ms"] = geomean_ms
    summary = {"validation": validation, "queries": {"total": total, "passed": total, "failed": 0}}
    if timing:
        summary["timing"] = timing
    if rows_loaded is not None:
        summary["data"] = {"rows_loaded": rows_loaded}
    return {
        "version": "2.1",
        "run": {"id": "timing-test", "timestamp": "2026-09-19T00:00:00", "total_duration_ms": 60000},
        "benchmark": {"id": benchmark, "name": benchmark, "scale_factor": scale_factor},
        "platform": {"name": platform, "version": "1.0"},
        "summary": summary,
        "phases": {"validation": {"status": "PASSED" if validation == "passed" else "PARTIAL"}},
        "queries": queries,
    }


def _flat_queries(base=4500.0, spread=60.0, count=22):
    return {f"Q{i}": base + (i % 5) * spread / 4 for i in range(1, count + 1)}


def _varied_queries(count=22):
    return {f"Q{i}": 200.0 * i for i in range(1, count + 1)}


class TestTimingPlateau:
    def test_flat_heterogeneous_run_warns_but_passes(self):
        vr = ValidationResult("test")
        _validate_bundle(_timing_bundle(_flat_queries()), vr)
        assert vr.ok, vr.errors
        assert any("timing-plateau" in w for w in vr.warnings)

    def test_varied_run_is_silent(self):
        vr = ValidationResult("test")
        _validate_bundle(_timing_bundle(_varied_queries()), vr)
        assert vr.ok, vr.errors
        assert not any("timing-plateau" in w for w in vr.warnings)

    def test_uniform_benchmark_is_out_of_scope(self):
        vr = ValidationResult("test")
        _validate_bundle(_timing_bundle(_flat_queries(), benchmark="read_primitives"), vr)
        assert vr.ok, vr.errors
        assert not any("timing-plateau" in w for w in vr.warnings)

    def test_few_distinct_queries_unevaluable(self):
        vr = ValidationResult("test")
        # Mirror lane: a 2-query fixture cannot satisfy canonical coverage;
        # the plateau gate under test is orthogonal to it.
        _validate_bundle(_timing_bundle({"Q1": 4400.0, "Q2": 4450.0}), vr, allow_partial_validation=True)
        assert vr.ok, vr.errors
        assert not any("timing-plateau" in w for w in vr.warnings)

    def test_all_zero_timings_have_no_plateau_warning(self):
        data = _timing_bundle({f"Q{i}": 0.0 for i in range(1, 23)})
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert not vr.ok  # owned by the queries-section gate
        assert not any("timing-plateau" in w for w in vr.warnings)

    def test_sub_millisecond_rows_are_timer_noise_not_evidence(self):
        data = _timing_bundle({f"Q{i}": 0.5 for i in range(1, 23)})
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert not any("timing-plateau" in w for w in vr.warnings)

    def test_case_variant_benchmark_id_still_gated(self):
        data = _timing_bundle({f"Q{i}": 4510.0 + (i % 5) * 7.0 for i in range(1, 23)}, benchmark="TPCH")
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert any("timing-plateau" in w for w in vr.warnings)


class TestSmallScaleFloor:
    def test_slow_floor_on_tiny_data_warns(self):
        vr = ValidationResult("test")
        _validate_bundle(_timing_bundle(_flat_queries(base=4400.0)), vr)
        assert vr.ok, vr.errors
        assert any("small-scale-floor" in w for w in vr.warnings)

    def test_fast_floor_is_silent(self):
        vr = ValidationResult("test")
        _validate_bundle(_timing_bundle(_varied_queries(), rows_loaded=866602), vr)
        assert vr.ok, vr.errors
        assert not any("small-scale-floor" in w for w in vr.warnings)

    def test_large_scale_is_out_of_scope(self):
        vr = ValidationResult("test")
        _validate_bundle(_timing_bundle(_flat_queries(base=4400.0), scale_factor=1.0), vr)
        assert vr.ok, vr.errors
        assert not any("small-scale-floor" in w for w in vr.warnings)

    def test_large_row_counts_excuse_a_slow_floor(self):
        vr = ValidationResult("test")
        _validate_bundle(_timing_bundle(_flat_queries(base=4400.0), rows_loaded=60_000_000), vr)
        assert vr.ok, vr.errors
        assert not any("small-scale-floor" in w for w in vr.warnings)

    def test_missing_rows_never_silently_passes(self):
        vr = ValidationResult("test")
        _validate_bundle(_timing_bundle(_flat_queries(base=4400.0), rows_loaded=None), vr)
        assert vr.ok, vr.errors
        assert any("small-scale-floor" in w and "unreported" in w for w in vr.warnings)

    def test_nonfinite_rows_loaded_is_unreported_not_fatal(self):
        # A JSON number like 1e309 parses to inf; int() would raise
        # OverflowError. The validator must treat it as unreported.
        for bad_rows in (float("inf"), float("-inf"), float("nan")):
            vr = ValidationResult("test")
            _validate_bundle(_timing_bundle(_flat_queries(base=4400.0), rows_loaded=bad_rows), vr)
            assert vr.ok, vr.errors
            assert any("small-scale-floor" in w and "unreported" in w for w in vr.warnings)

    def test_json_overflow_rows_loaded_does_not_abort_multibundle(self, tmp_path):
        good = _write_timing_bundle(tmp_path, "good.json", _varied_queries(), platform="Snowflake")
        bad_bundle = _timing_bundle(_flat_queries(base=4400.0), platform="Snowflake", rows_loaded=866602)
        text = json.dumps(bad_bundle).replace('"rows_loaded": 866602', '"rows_loaded": 1e309')
        assert "1e309" in text
        bad = tmp_path / "bad.json"
        bad.write_text(text, encoding="utf-8")
        results = validate_bundles([bad, good])
        assert len(results) == 2
        assert all(vr.ok for vr in results)


def _write_timing_bundle(tmp_path, name, per_query_ms, **kwargs):
    path = tmp_path / name
    path.write_text(json.dumps(_timing_bundle(per_query_ms, **kwargs)), encoding="utf-8")
    return path


class TestScaleInvariance:
    def test_flat_scales_warn_on_both_bundles(self, tmp_path):
        lo = _write_timing_bundle(
            tmp_path,
            "lo.json",
            _flat_queries(base=4500.0),
            scale_factor=0.1,
            geomean_ms=4531.0,
            platform="Snowflake",
        )
        hi = _write_timing_bundle(
            tmp_path,
            "hi.json",
            _flat_queries(base=4900.0),
            scale_factor=10.0,
            geomean_ms=4967.0,
            platform="Snowflake",
            rows_loaded=86_586_082,
        )
        results = validate_bundles([lo, hi])
        assert all(vr.ok for vr in results)
        assert all(any("scale-invariant" in w for w in vr.warnings) for vr in results)

    def test_warning_reports_actual_scale_span(self, tmp_path):
        lo = _write_timing_bundle(
            tmp_path,
            "lo.json",
            _flat_queries(base=4500.0),
            scale_factor=0.1,
            geomean_ms=4531.0,
            platform="Snowflake",
        )
        hi = _write_timing_bundle(
            tmp_path,
            "hi.json",
            _flat_queries(base=4900.0),
            scale_factor=10.0,
            geomean_ms=4967.0,
            platform="Snowflake",
            rows_loaded=86_586_082,
        )
        results = validate_bundles([lo, hi])
        warned = [w for vr in results for w in vr.warnings if "scale-invariant" in w]
        assert warned
        # The 0.1 -> 10 span is 100x, not the 0.1x lower endpoint.
        assert all("grows 100x in scale" in w for w in warned)

    def test_single_scale_is_silent(self, tmp_path):
        (ofar,) = validate_bundles([_write_timing_bundle(tmp_path, "only.json", _flat_queries(), platform="Snowflake")])
        assert ofar.ok, ofar.errors
        assert not any("scale-invariant" in w for w in ofar.warnings)

    def test_growing_timings_are_silent(self, tmp_path):
        lo = _write_timing_bundle(
            tmp_path,
            "lo.json",
            _flat_queries(base=400.0),
            scale_factor=0.1,
            geomean_ms=400.0,
            platform="Snowflake",
        )
        hi = _write_timing_bundle(
            tmp_path,
            "hi.json",
            _flat_queries(base=4000.0),
            scale_factor=10.0,
            geomean_ms=4000.0,
            platform="Snowflake",
            rows_loaded=86_586_082,
        )
        results = validate_bundles([lo, hi])
        assert all(vr.ok for vr in results)
        assert not any("scale-invariant" in w for vr in results for w in vr.warnings)

    def test_micro_benchmark_flat_scales_are_expected_not_suspicious(self, tmp_path):
        lo = _write_timing_bundle(
            tmp_path,
            "lo.json",
            _flat_queries(base=4500.0),
            benchmark="read_primitives",
            scale_factor=0.1,
            geomean_ms=4531.0,
            platform="Snowflake",
        )
        hi = _write_timing_bundle(
            tmp_path,
            "hi.json",
            _flat_queries(base=4900.0),
            benchmark="read_primitives",
            scale_factor=10.0,
            geomean_ms=4967.0,
            platform="Snowflake",
            rows_loaded=86_586_082,
        )
        results = validate_bundles([lo, hi])
        assert all(vr.ok for vr in results)
        assert not any("scale-invariant" in w for vr in results for w in vr.warnings)

    def test_missing_geomean_is_disclosed_not_silently_averaged(self, tmp_path):
        lo = _write_timing_bundle(
            tmp_path,
            "lo.json",
            _flat_queries(base=4500.0),
            scale_factor=0.1,
            geomean_ms=None,
            platform="Snowflake",
        )
        hi = _write_timing_bundle(
            tmp_path,
            "hi.json",
            _flat_queries(base=4900.0),
            scale_factor=10.0,
            geomean_ms=4967.0,
            platform="Snowflake",
            rows_loaded=86_586_082,
        )
        results = validate_bundles([lo, hi])
        assert all(vr.ok for vr in results)
        # The per-query leg still evaluates, but the message must admit the
        # geomean leg could not run — never a silent arithmetic-mean fallback.
        warned = [w for vr in results for w in vr.warnings if "scale-invariant" in w]
        assert warned
        assert all("geomean unevaluable" in w for w in warned)

    def test_partial_bundles_do_not_distort(self, tmp_path):
        lo = _write_timing_bundle(
            tmp_path,
            "lo.json",
            _flat_queries(base=4500.0),
            scale_factor=0.1,
            geomean_ms=4531.0,
            platform="Snowflake",
        )
        hi = _write_timing_bundle(
            tmp_path,
            "hi.json",
            _flat_queries(base=4900.0),
            scale_factor=10.0,
            geomean_ms=4967.0,
            platform="Snowflake",
            rows_loaded=86_586_082,
            validation="partial",
        )
        results = validate_bundles([lo, hi], allow_partial_validation=True)
        assert all(vr.ok for vr in results)
        assert not any("scale-invariant" in w for vr in results for w in vr.warnings)


class TestFloorOutlier:
    def _peer_set(self, tmp_path, floors, platforms=None):
        paths = []
        for i, floor in enumerate(floors):
            paths.append(
                _write_timing_bundle(
                    tmp_path,
                    f"p{i}.json",
                    {"Q1": floor, "Q2": floor + 500, "Q3": floor + 1000},
                    scale_factor=1.0,
                    geomean_ms=floor + 500,
                    platform=f"Engine{i}" if platforms is None else platforms[i],
                    rows_loaded=8_661_245,
                )
            )
        # Mirror lane: these peer fixtures are deliberately short-coverage
        # synthetic bundles; the coverage gate is orthogonal to peer logic.
        return validate_bundles(paths, allow_partial_validation=True)

    def test_slow_peer_warns_informationally(self, tmp_path):
        slow, mid, fast = self._peer_set(tmp_path, [4500.0, 350.0, 300.0])
        assert slow.ok and mid.ok and fast.ok
        assert any("floor-outlier" in w for w in slow.warnings)
        assert not any("floor-outlier" in w for w in mid.warnings)
        assert not any("floor-outlier" in w for w in fast.warnings)

    def test_pair_without_peers_is_silent(self, tmp_path):
        first, second = self._peer_set(tmp_path, [4500.0, 300.0])
        assert first.ok and second.ok
        assert not any("floor-outlier" in w for vr in (first, second) for w in vr.warnings)

    def test_same_platform_reruns_are_not_peers(self, tmp_path):
        # Three reruns of one engine satisfy the bundle-count quorum but
        # offer zero cross-platform evidence: no outlier may be declared.
        results = self._peer_set(tmp_path, [4500.0, 350.0, 300.0], platforms=["SameEngine"] * 3)
        assert all(vr.ok for vr in results)
        assert not any("floor-outlier" in w for vr in results for w in vr.warnings)

    def test_own_platform_rerun_does_not_dilute_peers(self, tmp_path):
        # A fast rerun of the slow engine shares its platform key, so it is
        # consolidated away; the two genuinely distinct peers still convict.
        slow, _mid, _fast, rerun = self._peer_set(
            tmp_path,
            [4500.0, 350.0, 300.0, 360.0],
            platforms=["SlowEngine", "EngineB", "EngineC", "SlowEngine"],
        )
        assert all(vr.ok for vr in (slow, rerun))
        assert any("floor-outlier" in w for w in slow.warnings)
        assert not any("floor-outlier" in w for w in rerun.warnings)


# compliance_class + canonical query-set coverage gates
# ---------------------------------------------------------------------------


class TestSubmissionDeterministicGates:
    def test_unofficial_compliance_refused_in_community_mode(self):
        for compliance in ("unofficial_nonstandard", "unofficial_subscale"):
            data = _minimal_bundle()
            data["benchmark"]["compliance_class"] = compliance
            vr = ValidationResult("test")
            _validate_bundle(data, vr)
            assert not vr.ok
            assert any("compliance_class" in e for e in vr.errors)

    def test_official_compliance_passes(self):
        data = _minimal_bundle()
        data["benchmark"]["compliance_class"] = "official"
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert vr.ok, vr.errors

    def test_absent_compliance_class_grandfathered(self):
        data = _minimal_bundle()
        assert "compliance_class" not in data["benchmark"]
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert vr.ok, vr.errors

    def test_unofficial_compliance_allowed_on_mirror_lane(self):
        data = _minimal_bundle()
        data["benchmark"]["compliance_class"] = "unofficial_subscale"
        vr = ValidationResult("test")
        _validate_bundle(data, vr, allow_partial_validation=True)
        assert vr.ok, vr.errors

    def test_short_query_coverage_refused_in_community_mode(self):
        data = _minimal_bundle()
        data["queries"] = [{"id": f"Q{i}", "ms": 100, "status": "SUCCESS"} for i in range(1, 6)]
        data["summary"]["queries"] = {"total": 5, "passed": 5, "failed": 0}
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert not vr.ok
        assert any("canonical queries" in e for e in vr.errors)

    def test_full_query_coverage_passes(self):
        vr = ValidationResult("test")
        _validate_bundle(_minimal_bundle(), vr)
        assert vr.ok, vr.errors

    def test_short_coverage_allowed_on_mirror_lane(self):
        data = _minimal_bundle()
        data["summary"]["validation"] = "partial"
        data["summary"]["queries"] = {"total": 5, "passed": 5, "failed": 0}
        data["queries"] = [{"id": f"Q{i}", "ms": 100, "status": "SUCCESS"} for i in range(1, 6)]
        vr = ValidationResult("test")
        _validate_bundle(data, vr, allow_partial_validation=True)
        assert vr.ok, vr.errors

    def test_unknown_benchmark_skips_coverage(self):
        data = _minimal_bundle()
        data["benchmark"]["id"] = "some_new_benchmark"
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert vr.ok, vr.errors

    def test_case_variant_benchmark_id_still_gated(self):
        for bm_id in ("TPCH", "tpch ", " Tpch"):
            data = _minimal_bundle()
            data["benchmark"]["id"] = bm_id
            data["queries"] = [{"id": f"Q{i}", "ms": 100, "status": "SUCCESS"} for i in range(1, 6)]
            data["summary"]["queries"] = {"total": 5, "passed": 5, "failed": 0}
            vr = ValidationResult("test")
            _validate_bundle(data, vr)
            assert not vr.ok
            assert any("canonical queries" in e for e in vr.errors)

    def test_non_string_query_ids_do_not_count_toward_coverage(self):
        data = _minimal_bundle()
        data["queries"] = [{"id": i, "ms": 100, "status": "SUCCESS"} for i in range(1, 23)]
        data["summary"]["queries"] = {"total": 22, "passed": 22, "failed": 0}
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert not vr.ok
        assert any("non-string or blank id" in e for e in vr.errors)

    def test_non_official_compliance_refused_in_community_mode(self):
        for compliance in ("unofficial", "Official", "official ", 123, True):
            data = _minimal_bundle()
            data["benchmark"]["compliance_class"] = compliance
            vr = ValidationResult("test")
            _validate_bundle(data, vr)
            assert not vr.ok, compliance
            assert any("compliance_class" in e for e in vr.errors)

    def test_canonical_counts_match_explorer_transformer(self):
        from _project.scripts.explorer_pipeline.transformer import (
            _KNOWN_LOGICAL_QUERY_COUNTS,
        )
        from benchbox.validation.bundle import CANONICAL_LOGICAL_QUERY_COUNTS

        assert CANONICAL_LOGICAL_QUERY_COUNTS == _KNOWN_LOGICAL_QUERY_COUNTS

    def test_matching_cardinality_with_wrong_ids_is_refused(self):
        # 22 distinct labels, none of them canonical: cardinality alone
        # must not pass the gate.
        data = _minimal_bundle()
        data["queries"] = [{"id": f"FAKE{i}", "ms": 100, "status": "SUCCESS"} for i in range(22)]
        data["summary"]["queries"] = {"total": 22, "passed": 22, "failed": 0}
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert not vr.ok
        assert any("covers 0 of 22 canonical queries" in e for e in vr.errors)
        assert any("missing:" in e for e in vr.errors)

    def test_canonical_membership_accepts_producer_id_variants(self):
        # Q-prefix, bare, padded, and query_-prefixed spellings all name
        # the same canonical queries once normalized.
        variants = [f"Q{i}" for i in range(1, 8)] + [str(i) for i in range(8, 15)]
        variants += [f"query_{i}" for i in range(15, 20)] + [f"  q{i} " for i in range(20, 23)]
        data = _minimal_bundle()
        data["queries"] = [{"id": v, "ms": 100, "status": "SUCCESS"} for v in variants]
        data["summary"]["queries"] = {"total": 22, "passed": 22, "failed": 0}
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert vr.ok, vr.errors

    def test_canonical_membership_allows_extra_ids(self):
        data = _minimal_bundle()
        data["queries"] = data["queries"] + [{"id": "EXTRA", "ms": 100, "status": "SUCCESS"}]
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert vr.ok, vr.errors

    def test_canonical_id_sets_agree_with_counts(self):
        from benchbox.validation.bundle import (
            CANONICAL_LOGICAL_QUERY_COUNTS,
            CANONICAL_LOGICAL_QUERY_IDS,
        )

        assert set(CANONICAL_LOGICAL_QUERY_IDS) == set(CANONICAL_LOGICAL_QUERY_COUNTS)
        for family, ids in CANONICAL_LOGICAL_QUERY_IDS.items():
            assert len(ids) == CANONICAL_LOGICAL_QUERY_COUNTS[family], family

    def test_ssb_and_clickbench_membership(self):
        from benchbox.validation.bundle import CANONICAL_LOGICAL_QUERY_IDS

        assert len(CANONICAL_LOGICAL_QUERY_IDS["ssb"]) == 13
        assert "1.1" in CANONICAL_LOGICAL_QUERY_IDS["ssb"]
        assert "4.3" in CANONICAL_LOGICAL_QUERY_IDS["ssb"]
        assert len(CANONICAL_LOGICAL_QUERY_IDS["clickbench"]) == 43
        # SSB flight IDs in producer Q-prefixed form validate.
        data = _minimal_bundle()
        data["benchmark"]["id"] = "ssb"
        data["queries"] = [
            {"id": qid, "ms": 100, "status": "SUCCESS"}
            for qid in (
                "Q1.1",
                "Q1.2",
                "Q1.3",
                "Q2.1",
                "Q2.2",
                "Q2.3",
                "Q3.1",
                "Q3.2",
                "Q3.3",
                "Q3.4",
                "Q4.1",
                "Q4.2",
                "Q4.3",
            )
        ]
        data["summary"]["queries"] = {"total": 13, "passed": 13, "failed": 0}
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert vr.ok, vr.errors


# ---------------------------------------------------------------------------
# _validate_manifest_hash
# ---------------------------------------------------------------------------


class TestValidateManifestHash:
    @staticmethod
    def _hash_of(file_path: Path) -> str:
        import hashlib

        return hashlib.sha256(file_path.read_bytes()).hexdigest()

    def test_matching_hash_passes(self, tmp_path: Path):
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        bundle_file = bundle_dir / "result.json"
        bundle_file.write_text(json.dumps(_minimal_bundle()), encoding="utf-8")

        manifest = bundle_dir / "submission-manifest.json"
        manifest.write_text(
            json.dumps({"bundle_file": "result.json", "bundle_hash": self._hash_of(bundle_file)}),
            encoding="utf-8",
        )

        vr = ValidationResult("test")
        _validate_manifest_hash(manifest, bundle_dir, vr)
        assert vr.ok

    def test_oversized_applied_companion_bytes_are_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(bundle_module, "APPLIED_COMPANION_MAX_BYTES", 32)
        bundle_file = tmp_path / "result.json"
        bundle_file.write_text(json.dumps(_minimal_bundle()), encoding="utf-8")
        companion = tmp_path / "result.applied.json"
        companion.write_text(json.dumps({"receipt": {"entries": [], "padding": "x" * 64}}), encoding="utf-8")
        manifest = tmp_path / "submission-manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "bundle_file": bundle_file.name,
                    "bundle_hash": self._hash_of(bundle_file),
                    "companion_hashes": {companion.name: self._hash_of(companion)},
                }
            ),
            encoding="utf-8",
        )

        vr = ValidationResult("test")
        _validate_manifest_hash(manifest, tmp_path, vr)

        assert any("byte limit" in error for error in vr.errors)

    def test_oversized_applied_receipt_entry_count_is_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(bundle_module, "APPLIED_RECEIPT_MAX_ENTRIES", 1)
        bundle_file = tmp_path / "result.json"
        bundle_file.write_text(json.dumps(_minimal_bundle()), encoding="utf-8")
        companion = tmp_path / "result.applied.json"
        companion.write_text(json.dumps({"receipt": {"entries": [{}, {}]}}), encoding="utf-8")
        manifest = tmp_path / "submission-manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "bundle_file": bundle_file.name,
                    "bundle_hash": self._hash_of(bundle_file),
                    "companion_hashes": {companion.name: self._hash_of(companion)},
                }
            ),
            encoding="utf-8",
        )

        vr = ValidationResult("test")
        _validate_manifest_hash(manifest, tmp_path, vr)

        assert any("entry limit" in error for error in vr.errors)

    def test_mismatched_hash_fails(self, tmp_path: Path):
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        (bundle_dir / "result.json").write_text("{}", encoding="utf-8")

        manifest = bundle_dir / "submission-manifest.json"
        manifest.write_text(
            json.dumps({"bundle_file": "result.json", "bundle_hash": "deadbeef" * 8}),
            encoding="utf-8",
        )

        vr = ValidationResult("test")
        _validate_manifest_hash(manifest, bundle_dir, vr)
        assert not vr.ok
        assert any("hash mismatch" in e.lower() for e in vr.errors)
        assert any("result.json" in e for e in vr.errors)

    def test_missing_hash_field_errors(self, tmp_path: Path):
        # A present manifest whose whole purpose is the bundle-hash contract
        # must carry it. Missing bundle_hash is an ERROR (not a warning), so an
        # empty/incomplete manifest cannot pass CI while still granting the
        # sidecar-derived community-submission trust label.
        manifest = tmp_path / "submission-manifest.json"
        manifest.write_text(json.dumps({"bundle_file": "result.json"}), encoding="utf-8")

        vr = ValidationResult("test")
        _validate_manifest_hash(manifest, tmp_path, vr)
        assert not vr.ok
        assert any("no bundle_hash" in e for e in vr.errors)

    def test_missing_bundle_file_field_errors(self, tmp_path: Path):
        manifest = tmp_path / "submission-manifest.json"
        manifest.write_text(json.dumps({"bundle_hash": "deadbeef" * 8}), encoding="utf-8")

        vr = ValidationResult("test")
        _validate_manifest_hash(manifest, tmp_path, vr)
        assert not vr.ok
        assert any("no bundle_file" in e for e in vr.errors)

    @pytest.mark.parametrize("bad_hash", [123, None, ["abc"], {"hash": "x"}])
    def test_non_string_hash_errors(self, tmp_path: Path, bad_hash):
        """Non-string bundle_hash values should error (not crash, not pass)."""
        manifest = tmp_path / "submission-manifest.json"
        manifest.write_text(
            json.dumps({"bundle_file": "result.json", "bundle_hash": bad_hash}),
            encoding="utf-8",
        )

        vr = ValidationResult("test")
        _validate_manifest_hash(manifest, tmp_path, vr)
        assert not vr.ok
        assert any("no bundle_hash" in e for e in vr.errors)

    def test_companion_hash_mismatch_fails(self, tmp_path: Path):
        """A companion file with a wrong hash must surface a per-file error."""
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        bundle_file = bundle_dir / "result.json"
        bundle_file.write_text(json.dumps(_minimal_bundle()), encoding="utf-8")
        plans_file = bundle_dir / "result.plans.json"
        plans_file.write_text("{}", encoding="utf-8")

        manifest = bundle_dir / "submission-manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "bundle_file": "result.json",
                    "bundle_hash": self._hash_of(bundle_file),
                    "companion_hashes": {"result.plans.json": "wrong" + "0" * 59},
                }
            ),
            encoding="utf-8",
        )

        vr = ValidationResult("test")
        _validate_manifest_hash(manifest, bundle_dir, vr)
        assert not vr.ok
        assert any("Companion hash mismatch" in e and "result.plans.json" in e for e in vr.errors)

    @pytest.mark.parametrize(
        "unsafe_name",
        [
            "../escape.json",
            "subdir/result.json",
            "/etc/passwd",
            "..",
            "a\x00b.json",
            "a\\b.json",
        ],
    )
    def test_unsafe_bundle_filename_rejected(self, tmp_path: Path, unsafe_name: str):
        """Manifest-supplied filenames must not escape the bundle directory."""
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        manifest = bundle_dir / "submission-manifest.json"
        manifest.write_text(
            json.dumps({"bundle_file": unsafe_name, "bundle_hash": "a" * 64}),
            encoding="utf-8",
        )

        vr = ValidationResult("test")
        _validate_manifest_hash(manifest, bundle_dir, vr)
        assert not vr.ok
        assert any("Unsafe bundle_file" in e for e in vr.errors)

    def test_unsafe_companion_filename_rejected(self, tmp_path: Path):
        """Companion-hash keys must also be plain filenames."""
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        bundle_file = bundle_dir / "result.json"
        bundle_file.write_text(json.dumps(_minimal_bundle()), encoding="utf-8")

        manifest = bundle_dir / "submission-manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "bundle_file": "result.json",
                    "bundle_hash": self._hash_of(bundle_file),
                    "companion_hashes": {"../escape.plans.json": "a" * 64},
                }
            ),
            encoding="utf-8",
        )

        vr = ValidationResult("test")
        _validate_manifest_hash(manifest, bundle_dir, vr)
        assert not vr.ok
        assert any("Unsafe companion filename" in e for e in vr.errors)

    def test_robust_when_corpus_already_populated(self, tmp_path: Path):
        """Sibling bundles in the directory must not affect validation.

        Regression coverage for the directory-vs-file-scope hash bug
        (filed and fixed 2026-04-27 via
        fix-submission-hash-mismatch-vs-validator-directory-scope).
        """
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        bundle_file = bundle_dir / "result.json"
        bundle_file.write_text(json.dumps(_minimal_bundle()), encoding="utf-8")

        manifest = bundle_dir / "submission-manifest.json"
        manifest.write_text(
            json.dumps({"bundle_file": "result.json", "bundle_hash": self._hash_of(bundle_file)}),
            encoding="utf-8",
        )

        (bundle_dir / "other_existing_1.json").write_text("{}", encoding="utf-8")
        (bundle_dir / "other_existing_2.json").write_text("{}", encoding="utf-8")

        vr = ValidationResult("test")
        _validate_manifest_hash(manifest, bundle_dir, vr)
        assert vr.ok, f"Expected pass with sibling bundles present, got: {vr.errors}"


# ---------------------------------------------------------------------------
# discover_bundles
# ---------------------------------------------------------------------------


class TestDiscoverBundles:
    def test_finds_primary_bundles(self, tmp_path: Path):
        (tmp_path / "result.json").write_text("{}", encoding="utf-8")
        (tmp_path / "result.plans.json").write_text("{}", encoding="utf-8")
        (tmp_path / "result.tuning.json").write_text("{}", encoding="utf-8")
        (tmp_path / "result.applied.json").write_text("{}", encoding="utf-8")
        (tmp_path / "result.manifest.json").write_text("{}", encoding="utf-8")
        (tmp_path / "corpus-inventory.json").write_text("{}", encoding="utf-8")
        (tmp_path / "submission-manifest.json").write_text("{}", encoding="utf-8")

        found = discover_bundles(tmp_path)
        assert len(found) == 1
        assert found[0].name == "result.json"

    def test_ignores_json_named_directories_and_companions_case_insensitively(self, tmp_path: Path):
        (tmp_path / "directory.json").mkdir()
        (tmp_path / "result.JSON").write_text("{}", encoding="utf-8")
        (tmp_path / "result.APPLIED.JSON").write_text("{}", encoding="utf-8")

        assert discover_bundles(tmp_path) == [tmp_path / "result.JSON"]


# ---------------------------------------------------------------------------
# validate_bundles (integration)
# ---------------------------------------------------------------------------


class TestValidateBundles:
    def test_valid_file(self, valid_bundle_file: Path):
        results = validate_bundles([valid_bundle_file])
        assert len(results) == 1
        assert results[0].ok

    def test_invalid_json(self, tmp_path: Path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        results = validate_bundles([bad])
        assert len(results) == 1
        assert not results[0].ok
        assert any("Invalid JSON" in e for e in results[0].errors)

    def test_conflicting_schema_aliases_are_reported_per_bundle(self, tmp_path: Path):
        bundle = tmp_path / "conflicting.json"
        payload = _minimal_bundle()
        payload["result_schema_version"] = "2.2"
        payload["version"] = "2.1"
        bundle.write_text(json.dumps(payload), encoding="utf-8")

        results = validate_bundles([bundle])

        assert len(results) == 1
        assert not results[0].ok
        assert any("must match" in error for error in results[0].errors)

    def test_nonexistent_file(self, tmp_path: Path):
        missing = tmp_path / "nope.json"
        results = validate_bundles([missing])
        assert len(results) == 1
        assert not results[0].ok

    def test_json_named_directory_returns_clean_validation_error(self, tmp_path: Path):
        directory = tmp_path / "not-a-bundle.json"
        directory.mkdir()

        results = validate_bundles([directory])

        assert not results[0].ok
        assert any("regular file" in error for error in results[0].errors)

    def test_unlisted_adjacent_applied_companion_still_obeys_caps(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(bundle_module, "APPLIED_COMPANION_MAX_BYTES", 32)
        bundle = tmp_path / "result.json"
        bundle.write_text(json.dumps(_minimal_bundle()), encoding="utf-8")
        (tmp_path / "result.applied.json").write_text(
            json.dumps({"receipt": {"entries": [], "padding": "x" * 64}}), encoding="utf-8"
        )

        results = validate_bundles([bundle])

        assert not results[0].ok
        assert any("byte limit" in error for error in results[0].errors)

    def test_non_object_json(self, tmp_path: Path):
        f = tmp_path / "array.json"
        f.write_text("[]", encoding="utf-8")
        results = validate_bundles([f])
        assert not results[0].ok
        assert any("JSON object" in e for e in results[0].errors)

    def test_explicit_manifest_paths_are_ignored(self, tmp_path: Path):
        bundle = tmp_path / "result.json"
        bundle.write_text(json.dumps(_minimal_bundle()), encoding="utf-8")
        manifest = tmp_path / "result.manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "bundle_file": bundle.name,
                    "bundle_hash": hashlib.sha256(bundle.read_bytes()).hexdigest(),
                }
            ),
            encoding="utf-8",
        )

        results = validate_bundles([bundle, manifest])

        assert len(results) == 1
        assert results[0].ok

    def test_present_but_empty_manifest_fails_end_to_end(self, tmp_path: Path):
        # A present-but-contentless sidecar must not pass: it would otherwise
        # grant the sidecar-derived community-submission trust label while the
        # bundle bytes are never hash-verified.
        bundle = tmp_path / "result.json"
        bundle.write_text(json.dumps(_minimal_bundle()), encoding="utf-8")
        manifest = tmp_path / "result.manifest.json"
        manifest.write_text(json.dumps({}), encoding="utf-8")

        results = validate_bundles([bundle])

        assert len(results) == 1
        assert not results[0].ok
        assert any("bundle_hash" in e or "bundle_file" in e for e in results[0].errors)

    def test_missing_sidecar_passes_by_default(self, valid_bundle_file: Path):
        # Default (maintainer path): no sidecar is fine — absence of a sidecar
        # is how a maintainer-run bundle is distinguished.
        results = validate_bundles([valid_bundle_file])
        assert results[0].ok

    def test_require_manifest_errors_on_missing_sidecar(self, valid_bundle_file: Path):
        # Community path: the sidecar is mandatory.
        results = validate_bundles([valid_bundle_file], require_manifest=True)
        assert len(results) == 1
        assert not results[0].ok
        assert any("manifest not found" in e.lower() for e in results[0].errors)

    def test_require_manifest_passes_when_sidecar_present(self, tmp_path: Path):
        bundle = tmp_path / "result.json"
        bundle.write_text(json.dumps(_minimal_bundle()), encoding="utf-8")
        manifest = tmp_path / "result.manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "bundle_file": bundle.name,
                    "bundle_hash": hashlib.sha256(bundle.read_bytes()).hexdigest(),
                }
            ),
            encoding="utf-8",
        )
        results = validate_bundles([bundle], require_manifest=True)
        assert results[0].ok


class TestRequireManifestCli:
    def test_cli_require_manifest_flag_fails_missing_sidecar(self, tmp_path: Path, capsys):
        bundle = tmp_path / "result.json"
        bundle.write_text(json.dumps(_minimal_bundle()), encoding="utf-8")
        rc = main([str(bundle), "--require-manifest"])
        assert rc == 1

    def test_cli_without_flag_allows_missing_sidecar(self, tmp_path: Path, capsys):
        bundle = tmp_path / "result.json"
        bundle.write_text(json.dumps(_minimal_bundle()), encoding="utf-8")
        rc = main([str(bundle)])
        assert rc == 0


class TestAllowPartialValidation:
    def test_cli_community_default_rejects_partial(self, tmp_path: Path, capsys):
        bundle = tmp_path / "partial.json"
        data = _minimal_bundle()
        data["summary"]["validation"] = "partial"
        bundle.write_text(json.dumps(data), encoding="utf-8")
        assert main([str(bundle)]) == 1
        captured = capsys.readouterr()
        assert "must be 'passed'" in captured.out or "must be 'passed'" in captured.err

    def test_cli_allow_partial_accepts_seed_shaped_partial(self, tmp_path: Path, capsys):
        bundle = tmp_path / "partial.json"
        data = _minimal_bundle()
        data["summary"]["validation"] = "partial"
        bundle.write_text(json.dumps(data), encoding="utf-8")
        assert main([str(bundle), "--allow-partial-validation"]) == 0

    def test_allow_partial_still_rejects_private_path_leaks(self, tmp_path: Path, capsys):
        """Privacy fail-closed is independent of the partial waiver."""
        bundle = tmp_path / "leaky-partial.json"
        data = _minimal_bundle()
        data["summary"]["validation"] = "partial"
        data["platform"]["config"] = {"working_dir": "/Users/alice/private"}
        bundle.write_text(json.dumps(data), encoding="utf-8")
        assert main([str(bundle), "--allow-partial-validation"]) == 1


# ---------------------------------------------------------------------------
# format_summary / format_pr_comment
# ---------------------------------------------------------------------------


class TestFormatters:
    def test_format_summary_includes_counts(self, valid_bundle_file: Path):
        results = validate_bundles([valid_bundle_file])
        summary = format_summary(results)
        assert "1 bundle" in summary
        assert "0 error" in summary

    def test_format_pr_comment_markdown(self, valid_bundle_file: Path):
        results = validate_bundles([valid_bundle_file])
        md = format_pr_comment(results)
        assert "## Submission Validation: PASSED" in md
        assert "tpch" in md
        assert "DuckDB" in md


# ---------------------------------------------------------------------------
# main() CLI entrypoint
# ---------------------------------------------------------------------------


class TestMain:
    def test_no_args_returns_1(self):
        assert main([]) == 1

    def test_valid_dir(self, bundle_dir: Path):
        assert main([str(bundle_dir)]) == 0

    def test_invalid_bundle(self, tmp_path: Path):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"version": "1.0"}), encoding="utf-8")
        assert main([str(bad)]) == 1

    def test_malformed_public_companion_fails_closed(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        bundle = tmp_path / "tpch_result.json"
        bundle.write_text(json.dumps(_minimal_bundle()), encoding="utf-8")
        bundle.with_name("tpch_result.plans.json").write_text(
            '{"plan": "/Users/alice/private" not-json',
            encoding="utf-8",
        )

        assert main([str(bundle)]) == 1
        assert "Malformed public companion JSON" in capsys.readouterr().out

    def test_case_insensitive_companion_name_is_privacy_scanned(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        bundle = tmp_path / "tpch_result.json"
        bundle.write_text(json.dumps(_minimal_bundle()), encoding="utf-8")
        bundle.with_name("tpch_result.PLANS.JSON").write_text(
            json.dumps({"path": "/Users/alice/private"}),
            encoding="utf-8",
        )

        assert main([str(bundle)]) == 1
        output = capsys.readouterr().out
        assert "PLANS.JSON" in output
        assert "private absolute paths" in output
