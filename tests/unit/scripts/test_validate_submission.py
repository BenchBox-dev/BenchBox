"""Tests for public submission bundle validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

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
            "queries": {"total": 2, "passed": 2, "failed": 0},
        },
        "queries": [
            {"id": "Q1", "ms": 100, "status": "pass"},
            {"id": "Q2", "ms": 200, "status": "pass"},
        ],
    }


def _normalized_cost_block(cost: str | None = "1.25", status: str = "normalized") -> dict:
    """Return a minimal valid BenchBox normalized-cost provenance block."""
    billing_unit = "instance_hour" if status == "normalized" else "not_applicable"
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


# ---------------------------------------------------------------------------
# _validate_bundle
# ---------------------------------------------------------------------------


class TestValidateBundle:
    def test_valid_bundle_passes(self):
        vr = ValidationResult("test")
        _validate_bundle(_minimal_bundle(), vr)
        assert vr.ok
        assert len(vr.errors) == 0

    def test_missing_top_level_keys(self):
        data = {"version": "2.1"}  # Missing everything else
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert not vr.ok
        assert any("Missing required top-level keys" in e for e in vr.errors)

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

    @pytest.mark.parametrize("status", ["not_run", "uncertain", "unknown"])
    def test_non_clean_public_validation_status_fails(self, status: str):
        data = _minimal_bundle()
        data["summary"]["validation"] = status
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert not vr.ok
        assert any("summary.validation must be 'passed'" in e for e in vr.errors)

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
            {"id": "Q1", "ms": 0, "status": "pass"},
            {"id": "Q2", "ms": 0, "status": "pass"},
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
        data["queries"] = [{"id": "Q1", "ms": 0.04, "status": "pass"}]
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

    def test_empty_queries_warns(self):
        data = _minimal_bundle()
        data["queries"] = []
        vr = ValidationResult("test")
        _validate_bundle(data, vr)
        assert vr.ok  # warning, not error
        assert any("queries array is empty" in w for w in vr.warnings)

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
        (tmp_path / "result.manifest.json").write_text("{}", encoding="utf-8")
        (tmp_path / "corpus-inventory.json").write_text("{}", encoding="utf-8")
        (tmp_path / "submission-manifest.json").write_text("{}", encoding="utf-8")

        found = discover_bundles(tmp_path)
        assert len(found) == 1
        assert found[0].name == "result.json"


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

    def test_nonexistent_file(self, tmp_path: Path):
        missing = tmp_path / "nope.json"
        results = validate_bundles([missing])
        assert len(results) == 1
        assert not results[0].ok

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
