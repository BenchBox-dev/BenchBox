"""Unit tests for publication reconciliation, independence matrix, and operational receipts.

These tools fail closed. The tests assert that missing, malformed, fabricated, or
collapsed inputs produce a nonzero result and never a reconciled/valid one, and
that real matching evidence reconciles.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[4]


def _load(name: str):
    path = ROOT / "scripts" / "publication" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


recon_mod = _load("reconciliation")
matrix_mod = _load("verify_independence_matrix")
receipts_mod = _load("check_operational_receipts")

NOW = datetime.now(timezone.utc)
NOW_ISO = NOW.isoformat()


def _full_live_receipt(generation: int = 5, timestamp: str | None = None) -> dict:
    return {
        "schema_version": "1.0",
        "receipt_id": "rcpt-live-0001",
        "target": "benchbox.dev",
        "generation": generation,
        "timestamp": timestamp or NOW_ISO,
        "manifest_digest": "sha256:" + "a" * 64,
        "develop_sha": "1111111111111111111111111111111111111111",
        "published_results_sha": "2222222222222222222222222222222222222222",
        "artifacts": {"site": {"digest": "d" * 64, "path": "/"}},
        "nonce": "nonce-xyz",
        "freshness_window": "24h",
        "attestor": "maintainer:joe",
        "signature_algorithm": "ed25519",
        "signature": "BASE64SIG==",
        "routes": [
            {"path": "/", "status_code": 200, "ok": True},
            {"path": "/results/", "status_code": 200, "ok": True},
            {"path": "/results/data/results.duckdb", "status_code": 200, "ok": True},
        ],
    }


def _sign_receipt(receipt: dict, private_key: Path) -> None:
    payload = private_key.parent / "receipt-payload.json"
    signature = private_key.parent / "receipt.sig"
    payload.write_bytes(recon_mod.canonical_live_receipt_payload(receipt))
    subprocess.run(
        [
            "openssl",
            "pkeyutl",
            "-sign",
            "-rawin",
            "-inkey",
            str(private_key),
            "-in",
            str(payload),
            "-out",
            str(signature),
        ],
        check=True,
    )
    receipt["signature"] = base64.b64encode(signature.read_bytes()).decode("ascii")


@pytest.fixture
def attestor_keypair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    private_key = tmp_path / "attestor-private.pem"
    public_key = tmp_path / "attestor-public.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private_key)], check=True)
    subprocess.run(["openssl", "pkey", "-in", str(private_key), "-pubout", "-out", str(public_key)], check=True)
    monkeypatch.setattr(recon_mod, "DEFAULT_ATTESTOR_PUBLIC_KEY", public_key)
    return private_key


def _distinct_states(generation: int = 5):
    desired = {
        "generation": generation,
        "develop_sha": "1111111111111111111111111111111111111111",
        "build_closure": {"lockfile_sha256": "lock", "workflow_sha": "wf"},
    }
    built = {
        "generation": generation,
        "develop_sha": "1111111111111111111111111111111111111111",
        "build_closure": {"lockfile_sha256": "lock", "workflow_sha": "wf"},
    }
    deployed = {
        "generation": generation,
        "source_commit": "1111111111111111111111111111111111111111",
        "status": "DEPLOYED",
    }
    observed = _full_live_receipt(generation=generation)
    return desired, built, deployed, observed


# ======================================================================
# RECONCILIATION (w1)
# ======================================================================


def test_reconcile_rejects_collapsed_states() -> None:
    desired = {"generation": 1}
    with pytest.raises(recon_mod.ReconciliationInputError):
        recon_mod.reconcile_states(desired=desired, built=desired, deployed=desired, observed=desired, now_dt=NOW)


def test_reconcile_live_incomplete_observed_receipt_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    class Resp:
        status = 200

        def read(self) -> bytes:
            return b"ok"

        def __enter__(self):
            return self

        def __exit__(self, *a) -> None:
            return None

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=15.0: Resp())

    desired, built, deployed, observed = _distinct_states()
    del observed["nonce"]
    del observed["signature"]
    report = recon_mod.reconcile_states(
        desired=desired, built=built, deployed=deployed, observed=observed, live=True, now_dt=NOW
    )
    assert report.reconciled is False
    assert any(d.drift_type == "RECEIPT_INCOMPLETE" for d in report.drifts)


def test_reconcile_happy_path_distinct_matching_states(attestor_keypair: Path) -> None:
    desired, built, deployed, observed = _distinct_states()
    _sign_receipt(observed, attestor_keypair)
    report = recon_mod.reconcile_states(desired=desired, built=built, deployed=deployed, observed=observed, now_dt=NOW)
    assert report.reconciled is True, [d.description for d in report.drifts]
    assert report.drift_count == 0


def test_reconcile_missing_observation_fails_closed() -> None:
    desired, built, deployed, _ = _distinct_states()
    report = recon_mod.reconcile_states(desired=desired, built=built, deployed=deployed, observed=None, now_dt=NOW)
    assert report.reconciled is False
    assert any(d.drift_type in ("MISSING_OBSERVATION", "STALE_RECEIPT") for d in report.drifts)


def test_reconcile_missing_built_and_deployed_fails_closed() -> None:
    desired, _, _, observed = _distinct_states()
    report = recon_mod.reconcile_states(desired=desired, built=None, deployed=None, observed=observed, now_dt=NOW)
    assert report.reconciled is False
    assert any("assembly (built) receipt" in d.description for d in report.drifts)
    assert any("deployment receipt" in d.description for d in report.drifts)


def test_reconcile_generation_drift_desired_vs_observed_when_deployed_missing() -> None:
    desired, built, _, _ = _distinct_states(generation=5)
    observed = _full_live_receipt(generation=1)
    report = recon_mod.reconcile_states(desired=desired, built=built, deployed=None, observed=observed, now_dt=NOW)
    assert report.reconciled is False
    gen_drifts = [d for d in report.drifts if d.drift_type == "GENERATION_DRIFT"]
    assert any(d.expected == 5 and d.actual == 1 for d in gen_drifts)


def test_reconcile_generation_type_normalization() -> None:
    desired, built, deployed, observed = _distinct_states(generation=5)
    deployed["generation"] = "5"
    observed["generation"] = "5"
    report = recon_mod.reconcile_states(desired=desired, built=built, deployed=deployed, observed=observed, now_dt=NOW)
    assert not any(d.drift_type == "GENERATION_DRIFT" for d in report.drifts)


def test_reconcile_missing_required_artifact_is_drift() -> None:
    desired, built, deployed, observed = _distinct_states()
    desired["artifacts"] = {
        "site": {"path": "/", "digest": "s" * 64},
        "explorer": {"path": "/results/", "digest": "e" * 64},
    }
    built["artifacts"] = {"site": {"path": "/", "digest": "s" * 64}}  # explorer never built
    report = recon_mod.reconcile_states(desired=desired, built=built, deployed=deployed, observed=observed, now_dt=NOW)
    assert report.reconciled is False
    assert any(d.drift_type == "ARTIFACT_DRIFT" and "/results/" in d.description for d in report.drifts)


def test_reconcile_incomplete_receipt_fields() -> None:
    desired, built, deployed, observed = _distinct_states()
    del observed["nonce"]
    del observed["signature"]
    del observed["attestor"]
    report = recon_mod.reconcile_states(desired=desired, built=built, deployed=deployed, observed=observed, now_dt=NOW)
    assert report.reconciled is False
    incomplete = [d for d in report.drifts if d.drift_type == "RECEIPT_INCOMPLETE"]
    assert len(incomplete) >= 3


def test_reconcile_partial_route_success_fails_closed() -> None:
    desired, built, deployed, observed = _distinct_states()
    observed["routes"] = [{"path": "/", "status_code": 200, "ok": True}]  # missing 2 required routes
    report = recon_mod.reconcile_states(desired=desired, built=built, deployed=deployed, observed=observed, now_dt=NOW)
    assert report.reconciled is False
    assert any("Required public route" in d.description for d in report.drifts)


def test_reconcile_probe_without_status_is_drift() -> None:
    desired, built, deployed, observed = _distinct_states()
    observed["routes"] = [
        {"path": "/"},
        {"path": "/results/"},
        {"path": "/results/data/results.duckdb"},
    ]
    report = recon_mod.reconcile_states(desired=desired, built=built, deployed=deployed, observed=observed, now_dt=NOW)
    assert report.reconciled is False
    assert any("omits both 'status_code'" in d.description for d in report.drifts)


def test_reconcile_stale_receipt() -> None:
    desired, built, deployed, _ = _distinct_states()
    observed = _full_live_receipt(timestamp=(NOW - timedelta(hours=36)).isoformat())
    report = recon_mod.reconcile_states(
        desired=desired, built=built, deployed=deployed, observed=observed, max_age_hours=24.0, now_dt=NOW
    )
    assert report.reconciled is False
    assert any(d.drift_type == "STALE_RECEIPT" and "stale" in d.description for d in report.drifts)
    assert report.receipt_age_hours is not None and report.receipt_age_hours >= 36.0


def test_reconcile_future_dated_receipt_fails_closed() -> None:
    desired, built, deployed, _ = _distinct_states()
    observed = _full_live_receipt(timestamp=(NOW + timedelta(hours=5)).isoformat())
    report = recon_mod.reconcile_states(desired=desired, built=built, deployed=deployed, observed=observed, now_dt=NOW)
    assert report.reconciled is False
    assert any(d.drift_type == "STALE_RECEIPT" and "future" in d.description for d in report.drifts)


def test_reconcile_undated_receipt_fails_closed() -> None:
    desired, built, deployed, observed = _distinct_states()
    del observed["timestamp"]
    report = recon_mod.reconcile_states(desired=desired, built=built, deployed=deployed, observed=observed, now_dt=NOW)
    assert report.reconciled is False
    assert any(d.drift_type == "STALE_RECEIPT" for d in report.drifts)


def test_reconcile_live_probe_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib

    content = b"live database bytes"
    db_sha = hashlib.sha256(content).hexdigest()

    class Resp:
        status = 200

        def read(self) -> bytes:
            return content

        def __enter__(self):
            return self

        def __exit__(self, *a) -> None:
            return None

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=15.0: Resp())

    desired = {"generation": 1, "live_database": {"sha256": db_sha}}
    built = {"generation": 1, "live_database": {"sha256": db_sha}, "kind": "assembly"}
    deployed = {"generation": 1, "kind": "deploy"}
    report = recon_mod.reconcile_states(
        desired=desired, built=built, deployed=deployed, observed=None, live=True, now_dt=NOW
    )
    assert len(report.probes) == 3
    assert all(p.ok for p in report.probes)


def test_reconciliation_cli_requires_inputs(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        recon_mod.main(["--help"])
    assert exc.value.code == 0

    # No arguments at all -> config error, never 0.
    assert recon_mod.main([]) == 2
    assert recon_mod.main(["--json"]) == 2

    manifest = tmp_path / "desired-manifest.json"
    manifest.write_text(json.dumps(_distinct_states()[0]), encoding="utf-8")

    # Manifest but no receipts dir -> 2.
    assert recon_mod.main(["--manifest", str(manifest)]) == 2

    # Receipts dir missing files -> 2.
    rdir = tmp_path / "reconciliation"
    rdir.mkdir()
    assert recon_mod.main(["--manifest", str(manifest), "--receipts-dir", str(rdir)]) == 2


def test_reconciliation_cli_full_evidence_reconciles(tmp_path: Path, attestor_keypair: Path) -> None:
    desired, built, deployed, observed = _distinct_states()
    _sign_receipt(observed, attestor_keypair)
    manifest = tmp_path / "desired-manifest.json"
    manifest.write_text(json.dumps(desired), encoding="utf-8")
    rdir = tmp_path / "reconciliation"
    rdir.mkdir()
    (rdir / recon_mod.ASSEMBLY_RECEIPT_NAME).write_text(json.dumps(built), encoding="utf-8")
    (rdir / recon_mod.DEPLOYMENT_RECEIPT_NAME).write_text(json.dumps(deployed), encoding="utf-8")
    (rdir / recon_mod.LIVE_RECEIPT_NAME).write_text(json.dumps(observed), encoding="utf-8")

    assert recon_mod.main(["--manifest", str(manifest), "--receipts-dir", str(rdir), "--json"]) == 0


def test_reconcile_receipt_signature_fails_closed_for_missing_empty_or_wrong_signature(
    attestor_keypair: Path,
) -> None:
    for signature in (None, "", "Zm9yZ2Vk"):
        desired, built, deployed, observed = _distinct_states()
        if signature is None:
            del observed["signature"]
        else:
            observed["signature"] = signature
        report = recon_mod.reconcile_states(
            desired=desired, built=built, deployed=deployed, observed=observed, now_dt=NOW
        )
        assert report.reconciled is False
        assert any(d.drift_type == "RECEIPT_SIGNATURE_INVALID" for d in report.drifts)


def test_reconcile_receipt_signature_accepts_valid_attestor_signature(attestor_keypair: Path) -> None:
    desired, built, deployed, observed = _distinct_states()
    _sign_receipt(observed, attestor_keypair)
    report = recon_mod.reconcile_states(desired=desired, built=built, deployed=deployed, observed=observed, now_dt=NOW)
    assert report.reconciled is True, [d.description for d in report.drifts]


def test_verify_live_receipt_signature_handles_missing_openssl(
    attestor_keypair: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    desired, built, deployed, observed = _distinct_states()
    _sign_receipt(observed, attestor_keypair)

    def _mock_subprocess_run(*args, **kwargs):
        raise FileNotFoundError("No such file or directory: 'openssl'")

    monkeypatch.setattr(subprocess, "run", _mock_subprocess_run)
    valid, reason = recon_mod.verify_live_receipt_signature(observed)
    assert valid is False
    assert "openssl binary execution failed" in reason
    assert "No such file or directory: 'openssl'" in reason

    report = recon_mod.reconcile_states(desired=desired, built=built, deployed=deployed, observed=observed, now_dt=NOW)
    assert report.reconciled is False
    assert any(
        d.drift_type == "RECEIPT_SIGNATURE_INVALID" and "openssl binary execution failed" in d.description
        for d in report.drifts
    )


# ======================================================================
# INDEPENDENCE MATRIX (w2)
# ======================================================================

_BASE = {"package": "p1", "site": "s1", "explorer": "e1", "corpus": "c1"}


def _single_lane_transitions() -> list[dict]:
    mut = {"package": "p2", "site": "s2", "explorer": "e2", "corpus": "c2"}
    out = []
    for lane in matrix_mod.LANES:
        after = dict(_BASE)
        after[lane] = mut[lane]
        out.append(
            {
                "transition_id": f"t_{lane}",
                "target_lane": lane,
                "before_hashes": dict(_BASE),
                "after_hashes": after,
                "evidence": {
                    "workflow_run_id": "123",
                    "event_id": f"event-{lane}",
                    "artifact_name": f"lane-{lane}",
                    "artifact_digest": "a" * 64,
                },
            }
        )
    return out


def test_matrix_no_input_raises() -> None:
    with pytest.raises(matrix_mod.MatrixInputError):
        matrix_mod.verify_independence()


def test_matrix_detects_lane_coupling() -> None:
    coupled_after = {"package": "p1", "site": "s2", "explorer": "e2", "corpus": "c1"}
    trans = matrix_mod.verify_transition_independence(
        transition_id="coupled", target_lane="site", before_hashes=_BASE, after_hashes=coupled_after
    )
    assert trans.valid is False
    report = matrix_mod.verify_independence(transitions=[trans])
    assert report.valid is False


def test_matrix_detects_unmutated_target_lane() -> None:
    trans = matrix_mod.verify_transition_independence(
        transition_id="nochange", target_lane="package", before_hashes=_BASE, after_hashes=dict(_BASE)
    )
    assert trans.valid is False
    assert any("did not change" in v for v in trans.violations)


def test_matrix_loads_recorded_transitions(tmp_path: Path) -> None:
    (tmp_path / matrix_mod.MATRIX_FILE_NAME).write_text(
        json.dumps({"transitions": _single_lane_transitions()}), encoding="utf-8"
    )
    report = matrix_mod.verify_independence(receipts_dir=tmp_path)
    assert report.valid is True
    assert report.transitions_checked == 4


def test_matrix_malformed_record_is_config_error(tmp_path: Path) -> None:
    (tmp_path / matrix_mod.MATRIX_FILE_NAME).write_text("{ not json", encoding="utf-8")
    with pytest.raises(matrix_mod.MatrixInputError):
        matrix_mod.verify_independence(receipts_dir=tmp_path)


def test_matrix_cli(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        matrix_mod.main(["--help"])
    assert exc.value.code == 0

    assert matrix_mod.main([]) == 2
    assert matrix_mod.main(["--json"]) == 2
    assert matrix_mod.main(["--receipts-dir", str(tmp_path / "nope")]) == 2

    empty = tmp_path / "independence"
    empty.mkdir()
    assert matrix_mod.main(["--receipts-dir", str(empty)]) == 2  # no transition record

    (empty / matrix_mod.MATRIX_FILE_NAME).write_text(
        json.dumps({"transitions": _single_lane_transitions()}), encoding="utf-8"
    )
    assert matrix_mod.main(["--receipts-dir", str(empty), "--json"]) == 0


# ======================================================================
# OPERATIONAL RECEIPTS (w2)
# ======================================================================


def _valid_operational_dir(tmp_path: Path) -> Path:
    d = tmp_path / "operational"
    d.mkdir()
    for name, rid in (
        (receipts_mod.ROLLBACK_DRILL_FILE, "r1"),
        (receipts_mod.TAKEDOWN_DRILL_FILE, "t1"),
        (receipts_mod.INCIDENT_DRILL_FILE, "i1"),
    ):
        (d / name).write_text(
            json.dumps(
                {
                    "receipt_id": rid,
                    "status": "SUCCESS",
                    "executed_at": NOW_ISO,
                    "evidence": {
                        "workflow_run_id": "123",
                        "event_id": rid,
                        "artifact_name": "pages",
                        "artifact_digest": "a" * 64,
                    },
                }
            ),
            encoding="utf-8",
        )
    (d / receipts_mod.CAPACITY_FILE).write_text(
        json.dumps({"total_size_bytes": 50_000_000, "largest_file_bytes": 10_000_000, "measured": True}),
        encoding="utf-8",
    )
    (d / receipts_mod.RETENTION_FILE).write_text(
        json.dumps(
            {
                "transient_retention_days": 7,
                "receipt_retention_days": 30,
                "rollback_checkpoint_retention_days": 90,
                "source": "publication-canaries.yml retention-days + contract Retention and audit",
            }
        ),
        encoding="utf-8",
    )
    return d


def test_operational_requires_receipts_dir() -> None:
    with pytest.raises(receipts_mod.ReceiptsConfigError):
        receipts_mod.audit_operational_receipts(receipts_dir=None)


def test_operational_missing_drill_is_missing_violation(tmp_path: Path) -> None:
    d = _valid_operational_dir(tmp_path)
    (d / receipts_mod.ROLLBACK_DRILL_FILE).unlink()
    report = receipts_mod.audit_operational_receipts(receipts_dir=d, now_dt=NOW)
    assert report.valid is False
    assert report.drills["rollback"].status == "MISSING"
    assert report.drills["rollback"].passed is False


def test_operational_missing_capacity_and_retention_fail_closed(tmp_path: Path) -> None:
    d = tmp_path / "operational"
    d.mkdir()
    for name in (receipts_mod.ROLLBACK_DRILL_FILE, receipts_mod.TAKEDOWN_DRILL_FILE, receipts_mod.INCIDENT_DRILL_FILE):
        (d / name).write_text(
            json.dumps({"receipt_id": "x", "status": "SUCCESS", "executed_at": NOW_ISO}), encoding="utf-8"
        )
    report = receipts_mod.audit_operational_receipts(receipts_dir=d, now_dt=NOW)
    assert report.valid is False
    assert any("capacity evidence" in v.lower() or "no capacity" in v.lower() for v in report.violations)
    assert any("retention policy" in v.lower() for v in report.violations)


def test_operational_retention_without_source_fails() -> None:
    audit = receipts_mod.audit_retention(transient_days=7, receipt_days=30, rollback_days=90, source="")
    assert audit.passed is False
    assert any("source" in v for v in audit.violations)


def test_operational_capacity_at_limit_rejected() -> None:
    audit = receipts_mod.audit_capacity(total_bytes=receipts_mod.MAX_TOTAL_PAGES_BYTES, largest_file_bytes=1)
    assert audit.passed is False
    audit2 = receipts_mod.audit_capacity(total_bytes=1, largest_file_bytes=receipts_mod.MAX_INDIVIDUAL_FILE_BYTES)
    assert audit2.passed is False


def test_operational_status_missing_is_invalid() -> None:
    status = receipts_mod.audit_drill_receipt("rollback", {"receipt_id": "r", "executed_at": NOW_ISO}, now_dt=NOW)
    assert status.passed is False
    assert status.status == "INVALID"


def test_operational_future_dated_drill_is_invalid() -> None:
    future = (NOW + timedelta(days=2)).isoformat()
    status = receipts_mod.audit_drill_receipt(
        "rollback", {"receipt_id": "r", "status": "SUCCESS", "executed_at": future}, now_dt=NOW
    )
    assert status.passed is False
    assert status.status == "INVALID"


def test_operational_expired_drill() -> None:
    old = (NOW - timedelta(days=45)).isoformat()
    status = receipts_mod.audit_drill_receipt(
        "rollback", {"receipt_id": "r", "status": "SUCCESS", "executed_at": old}, max_age_days=30.0, now_dt=NOW
    )
    assert status.passed is False
    assert status.status == "EXPIRED"


def test_operational_pages_dir_measurement(tmp_path: Path) -> None:
    d = _valid_operational_dir(tmp_path)
    (d / receipts_mod.CAPACITY_FILE).unlink()
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "index.html").write_text("x" * 1000, encoding="utf-8")
    report = receipts_mod.audit_operational_receipts(receipts_dir=d, pages_dir=pages, now_dt=NOW)
    assert report.capacity.measured is True
    assert report.capacity.total_size_bytes == 1000
    assert report.valid is True


def test_operational_cli(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        receipts_mod.main(["--help"])
    assert exc.value.code == 0

    assert receipts_mod.main([]) == 2
    assert receipts_mod.main(["--json"]) == 2
    assert receipts_mod.main(["--receipts-dir", str(tmp_path / "missing")]) == 2

    d = _valid_operational_dir(tmp_path)
    assert receipts_mod.main(["--receipts-dir", str(d), "--json"]) == 0

    (d / receipts_mod.TAKEDOWN_DRILL_FILE).write_text("{bad", encoding="utf-8")
    assert receipts_mod.main(["--receipts-dir", str(d), "--json"]) == 2
