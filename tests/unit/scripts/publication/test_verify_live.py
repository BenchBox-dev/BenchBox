"""Unit tests for live publication verification and receipt checking."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

SCRIPT = Path(__file__).parents[4] / "scripts/publication/verify_live.py"
SPEC = importlib.util.spec_from_file_location("verify_live", SCRIPT)
assert SPEC and SPEC.loader
verify_live_mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verify_live_mod
SPEC.loader.exec_module(verify_live_mod)


class MockHTTPResponse:
    def __init__(
        self,
        body: bytes,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ):
        self._body = io.BytesIO(body)
        self.status = status
        self.headers = headers or {"content-type": "application/octet-stream", "etag": '"test-etag"'}

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def __enter__(self) -> MockHTTPResponse:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass


def test_extract_expected_checksums_various_formats() -> None:
    # 1. Baseline format
    baseline_fmt = {
        "live_database": {
            "sha256": "aaaa111122223333444455556666777788889999000011112222333344445555",
            "url": "https://benchbox.dev/results/data/results.duckdb",
        }
    }
    extracted = verify_live_mod.extract_expected_checksums(baseline_fmt)
    assert (
        extracted["/results/data/results.duckdb"] == "aaaa111122223333444455556666777788889999000011112222333344445555"
    )

    # 2. Receipt format with checksums mapping
    receipt_fmt = {
        "checksums": {
            "/results/data/results.duckdb": "bbbb",
            "index.html": "cccc",
        }
    }
    extracted2 = verify_live_mod.extract_expected_checksums(receipt_fmt)
    assert extracted2["/results/data/results.duckdb"] == "bbbb"
    assert extracted2["/index.html"] == "cccc"

    # 3. Direct database_sha256 format
    direct_fmt = {"database_sha256": "dddd"}
    extracted3 = verify_live_mod.extract_expected_checksums(direct_fmt)
    assert extracted3["/results/data/results.duckdb"] == "dddd"

    # 4. Artifact list format
    artifact_fmt = {
        "artifacts": [
            {"path": "/results/data/results.duckdb", "sha256": "eeee"},
            {"path": "explorer.js", "sha256": "ffff"},
        ]
    }
    extracted4 = verify_live_mod.extract_expected_checksums(artifact_fmt)
    assert extracted4["/results/data/results.duckdb"] == "eeee"
    assert extracted4["/explorer.js"] == "ffff"


def test_probe_endpoint_success(monkeypatch: pytest.MonkeyPatch) -> None:
    content = b"DuckDB database content payload"
    import hashlib

    expected_sha = hashlib.sha256(content).hexdigest()

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=30: MockHTTPResponse(content, status=200, headers={"etag": "abc"}),
    )

    probe = verify_live_mod.probe_endpoint("https://benchbox.dev", "/results/data/results.duckdb")
    assert probe.ok is True
    assert probe.status_code == 200
    assert probe.sha256 == expected_sha
    assert probe.content_length == len(content)
    assert probe.etag == "abc"
    assert probe.latency_ms >= 0


def test_probe_endpoint_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req, timeout=30):
        raise urllib.error.HTTPError(
            url="https://benchbox.dev/bad",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=None,
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    probe = verify_live_mod.probe_endpoint("https://benchbox.dev", "/bad")
    assert probe.ok is False
    assert probe.status_code == 404
    assert "HTTP 404" in probe.error


def test_probe_endpoint_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req, timeout=30):
        raise urllib.error.URLError(reason="Connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    probe = verify_live_mod.probe_endpoint("https://benchbox.dev", "/")
    assert probe.ok is False
    assert probe.status_code == 0
    assert "Connection refused" in probe.error


def test_verify_live_passes_matching_checksums(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    content = b"sample content"
    import hashlib

    sha = hashlib.sha256(content).hexdigest()

    manifest_file = tmp_path / "receipt.json"
    manifest_file.write_text(json.dumps({"checksums": {"/results/data/results.duckdb": sha}}))

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=30: MockHTTPResponse(content, status=200),
    )

    report = verify_live_mod.verify_live(
        base_url="https://benchbox.dev",
        manifest_path=manifest_file,
        require_receipt=True,
        expect_noop=True,
    )

    assert report.ok is True
    assert len(report.errors) == 0
    assert "/results/data/results.duckdb" in report.matched_checksums


def test_verify_live_fails_mismatched_checksum(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    live_content = b"live mutated content"
    manifest_file = tmp_path / "receipt.json"
    manifest_file.write_text(json.dumps({"checksums": {"/results/data/results.duckdb": "expected_old_sha"}}))

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=30: MockHTTPResponse(live_content, status=200),
    )

    report = verify_live_mod.verify_live(
        base_url="https://benchbox.dev",
        manifest_path=manifest_file,
        require_receipt=True,
        expect_noop=False,
    )

    assert report.ok is False
    assert "/results/data/results.duckdb" in report.mismatched_checksums
    assert any("Receipt checksum mismatch" in err for err in report.errors)


def test_verify_live_expect_noop_fails_on_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    live_content = b"live mutated content"
    manifest_file = tmp_path / "baseline.json"
    manifest_file.write_text(json.dumps({"checksums": {"/results/data/results.duckdb": "baseline_sha"}}))

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=30: MockHTTPResponse(live_content, status=200),
    )

    report = verify_live_mod.verify_live(
        base_url="https://benchbox.dev",
        manifest_path=manifest_file,
        require_receipt=True,
        expect_noop=True,
    )

    assert report.ok is False
    assert any("Unexpected mutation detected during no-op verification" in err for err in report.errors)


def test_noop_comparison_uses_frozen_baseline_scope() -> None:
    candidate = {
        "/": "newly-attested-root",
        "/results/": "newly-attested-explorer",
        "/results/data/results.duckdb": "stable-database",
    }
    baseline = {"/results/data/results.duckdb": "stable-database"}

    matched, mismatched, errors = verify_live_mod.compare_candidate_against_baseline(
        candidate, baseline, expect_noop=True
    )

    assert matched == baseline
    assert mismatched == {}
    assert errors == []


def test_verify_live_missing_manifest_when_required() -> None:
    report = verify_live_mod.verify_live(
        base_url="https://benchbox.dev",
        manifest_path=None,
        require_receipt=True,
    )
    assert report.ok is False
    assert any("Receipt verification was required" in err for err in report.errors)


def test_verify_live_main_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    content = b"sample content"
    import hashlib

    sha = hashlib.sha256(content).hexdigest()

    manifest_file = tmp_path / "receipt.json"
    manifest_file.write_text(json.dumps({"checksums": {"/results/data/results.duckdb": sha}}))

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=30: MockHTTPResponse(content, status=200),
    )

    rc = verify_live_mod.main(
        [
            "--base-url",
            "https://benchbox.dev",
            "--manifest",
            str(manifest_file),
            "--require-receipt",
            "--expect-noop",
            "--json",
        ]
    )
    assert rc == 0


def test_pre_deploy_candidate_matching_baseline(tmp_path: Path) -> None:
    sha = "1111222233334444555566667777888899990000111122223333444455556666"
    cand_file = tmp_path / "candidate.json"
    cand_file.write_text(json.dumps({"checksums": {"/results/data/results.duckdb": sha}}))

    base_file = tmp_path / "baseline.json"
    base_file.write_text(json.dumps({"live_database": {"sha256": sha}}))

    report = verify_live_mod.verify_live(
        candidate_manifest=cand_file,
        baseline_manifest=base_file,
        expect_noop=True,
        require_receipt=True,
        skip_live_probes=True,
    )

    assert report.ok is True
    assert report.pre_deploy_check_performed is True
    assert len(report.errors) == 0
    assert "/results/data/results.duckdb" in report.matched_checksums


def test_pre_deploy_candidate_differs_fails_on_expect_noop(tmp_path: Path) -> None:
    cand_file = tmp_path / "candidate.json"
    cand_file.write_text(json.dumps({"checksums": {"/results/data/results.duckdb": "new_candidate_sha"}}))

    base_file = tmp_path / "baseline.json"
    base_file.write_text(json.dumps({"live_database": {"sha256": "old_baseline_sha"}}))

    report = verify_live_mod.verify_live(
        candidate_manifest=cand_file,
        baseline_manifest=base_file,
        expect_noop=True,
        require_receipt=True,
        skip_live_probes=True,
    )

    assert report.ok is False
    assert report.pre_deploy_check_performed is True
    assert any("Pre-deploy no-op check failed" in err for err in report.errors)


def test_pre_deploy_cli_main(tmp_path: Path) -> None:
    sha = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
    cand_file = tmp_path / "candidate.json"
    cand_file.write_text(json.dumps({"checksums": {"/results/data/results.duckdb": sha}}))

    base_file = tmp_path / "baseline.json"
    base_file.write_text(json.dumps({"live_database": {"sha256": sha}}))

    rc = verify_live_mod.main(
        [
            "--candidate-manifest",
            str(cand_file),
            "--baseline-manifest",
            str(base_file),
            "--pre-deploy",
            "--expect-noop",
            "--require-receipt",
        ]
    )
    assert rc == 0


def test_pre_deploy_without_manifests_fails() -> None:
    rc = verify_live_mod.main(["--pre-deploy"])
    assert rc != 0
    report = verify_live_mod.verify_live(pre_deploy=True, skip_live_probes=True)
    assert report.ok is False
    assert report.pre_deploy_check_performed is False
    assert report.live_probes_performed is False
    assert any("Pre-deploy check requires both a candidate and a baseline" in err for err in report.errors)


def test_defect_d3_availability_runs_without_evidence_acquisition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Falsifying test for Defect D3:

    Delete/expire evidence while service is up:
    - availability remains measured and OK
    - content and certification are UNAVAILABLE
    - certification fails closed (certified is False)
    """
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=30: MockHTTPResponse(b"OK", status=200),
    )

    # 1. Run live probe without any evidence or receipts
    probe_report = verify_live_mod.verify_live(
        base_url="https://benchbox.dev",
        endpoints=["/", "/docs/", "/docs/api.html", "/results/", "/results/data/results.duckdb"],
    )
    assert probe_report.ok is True
    assert probe_report.live_probes_performed is True
    assert len(probe_report.probes) == 5
    assert all(p.ok for p in probe_report.probes)

    # 2. Write probe report to diagnostic-reports directory (no evidence/receipts exist)
    reports_dir = tmp_path / "diagnostic-reports"
    reports_dir.mkdir()
    (reports_dir / "availability-report.json").write_text(json.dumps(probe_report.to_dict()))

    # 3. Evaluate 5-dimension operational certification
    cert = verify_live_mod.evaluate_certification_reports(reports_dir)

    # Availability must be measured as PASS
    assert cert.dimensions[verify_live_mod.DIMENSION_AVAILABILITY].status == verify_live_mod.STATUS_PASS

    # Evidence is absent/expired: content identity, reconciliation, independence, and operational recovery are UNAVAILABLE
    assert cert.dimensions[verify_live_mod.DIMENSION_CONTENT_IDENTITY].status == verify_live_mod.STATUS_UNAVAILABLE
    assert cert.dimensions[verify_live_mod.DIMENSION_RECONCILIATION].status == verify_live_mod.STATUS_UNAVAILABLE
    assert cert.dimensions[verify_live_mod.DIMENSION_INDEPENDENCE].status == verify_live_mod.STATUS_UNAVAILABLE
    assert cert.dimensions[verify_live_mod.DIMENSION_OPERATIONAL_RECOVERY].status == verify_live_mod.STATUS_UNAVAILABLE

    # Overall certification MUST fail closed (not certified)
    assert cert.certified is False

    # CLI exits 1
    rc = verify_live_mod.main(["--certify-reports-dir", str(reports_dir)])
    assert rc == 1


def test_defect_d3_return_503_fails_availability(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Falsifying test for Defect D3:

    When endpoints return 503 while receipts are valid, availability fails immediately.
    """

    def mock_503(req, timeout=30):
        raise urllib.error.HTTPError(
            url=req.get_full_url(),
            code=503,
            msg="Service Unavailable",
            hdrs={},
            fp=io.BytesIO(b"Service Unavailable"),
        )

    monkeypatch.setattr(urllib.request, "urlopen", mock_503)

    probe_report = verify_live_mod.verify_live(
        base_url="https://benchbox.dev",
        endpoints=["/"],
    )
    assert probe_report.ok is False
    assert probe_report.probes[0].status_code == 503

    reports_dir = tmp_path / "diagnostic-reports"
    reports_dir.mkdir()
    (reports_dir / "availability-report.json").write_text(json.dumps(probe_report.to_dict()))

    # Even if reconciliation report was valid
    (reports_dir / "reconciliation-report.json").write_text(json.dumps({"reconciled": True, "violations": []}))

    cert = verify_live_mod.evaluate_certification_reports(reports_dir)
    assert cert.dimensions[verify_live_mod.DIMENSION_AVAILABILITY].status == verify_live_mod.STATUS_FAIL
    assert cert.certified is False


def test_evaluate_certification_all_dimensions_pass(tmp_path: Path) -> None:
    reports_dir = tmp_path / "diagnostic-reports"
    reports_dir.mkdir()

    avail_data = {
        "ok": True,
        "probes": [{"path": "/", "ok": True, "status_code": 200}],
        "matched_checksums": {"/results/data/results.duckdb": "abc"},
        "mismatched_checksums": {},
        "errors": [],
    }
    (reports_dir / "availability-report.json").write_text(json.dumps(avail_data))
    (reports_dir / "reconciliation-report.json").write_text(json.dumps({"reconciled": True, "violations": []}))
    (reports_dir / "independence-matrix-report.json").write_text(
        json.dumps({"valid": True, "violations": [], "transitions_checked": 4})
    )
    (reports_dir / "operational-receipts-report.json").write_text(
        json.dumps({"passed": True, "all_violations": [], "drills": {"rollback": {"passed": True}}})
    )

    cert = verify_live_mod.evaluate_certification_reports(reports_dir)
    assert cert.certified is True
    assert all(d.status == verify_live_mod.STATUS_PASS for d in cert.dimensions.values())

    rc = verify_live_mod.main(["--certify-reports-dir", str(reports_dir)])
    assert rc == 0
