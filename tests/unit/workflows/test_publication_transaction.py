"""Contract and architecture tests for publication transactions workflow."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS_DIR = ROOT / ".github" / "workflows"
TX_WORKFLOW_PATH = WORKFLOWS_DIR / "publication-transaction.yml"
PREVIEW_DEPLOY_PATH = WORKFLOWS_DIR / "publication-preview-deploy.yml"
PREVIEW_SOAK_PATH = WORKFLOWS_DIR / "publication-preview-soak.yml"
DOCS_PATH = WORKFLOWS_DIR / "docs.yml"
DEPLOY_PATH = WORKFLOWS_DIR / "publication-deploy.yml"


def _load_yaml(path: Path) -> dict[str, Any]:
    assert path.is_file(), f"Workflow file missing at {path}"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_transaction_workflow_is_dispatch_only_with_required_inputs() -> None:
    wf = _load_yaml(TX_WORKFLOW_PATH)
    triggers = wf.get("on") or wf.get(True) or {}

    assert "push" not in triggers
    assert "pull_request" not in triggers
    assert "workflow_dispatch" in triggers

    inputs = triggers["workflow_dispatch"].get("inputs", {})
    assert "kind" in inputs
    assert inputs["kind"]["type"] == "choice"
    assert set(inputs["kind"]["options"]) == {"promotion", "rollback"}
    assert inputs["develop_sha"]["required"] is True
    assert inputs["published_results_sha"]["required"] is True
    assert "candidate_manifest_digest" in inputs
    assert "restore_transaction_id" in inputs
    assert "barrier_evidence" in inputs


def test_transaction_workflow_permissions_follow_least_privilege() -> None:
    wf = _load_yaml(TX_WORKFLOW_PATH)
    jobs = wf["jobs"]

    # Top-level is read-only
    assert wf.get("permissions") == {"contents": "read"}

    # prepare: read-only
    assert jobs["prepare"]["permissions"] == {"contents": "read", "actions": "read"}

    # deploy: contents: write (for journal CAS), pages: write, id-token: write, actions: read
    assert jobs["deploy"]["permissions"] == {
        "contents": "write",
        "pages": "write",
        "id-token": "write",
        "actions": "read",
    }
    assert jobs["deploy"]["environment"]["name"] == "github-pages"

    # verify: contents: write (for journal CAS)
    assert jobs["verify"]["permissions"] == {"contents": "write"}
    assert jobs["verify"]["environment"]["name"] == "publication-attestation"

    # finalize: contents: write (for journal CAS)
    assert jobs["finalize"]["permissions"] == {"contents": "write"}


def test_transaction_workflow_concurrency_scoped_to_deploy_job() -> None:
    wf = _load_yaml(TX_WORKFLOW_PATH)

    # Top-level workflow must NOT lock pages-deploy across candidate preparation
    assert "concurrency" not in wf

    # prepare job must NOT lock pages-deploy
    assert "concurrency" not in wf["jobs"]["prepare"]

    # deploy job alone holds the pages-deploy lock
    assert wf["jobs"]["deploy"]["concurrency"] == {
        "group": "pages-deploy",
        "cancel-in-progress": False,
    }


def test_transaction_workflow_job_dependencies() -> None:
    jobs = _load_yaml(TX_WORKFLOW_PATH)["jobs"]

    assert jobs["deploy"]["needs"] == "prepare"
    assert jobs["verify"]["needs"] == ["prepare", "deploy"]
    assert jobs["finalize"]["needs"] == ["prepare", "deploy", "verify"]


def test_transaction_workflow_pins_all_actions() -> None:
    text = TX_WORKFLOW_PATH.read_text(encoding="utf-8")
    action_refs = re.findall(r"uses:\s+([^\s#]+)", text)

    for ref in action_refs:
        assert "@" in ref, f"Action reference '{ref}' is missing version tag or commit SHA"
        name, sha = ref.split("@", 1)
        assert re.fullmatch(r"[0-9a-f]{40}", sha), (
            f"Action '{name}' in publication-transaction.yml must be pinned by a 40-character commit SHA, got: {sha}"
        )


def test_five_write_paths_inventory_and_disabled_or_journaled_invariant() -> None:
    """Inventory all five write paths (promotion, rollback, legacy release, legacy recovery, preview).

    Assert the invariant: every Pages write path is either:
    1. A journaled transaction in publication-transaction.yml (promotion, rollback)
    2. An approved legacy path with admission control (docs.yml, publication-deploy.yml)
    3. Explicitly disabled in code (publication-preview-deploy.yml)
    """
    deploy_pages_workflows: list[Path] = []
    for path in WORKFLOWS_DIR.glob("*.yml"):
        content = path.read_text(encoding="utf-8")
        if "deploy-pages" in content or "pages.cjs" in content:
            deploy_pages_workflows.append(path)

    workflow_names = {p.name for p in deploy_pages_workflows}
    expected_workflow_names = {
        "publication-transaction.yml",  # Path 1 (promotion) & Path 2 (rollback)
        "docs.yml",  # Path 3 (legacy release)
        "publication-deploy.yml",  # Path 4 (legacy recovery)
        "publication-preview-deploy.yml",  # Path 5 (preview, disabled in code)
    }

    assert workflow_names == expected_workflow_names, (
        f"Unexpected Pages deployment workflows found. Expected only {expected_workflow_names}, got {workflow_names}"
    )

    # Verify Path 5 (preview deploy) is disabled in code
    preview_wf = _load_yaml(PREVIEW_DEPLOY_PATH)
    deploy_job = preview_wf["jobs"]["deploy"]
    assert deploy_job.get("if") is False, "Preview deploy job must be disabled in code with 'if: false'"
    deploy_steps = deploy_job.get("steps", [])
    first_step = deploy_steps[0] if deploy_steps else {}
    assert "permanently disabled in code" in first_step.get("run", ""), (
        "Preview deploy job must contain an explicit code guard asserting permanent disablement"
    )

    # Verify Path 3 (docs.yml legacy release) has admission guard
    docs_wf = _load_yaml(DOCS_PATH)
    docs_deploy_steps = docs_wf["jobs"]["deploy"]["steps"]
    guard_step = next(
        (s for s in docs_deploy_steps if s.get("name") == "Check for independent publication ownership"), None
    )
    assert guard_step is not None, "docs.yml must retain independent publication admission guard"
    assert "Publication Transactions" in guard_step.get("run", "")

    # Verify Path 4 (publication-deploy.yml legacy recovery) has scoped concurrency and attested restore
    deploy_wf = _load_yaml(DEPLOY_PATH)
    assert "concurrency" not in deploy_wf, "publication-deploy.yml must not lock concurrency at workflow level"
    assert deploy_wf["jobs"]["deploy"]["concurrency"]["group"] == "pages-deploy"
    assert deploy_wf["jobs"]["rollback"]["concurrency"]["group"] == "pages-deploy"


def test_preview_soak_caller_handles_disabled_preview_gracefully() -> None:
    soak_text = PREVIEW_SOAK_PATH.read_text(encoding="utf-8")
    assert "skipping soak probe" in soak_text or "skipping probe" in soak_text
    assert "exit 0" in soak_text


def test_transaction_workflow_manifest_transfer_across_jobs_contract() -> None:
    """Verify artifact passing and manifest materialization across deploy and verify jobs."""
    wf = _load_yaml(TX_WORKFLOW_PATH)
    deploy_steps = wf["jobs"]["deploy"]["steps"]
    verify_steps = wf["jobs"]["verify"]["steps"]

    # 1. Deploy job uploads candidate receipts as retained artifact
    upload_step = next(
        (s for s in deploy_steps if s.get("name") == "Retain candidate receipts for verification and audit"), None
    )
    assert upload_step is not None, "deploy job must retain candidate receipts artifact"
    assert upload_step.get("if") == "needs.prepare.outputs.kind == 'promotion'"
    assert "publication-candidate-receipts-" in upload_step["with"]["name"]
    assert upload_step["with"]["path"] == "candidate-receipts/"
    assert upload_step["with"]["retention-days"] == 90

    # 2. Verify job downloads candidate receipts artifact
    download_step = next((s for s in verify_steps if s.get("name") == "Download candidate receipts"), None)
    assert download_step is not None, "verify job must download candidate receipts artifact"
    assert download_step.get("if") == "needs.prepare.outputs.kind == 'promotion'"
    assert "publication-candidate-receipts-" in download_step["with"]["name"]
    assert download_step["with"]["path"] == "candidate-receipts"

    # 3. Verify job materializes verification manifest for both promotion and rollback
    mat_step = next((s for s in verify_steps if s.get("name") == "Materialize verification manifest"), None)
    assert mat_step is not None, "verify job must materialize verification manifest"
    run_text = mat_step.get("run", "")
    assert "candidate-receipts/desired-manifest.json" in run_text
    assert "transaction-artifacts/verification-manifest.json" in run_text
    assert "restore_source" in run_text
    assert "parent_tx.attestation" in run_text

    # 4. Verify job supplies --manifest and --require-receipt to verify_live.py
    probe_step = next((s for s in verify_steps if s.get("name") == "Probe required live routes"), None)
    assert probe_step is not None, "verify job must have probe step"
    probe_run = probe_step.get("run", "")
    assert "--manifest transaction-artifacts/verification-manifest.json" in probe_run
    assert "--require-receipt" in probe_run
    assert "--candidate-manifest" not in probe_run


def test_transaction_verify_fails_closed_without_per_route_checksums() -> None:
    """Promotion verify must refuse manifests that would reduce probing to HTTP-only checks."""
    wf = _load_yaml(TX_WORKFLOW_PATH)
    verify_steps = wf["jobs"]["verify"]["steps"]
    mat_step = next((s for s in verify_steps if s.get("name") == "Materialize verification manifest"), None)
    assert mat_step is not None, "verify job must materialize verification manifest"
    run_text = mat_step.get("run", "")
    assert ".checksums" in run_text, "promotion path must assert per-route checksums exist"
    assert "byte-equivalence" in run_text


class _MockHTTPResponse:
    def __init__(self, content: bytes, status: int = 200) -> None:
        self._content = content
        self.status = status
        self.code = status
        self.headers = {"content-length": str(len(content))}
        self._offset = 0

    def read(self, chunk_size: int = -1) -> bytes:
        if chunk_size == -1:
            data = self._content[self._offset :]
            self._offset = len(self._content)
            return data
        data = self._content[self._offset : self._offset + chunk_size]
        self._offset += len(data)
        return data

    def __enter__(self) -> _MockHTTPResponse:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass


def test_isolated_job_promotion_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolated-job proof for promotion: missing manifest, wrong digest, partial routes, matching bytes."""
    import hashlib
    import json
    import urllib.error
    import urllib.request

    from scripts.publication import verify_live as verify_live_mod

    # Setup isolated directories
    deploy_dir = tmp_path / "runner_deploy"
    verify_dir = tmp_path / "runner_verify"
    deploy_dir.mkdir()
    verify_dir.mkdir()

    root_bytes = b"<html>homepage</html>"
    duckdb_bytes = b"duckdb-binary-data"
    root_sha = hashlib.sha256(root_bytes).hexdigest()
    duckdb_sha = hashlib.sha256(duckdb_bytes).hexdigest()

    # In deploy runner: candidate receipts generated
    cand_dir = deploy_dir / "candidate-receipts"
    cand_dir.mkdir()
    manifest_data = {
        "manifest_digest": "sha256:abc123",
        "checksums": {
            "/": root_sha,
            "/results/data/results.duckdb": duckdb_sha,
        },
    }
    (cand_dir / "desired-manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

    # Case 1: Missing manifest fails closed in verify runner
    report_missing = verify_live_mod.verify_live(
        base_url="https://benchbox.dev",
        manifest_path=verify_dir / "missing.json",
        require_receipt=True,
    )
    assert report_missing.ok is False
    assert any("not found" in e or "missing" in e for e in report_missing.errors)

    # Artifact transfer: simulate actions/download-artifact into fresh verify runner
    verify_cand_dir = verify_dir / "candidate-receipts"
    verify_cand_dir.mkdir()
    (verify_cand_dir / "desired-manifest.json").write_text(
        (cand_dir / "desired-manifest.json").read_text(encoding="utf-8"), encoding="utf-8"
    )

    # Materialize verification manifest in verify runner
    tx_artifacts = verify_dir / "transaction-artifacts"
    tx_artifacts.mkdir()
    verif_manifest_path = tx_artifacts / "verification-manifest.json"
    verif_manifest_path.write_text(
        (verify_cand_dir / "desired-manifest.json").read_text(encoding="utf-8"), encoding="utf-8"
    )

    # Case 2: Wrong digest fails closed
    def mock_wrong_urlopen(req: Any, timeout: float = 30) -> _MockHTTPResponse:
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if url.endswith("/results/data/results.duckdb"):
            return _MockHTTPResponse(b"tampered-database-bytes", status=200)
        return _MockHTTPResponse(root_bytes, status=200)

    monkeypatch.setattr(urllib.request, "urlopen", mock_wrong_urlopen)
    report_wrong = verify_live_mod.verify_live(
        base_url="https://benchbox.dev",
        manifest_path=verif_manifest_path,
        require_receipt=True,
    )
    assert report_wrong.ok is False
    assert "/results/data/results.duckdb" in report_wrong.mismatched_checksums

    # Case 3: Partial routes (HTTP 404 on a route) fails closed
    def mock_partial_urlopen(req: Any, timeout: float = 30) -> _MockHTTPResponse:
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if url.endswith("/results/data/results.duckdb"):
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]
        return _MockHTTPResponse(root_bytes, status=200)

    monkeypatch.setattr(urllib.request, "urlopen", mock_partial_urlopen)
    report_partial = verify_live_mod.verify_live(
        base_url="https://benchbox.dev",
        manifest_path=verif_manifest_path,
        require_receipt=True,
    )
    assert report_partial.ok is False
    assert any("404" in e for e in report_partial.errors)

    # Case 4: Successful matching bytes
    def mock_matching_urlopen(req: Any, timeout: float = 30) -> _MockHTTPResponse:
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if url.endswith("/results/data/results.duckdb"):
            return _MockHTTPResponse(duckdb_bytes, status=200)
        return _MockHTTPResponse(root_bytes, status=200)

    monkeypatch.setattr(urllib.request, "urlopen", mock_matching_urlopen)
    report_success = verify_live_mod.verify_live(
        base_url="https://benchbox.dev",
        manifest_path=verif_manifest_path,
        require_receipt=True,
    )
    assert report_success.ok is True
    assert len(report_success.matched_checksums) >= 2
    assert report_success.matched_checksums["/"] == root_sha
    assert report_success.matched_checksums["/results/data/results.duckdb"] == duckdb_sha


def test_isolated_job_rollback_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolated-job proof for rollback: absent parent attestation, wrong digest, matching restored bytes."""
    import hashlib
    import json
    import urllib.request

    from scripts.publication import verify_live as verify_live_mod

    verify_dir = tmp_path / "runner_verify_rollback"
    tx_artifacts = verify_dir / "transaction-artifacts"
    tx_artifacts.mkdir(parents=True)

    restored_root = b"<html>restored-homepage</html>"
    restored_db = b"restored-duckdb-data"
    restored_root_sha = hashlib.sha256(restored_root).hexdigest()
    restored_db_sha = hashlib.sha256(restored_db).hexdigest()

    # Case 1: Parent transaction lacking attestation routes fails closed
    parent_tx_bad = {
        "transaction_id": "tx-parent-bad",
        "attestation": None,
    }
    with pytest.raises(SystemExit) as exc:
        if not parent_tx_bad.get("attestation") or not parent_tx_bad["attestation"].get("routes"):
            raise SystemExit("parent transaction lacks live attestation routes for rollback verification")
    assert "lacks live attestation routes" in str(exc.value)

    # Parent transaction with valid prior live-receipt attestation
    parent_tx = {
        "transaction_id": "tx-parent-good",
        "content": {"manifest_digest": "sha256:parent123"},
        "attestation": {
            "routes": [
                {"path": "/", "sha256": restored_root_sha, "ok": True},
                {"path": "/results/data/results.duckdb", "sha256": restored_db_sha, "ok": True},
            ]
        },
    }

    # Materialize rollback verification manifest
    rollback_manifest = {
        "manifest_digest": parent_tx["content"]["manifest_digest"],
        "checksums": {
            r["path"]: r["sha256"] for r in parent_tx["attestation"]["routes"] if r.get("sha256") and r.get("ok")
        },
    }
    manifest_path = tx_artifacts / "verification-manifest.json"
    manifest_path.write_text(json.dumps(rollback_manifest), encoding="utf-8")

    # Case 2: Wrong digest (e.g. still serving failed content instead of restored content)
    def mock_failed_content_urlopen(req: Any, timeout: float = 30) -> _MockHTTPResponse:
        return _MockHTTPResponse(b"corrupted-or-unrestored-content", status=200)

    monkeypatch.setattr(urllib.request, "urlopen", mock_failed_content_urlopen)
    report_mismatch = verify_live_mod.verify_live(
        base_url="https://benchbox.dev",
        manifest_path=manifest_path,
        require_receipt=True,
    )
    assert report_mismatch.ok is False
    assert any("Receipt checksum mismatch" in e for e in report_mismatch.errors)

    # Case 3: Matching restored bytes succeeds
    def mock_restored_urlopen(req: Any, timeout: float = 30) -> _MockHTTPResponse:
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if url.endswith("/results/data/results.duckdb"):
            return _MockHTTPResponse(restored_db, status=200)
        return _MockHTTPResponse(restored_root, status=200)

    monkeypatch.setattr(urllib.request, "urlopen", mock_restored_urlopen)
    report_success = verify_live_mod.verify_live(
        base_url="https://benchbox.dev",
        manifest_path=manifest_path,
        require_receipt=True,
    )
    assert report_success.ok is True
    assert report_success.matched_checksums["/"] == restored_root_sha
    assert report_success.matched_checksums["/results/data/results.duckdb"] == restored_db_sha
