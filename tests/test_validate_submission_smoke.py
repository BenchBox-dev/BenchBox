"""Smoke test for `scripts/validate_submission.py` on the
published-results branch.

Why this exists: this branch's CI lanes (lint.yml, test.yml) only run on
PRs to `develop` / `main`, and `validate-submission.yml` only fires when
`results-data/bundles/**` changes. A PR that edits *only* the validator
script (like the sister sync PR) would otherwise have no CI gating on
this branch. This smoke test is wired into `.github/workflows/validator-smoke.yml`
so changes to `scripts/validate_submission.py` are exercised end-to-end
before merge.

Standalone by design: no benchbox import — uses pytest + subprocess so
it works on a stripped-down CI runner without the full benchbox dev
environment.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = REPO_ROOT / "scripts" / "validate_submission.py"


def _minimal_schema_v2_bundle() -> dict:
    """Leanest payload that satisfies the validator's schema-v2 checks.

    Mirrors the fixture in develop's
    tests/integration/test_cross_branch_validator_contract.py so any
    drift between the two sides surfaces visibly.
    """
    return {
        "version": "2.0",
        "run": {
            "id": "smoke-test-run",
            "timestamp": "2026-04-29T00:00:00Z",
            "total_duration_ms": 12340,
        },
        "benchmark": {"id": "tpch", "scale_factor": 0.01},
        "platform": {"name": "duckdb"},
        "summary": {"queries": {"total": 22}},
        "queries": [{"id": "Q1", "ms": 100.0}],
    }


def _write_bundle_with_manifest(bundle_dir: Path, bundle_filename: str = "tpch_duckdb.json") -> Path:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / bundle_filename
    bundle_path.write_text(json.dumps(_minimal_schema_v2_bundle()), encoding="utf-8")

    manifest = {
        "bundle_file": bundle_filename,
        "bundle_hash": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
        "companion_hashes": {},
    }
    (bundle_dir / "submission-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return bundle_path


def _run_validator(bundle_path: Path, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(bundle_path)],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def test_validator_accepts_valid_bundle(tmp_path: Path) -> None:
    """Happy path: a valid schema-v2 bundle with a matching manifest passes."""
    bundle_path = _write_bundle_with_manifest(tmp_path / "bundle")
    proc = _run_validator(bundle_path, tmp_path)
    output = proc.stdout + proc.stderr

    assert proc.returncode == 0, f"Valid bundle was rejected:\n{output}"
    assert "0 error(s), 0 warning(s)" in output, output


def test_validator_rejects_hash_mismatch(tmp_path: Path) -> None:
    """Negative path: a manifest whose bundle_hash doesn't match the
    bundle's actual SHA-256 must be rejected."""
    bundle_dir = tmp_path / "bundle"
    bundle_path = _write_bundle_with_manifest(bundle_dir)

    manifest_path = bundle_dir / "submission-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # Tamper with the recorded hash so the validator's recomputation diverges.
    manifest["bundle_hash"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    proc = _run_validator(bundle_path, tmp_path)
    output = proc.stdout + proc.stderr

    assert proc.returncode != 0, f"Tampered manifest was wrongly accepted:\n{output}"
    assert "Bundle hash mismatch" in output, output


def test_validator_rejects_symlinked_bundle(tmp_path: Path) -> None:
    """Symlink defense: a bundle file that is actually a symlink must be
    rejected even when the symlink target's bytes happen to match the
    manifest hash. Without this check, a malicious PR could redirect the
    hash computation through a symlink to attacker-chosen bytes."""
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()

    real = tmp_path / "real_target.json"
    real.write_text(json.dumps(_minimal_schema_v2_bundle()), encoding="utf-8")

    bundle_filename = "tpch_duckdb.json"
    symlink_path = bundle_dir / bundle_filename
    symlink_path.symlink_to(real)

    manifest = {
        "bundle_file": bundle_filename,
        "bundle_hash": hashlib.sha256(real.read_bytes()).hexdigest(),
        "companion_hashes": {},
    }
    (bundle_dir / "submission-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    proc = _run_validator(symlink_path, tmp_path)
    output = proc.stdout + proc.stderr

    assert proc.returncode != 0, f"Symlinked bundle was wrongly accepted:\n{output}"
    assert "symlink" in output.lower(), output


def test_validator_script_exists() -> None:
    """Sanity: the validator script the rest of these tests exec actually
    exists at the expected path. Catches accidental relocations early."""
    assert VALIDATOR.is_file(), f"Validator script not found at {VALIDATOR}"
