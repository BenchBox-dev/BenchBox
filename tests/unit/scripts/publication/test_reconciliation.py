"""Unit tests for publication reconciliation, independence matrix, and operational receipts."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

# Load modules under test via spec
ROOT = Path(__file__).resolve().parents[4]

RECON_SCRIPT = ROOT / "scripts" / "publication" / "reconciliation.py"
RECON_SPEC = importlib.util.spec_from_file_location("reconciliation", RECON_SCRIPT)
assert RECON_SPEC and RECON_SPEC.loader
recon_mod = importlib.util.module_from_spec(RECON_SPEC)
sys.modules[RECON_SPEC.name] = recon_mod
RECON_SPEC.loader.exec_module(recon_mod)

MATRIX_SCRIPT = ROOT / "scripts" / "publication" / "verify_independence_matrix.py"
MATRIX_SPEC = importlib.util.spec_from_file_location("verify_independence_matrix", MATRIX_SCRIPT)
assert MATRIX_SPEC and MATRIX_SPEC.loader
matrix_mod = importlib.util.module_from_spec(MATRIX_SPEC)
sys.modules[MATRIX_SPEC.name] = matrix_mod
MATRIX_SPEC.loader.exec_module(matrix_mod)

RECEIPTS_SCRIPT = ROOT / "scripts" / "publication" / "check_operational_receipts.py"
RECEIPTS_SPEC = importlib.util.spec_from_file_location("check_operational_receipts", RECEIPTS_SCRIPT)
assert RECEIPTS_SPEC and RECEIPTS_SPEC.loader
receipts_mod = importlib.util.module_from_spec(RECEIPTS_SPEC)
sys.modules[RECEIPTS_SPEC.name] = receipts_mod
RECEIPTS_SPEC.loader.exec_module(receipts_mod)


class MockHTTPResponse:
    def __init__(self, body: bytes, status: int = 200, headers: dict[str, str] | None = None):
        self._body = io.BytesIO(body)
        self.status = status
        self.headers = headers or {"content-type": "application/octet-stream"}

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def __enter__(self) -> MockHTTPResponse:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass


# ==============================================================================
# RECONCILIATION & DRIFT TESTS (w1)
# ==============================================================================


def test_reconciliation_happy_path_matched_states() -> None:
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    manifest = {
        "generation": 5,
        "source_commit": "1111111111111111111111111111111111111111",
        "source_branch": "develop",
        "build_closure": {
            "lockfile_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "workflow_sha": "2222222222222222222222222222222222222222",
            "read_model_version": "v1",
        },
        "artifacts": {
            "explorer_app": {
                "digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "path": "/results/",
            },
            "corpus_database": {
                "digest": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
                "path": "/results/data/results.duckdb",
            },
        },
    }

    built = {
        "generation": 5,
        "source_commit": "1111111111111111111111111111111111111111",
        "build_closure": dict(manifest["build_closure"]),
        "artifacts": dict(manifest["artifacts"]),
    }

    deployed = {
        "generation": 5,
        "source_commit": "1111111111111111111111111111111111111111",
        "status": "DEPLOYED",
    }

    observed = {
        "generation": 5,
        "timestamp": now_iso,
        "checksums": {
            "/results/": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "/results/data/results.duckdb": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        },
    }

    report = recon_mod.reconcile_states(
        desired=manifest,
        built=built,
        deployed=deployed,
        observed=observed,
        now_dt=now,
    )

    assert report.reconciled is True
    assert report.drift_count == 0
    assert len(report.drifts) == 0
    assert report.desired_generation == 5
    assert report.deployed_generation == 5
    assert report.observed_generation == 5
    assert report.receipt_age_hours == 0.0


def test_reconciliation_generation_drift_detection() -> None:
    now = datetime.now(timezone.utc)
    manifest = {"generation": 6, "source_commit": "aaaa"}
    deployed = {"generation": 5, "source_commit": "aaaa"}  # lagging generation
    observed = {"generation": 5, "timestamp": now.isoformat()}

    report = recon_mod.reconcile_states(
        desired=manifest,
        built=manifest,
        deployed=deployed,
        observed=observed,
        now_dt=now,
    )

    assert report.reconciled is False
    assert any(d.drift_type == "GENERATION_DRIFT" for d in report.drifts)
    gen_drift = next(d for d in report.drifts if d.drift_type == "GENERATION_DRIFT")
    assert gen_drift.expected == 6
    assert gen_drift.actual == 5


def test_reconciliation_manifest_drift_detection() -> None:
    now = datetime.now(timezone.utc)
    manifest = {
        "generation": 1,
        "source_commit": "1111111111111111111111111111111111111111",
        "build_closure": {"lockfile_sha256": "lock_sha_A"},
    }
    built = {
        "generation": 1,
        "source_commit": "1111111111111111111111111111111111111111",
        "build_closure": {"lockfile_sha256": "lock_sha_B"},  # lockfile mismatch
    }
    deployed = {
        "generation": 1,
        "source_commit": "2222222222222222222222222222222222222222",  # commit mismatch
    }
    observed = {"generation": 1, "timestamp": now.isoformat()}

    report = recon_mod.reconcile_states(
        desired=manifest,
        built=built,
        deployed=deployed,
        observed=observed,
        now_dt=now,
    )

    assert report.reconciled is False
    manifest_drifts = [d for d in report.drifts if d.drift_type == "MANIFEST_DRIFT"]
    assert len(manifest_drifts) >= 2


def test_reconciliation_artifact_drift_detection() -> None:
    now = datetime.now(timezone.utc)
    manifest = {
        "generation": 1,
        "artifacts": {
            "explorer": {"path": "/results/", "digest": "sha_expected"},
        },
    }
    built = {
        "generation": 1,
        "artifacts": {
            "explorer": {"path": "/results/", "digest": "sha_different_built"},
        },
    }
    observed = {
        "generation": 1,
        "timestamp": now.isoformat(),
        "checksums": {"/results/": "sha_different_live"},
    }

    report = recon_mod.reconcile_states(
        desired=manifest,
        built=built,
        deployed=manifest,
        observed=observed,
        now_dt=now,
    )

    assert report.reconciled is False
    artifact_drifts = [d for d in report.drifts if d.drift_type == "ARTIFACT_DRIFT"]
    assert len(artifact_drifts) >= 1


def test_reconciliation_stale_receipt_detection() -> None:
    now = datetime.now(timezone.utc)
    stale_time = (now - timedelta(hours=36)).isoformat()

    manifest = {"generation": 1}
    observed = {
        "generation": 1,
        "timestamp": stale_time,
    }

    report = recon_mod.reconcile_states(
        desired=manifest,
        built=manifest,
        deployed=manifest,
        observed=observed,
        max_age_hours=24.0,
        now_dt=now,
    )

    assert report.reconciled is False
    assert any(d.drift_type == "STALE_RECEIPT" for d in report.drifts)
    stale_drift = next(d for d in report.drifts if d.drift_type == "STALE_RECEIPT")
    assert "stale" in stale_drift.description
    assert report.receipt_age_hours is not None and report.receipt_age_hours >= 36.0


def test_reconciliation_live_probe_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    content = b"Simulated DuckDB live database content"
    import hashlib

    db_sha = hashlib.sha256(content).hexdigest()

    manifest = {
        "generation": 1,
        "live_database": {"sha256": db_sha},
    }

    def mock_urlopen(req, timeout=15.0):
        return MockHTTPResponse(content, status=200)

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    report = recon_mod.reconcile_states(
        desired=manifest,
        built=manifest,
        deployed=manifest,
        observed=None,
        base_url="https://benchbox.dev",
        live=True,
    )

    assert len(report.probes) == 3
    assert all(p.ok for p in report.probes)
    db_probe = next(p for p in report.probes if p.path == "/results/data/results.duckdb")
    assert db_probe.sha256 == db_sha


def test_reconciliation_cli_main_exit_codes(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        recon_mod.main(["--help"])
    assert exc_info.value.code == 0

    # 1. Valid manifest JSON
    now_iso = datetime.now(timezone.utc).isoformat()
    manifest_file = tmp_path / "test-manifest.json"
    manifest_file.write_text(
        json.dumps(
            {
                "generation": 1,
                "source_commit": "aaaa",
                "timestamp": now_iso,
            }
        ),
        encoding="utf-8",
    )

    rc = recon_mod.main(["--manifest", str(manifest_file), "--json"])
    assert rc == 0

    # 2. Non-existent manifest returns error code 2
    rc_err = recon_mod.main(["--manifest", "/tmp/non-existent-manifest-path.json"])
    assert rc_err == 2


# ==============================================================================
# INDEPENDENCE MATRIX TESTS (w2)
# ==============================================================================


def test_independence_matrix_canonical_orthogonal_verification() -> None:
    report = matrix_mod.verify_independence()
    assert report.valid is True
    assert report.transitions_checked == 4
    assert len(report.violations) == 0

    # Check 4x4 matrix is strictly identity / orthogonal
    for row in matrix_mod.LANES:
        for col in matrix_mod.LANES:
            assert report.matrix[row][col] is (row == col)


def test_independence_matrix_detects_lane_coupling() -> None:
    base = {
        "package": "p1",
        "site": "s1",
        "explorer": "e1",
        "corpus": "c1",
    }
    # Mutating site ALSO mutates explorer (coupling violation)
    coupled_after = {
        "package": "p1",
        "site": "s2",
        "explorer": "e2",  # Unintended side-effect mutation
        "corpus": "c1",
    }

    trans = matrix_mod.verify_transition_independence(
        transition_id="test_coupled_transition",
        target_lane="site",
        before_hashes=base,
        after_hashes=coupled_after,
    )

    assert trans.valid is False
    assert any("explorer" in v for v in trans.violations)

    # Check that report reports invalid
    report = matrix_mod.verify_independence(transitions=[trans])
    assert report.valid is False
    assert len(report.violations) > 0


def test_independence_matrix_detects_unmutated_target_lane() -> None:
    base = {
        "package": "p1",
        "site": "s1",
        "explorer": "e1",
        "corpus": "c1",
    }
    # Target lane package did NOT change
    no_change_after = dict(base)

    trans = matrix_mod.verify_transition_independence(
        transition_id="test_no_change_transition",
        target_lane="package",
        before_hashes=base,
        after_hashes=no_change_after,
    )

    assert trans.valid is False
    assert any("did not change" in v for v in trans.violations)


def test_independence_matrix_cli_main(tmp_path: Path) -> None:
    # CLI help and default run
    with pytest.raises(SystemExit) as exc_info:
        matrix_mod.main(["--help"])
    assert exc_info.value.code == 0

    rc_default = matrix_mod.main(["--json"])
    assert rc_default == 0

    # Invalid directory returns 2
    rc_bad = matrix_mod.main(["--receipts-dir", "/tmp/bad-receipts-dir-does-not-exist"])
    assert rc_bad == 2


# ==============================================================================
# OPERATIONAL RECEIPTS AUDIT TESTS (w2)
# ==============================================================================


def test_operational_receipts_happy_path() -> None:
    now = datetime.now(timezone.utc)
    report = receipts_mod.audit_operational_receipts(now_dt=now)

    assert report.valid is True
    assert report.capacity.passed is True
    assert report.retention.passed is True
    assert len(report.violations) == 0
    assert report.drills["rollback"].passed is True
    assert report.drills["takedown"].passed is True
    assert report.drills["incident_response"].passed is True


def test_operational_receipts_capacity_limits() -> None:
    # 1. Normal capacity
    cap_ok = receipts_mod.audit_capacity(total_bytes=50_000_000, largest_file_bytes=10_000_000)
    assert cap_ok.passed is True
    assert len(cap_ok.warnings) == 0
    assert len(cap_ok.violations) == 0

    # 2. Warning capacity (> 800 MB, <= 1 GB)
    cap_warn = receipts_mod.audit_capacity(total_bytes=850 * 1024 * 1024, largest_file_bytes=10_000_000)
    assert cap_warn.passed is True
    assert len(cap_warn.warnings) == 1
    assert len(cap_warn.violations) == 0

    # 3. Violation total size (> 1 GB)
    cap_total_err = receipts_mod.audit_capacity(total_bytes=1100 * 1024 * 1024, largest_file_bytes=10_000_000)
    assert cap_total_err.passed is False
    assert any("exceeds limit" in v for v in cap_total_err.violations)

    # 4. Violation single file size (> 100 MB)
    cap_file_err = receipts_mod.audit_capacity(
        total_bytes=200 * 1024 * 1024,
        largest_file_bytes=105 * 1024 * 1024,
        largest_file_path="big_results.duckdb",
    )
    assert cap_file_err.passed is False
    assert any("exceeds limit" in v for v in cap_file_err.violations)


def test_operational_receipts_retention_rules() -> None:
    # Transient too long (> 7 days)
    ret_err1 = receipts_mod.audit_retention(transient_days=14)
    assert ret_err1.passed is False
    assert any("Transient artifact retention" in v for v in ret_err1.violations)

    # Receipts retention too short (< 30 days)
    ret_err2 = receipts_mod.audit_retention(receipt_days=14)
    assert ret_err2.passed is False
    assert any("Receipt retention" in v for v in ret_err2.violations)

    # Rollback retention too short (< 90 days)
    ret_err3 = receipts_mod.audit_retention(rollback_days=60)
    assert ret_err3.passed is False
    assert any("Rollback checkpoint retention" in v for v in ret_err3.violations)


def test_operational_receipts_expired_drill_detection() -> None:
    now = datetime.now(timezone.utc)
    expired_time = (now - timedelta(days=45)).isoformat()

    expired_drill_data = {
        "receipt_id": "rcpt-old-rollback",
        "status": "SUCCESS",
        "executed_at": expired_time,
    }

    status = receipts_mod.audit_drill_receipt(
        drill_type="rollback",
        receipt_data=expired_drill_data,
        max_age_days=30.0,
        now_dt=now,
    )

    assert status.passed is False
    assert status.status == "EXPIRED"
    assert status.age_days is not None and status.age_days >= 45.0


def test_operational_receipts_cli_main(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        receipts_mod.main(["--help"])
    assert exc_info.value.code == 0

    rc_default = receipts_mod.main(["--json"])
    assert rc_default == 0

    # Receipts dir with custom valid drill
    rdir = tmp_path / "receipts"
    rdir.mkdir()
    now_iso = datetime.now(timezone.utc).isoformat()
    (rdir / "rollback-drill.json").write_text(
        json.dumps({"receipt_id": "r1", "status": "SUCCESS", "executed_at": now_iso}),
        encoding="utf-8",
    )
    (rdir / "takedown-drill.json").write_text(
        json.dumps({"receipt_id": "t1", "status": "SUCCESS", "executed_at": now_iso}),
        encoding="utf-8",
    )
    (rdir / "incident-drill.json").write_text(
        json.dumps({"receipt_id": "i1", "status": "SUCCESS", "executed_at": now_iso}),
        encoding="utf-8",
    )

    rc_custom = receipts_mod.main(["--receipts-dir", str(rdir), "--json"])
    assert rc_custom == 0
