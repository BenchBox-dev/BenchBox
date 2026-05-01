"""Tests for scripts/validate_submission.py."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from validate_submission import (
    ValidationResult,
    _validate_bundle,
    _validate_manifest_hash,
    discover_bundles,
    format_pr_comment,
    format_summary,
    main,
    validate_bundles,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

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
            "queries": {"total": 2, "passed": 2, "failed": 0},
        },
        "queries": [
            {"id": "Q1", "ms": 100, "status": "pass"},
            {"id": "Q2", "ms": 200, "status": "pass"},
        ],
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

    def test_missing_hash_field_warns(self, tmp_path: Path):
        manifest = tmp_path / "submission-manifest.json"
        manifest.write_text(json.dumps({"bundle_file": "result.json"}), encoding="utf-8")

        vr = ValidationResult("test")
        _validate_manifest_hash(manifest, tmp_path, vr)
        assert vr.ok
        assert any("no bundle_hash" in w for w in vr.warnings)

    def test_missing_bundle_file_field_warns(self, tmp_path: Path):
        manifest = tmp_path / "submission-manifest.json"
        manifest.write_text(json.dumps({"bundle_hash": "deadbeef" * 8}), encoding="utf-8")

        vr = ValidationResult("test")
        _validate_manifest_hash(manifest, tmp_path, vr)
        assert vr.ok
        assert any("no bundle_file" in w for w in vr.warnings)

    @pytest.mark.parametrize("bad_hash", [123, None, ["abc"], {"hash": "x"}])
    def test_non_string_hash_warns(self, tmp_path: Path, bad_hash):
        """Non-string bundle_hash values should warn, not crash."""
        manifest = tmp_path / "submission-manifest.json"
        manifest.write_text(
            json.dumps({"bundle_file": "result.json", "bundle_hash": bad_hash}),
            encoding="utf-8",
        )

        vr = ValidationResult("test")
        _validate_manifest_hash(manifest, tmp_path, vr)
        assert vr.ok
        assert any("no bundle_hash" in w for w in vr.warnings)

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
