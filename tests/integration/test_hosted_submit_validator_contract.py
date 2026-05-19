"""Hosted-submit -> develop-validator contract test.

Background: `benchbox submit --service` (Phase 3 hosted path) sends bytes
to the hosted ingest service WITHOUT first running
`scripts/validate_submission.py` against the bundle. The trade-off is
documented in `_dispatch_service_mode` (benchbox/cli/commands/submit.py)
and captured in blind-spot
`_project/blind-spots/2026-05-01-103000-hosted-submit-no-local-validate-preflight.md`:

    The hosted ingest service validates server-side; running the
    develop-tip validator here would couple the Python CLI release
    cadence to the hosted API's accepted-schema set and create false
    rejections on legacy clients. The trade-off: contributors pay full
    upload latency before the service tells them what's wrong. We
    accept that trade-off until we have a hosted-vs-validator contract
    test that proves the two accept the same bundles; once that
    exists, fail-fast preflight is the obvious next move.

This test is that contract test. It exercises the exact bundle layout
that the hosted service would mirror onto `published-results` and
asserts that `scripts/validate_submission.py` accepts/rejects it
consistently with what the manifest contract requires. If the develop
validator's accepted-schema set drifts from what the hosted submit
path emits, this test fails fast on develop instead of producing
silently-divergent bundles in the corpus.

Scope: this asserts the *develop-side* contract for hosted-submit
output. The hosted ingest service's own validator is a black box from
this repo; that side of the contract is owned by the hosted
deployment. What this test guarantees is that drift on the develop
side (manifest shape, hash format, required keys) cannot land
silently.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[2]
DEVELOP_VALIDATOR = REPO_ROOT / "scripts" / "validate_submission.py"


def _fake_result() -> SimpleNamespace:
    return SimpleNamespace(
        benchmark_name="tpch",
        platform="duckdb",
        scale_factor=0.01,
        total_queries=22,
        duration_seconds=12.34,
    )


def _minimal_schema_v2_bundle() -> dict:
    return {
        "version": "2.0",
        "run": {
            "id": "test-run-id",
            "timestamp": "2026-05-02T00:00:00Z",
            "total_duration_ms": 12340,
        },
        "benchmark": {"id": "tpch", "scale_factor": 0.01},
        "platform": {"name": "duckdb"},
        "summary": {"queries": {"total": 22}},
        "queries": [{"id": "Q1", "ms": 100.0}],
    }


def _hosted_bundle_layout(tmp_path: Path) -> tuple[Path, Path, dict]:
    """Reconstruct the bundle layout the hosted service mirrors to corpus.

    The `--service` path uploads the source file as `bundle` plus a
    multipart manifest. When the hosted service later mirrors a
    submission into `published-results`, the layout is `<stem>.json`
    plus `<stem>.manifest.json` in the same directory — same shape
    `validate_submission.py` walks for PR-flow bundles. This helper
    produces that layout from the same in-process manifest builder
    that `_dispatch_service_mode` uses.
    """
    sub = importlib.import_module("benchbox.cli.commands.submit")

    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    source_path = bundle_dir / "tpch_duckdb.json"
    source_path.write_text(json.dumps(_minimal_schema_v2_bundle()), encoding="utf-8")

    # Build manifest with submission_path="hosted-service" — the exact
    # call _dispatch_service_mode makes at submit.py:222.
    manifest = sub._build_submission_manifest(
        source_path=source_path,
        companions=[],
        result=_fake_result(),
        submitted_by="contract-test@example.invalid",
        submission_path="hosted-service",
    )

    manifest_path = bundle_dir / f"{source_path.stem}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return source_path, manifest_path, manifest


def _run_validator(bundle_path: Path, cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(DEVELOP_VALIDATOR), str(bundle_path)],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    return proc.returncode, proc.stdout + proc.stderr


def test_hosted_bundle_passes_develop_validator(tmp_path: Path) -> None:
    """Happy path: the bundle the hosted-submit code path generates must
    pass `scripts/validate_submission.py` unchanged."""
    bundle_path, _manifest_path, _manifest = _hosted_bundle_layout(tmp_path)

    rc, output = _run_validator(bundle_path, cwd=tmp_path)

    assert rc == 0, (
        "develop validator rejected hosted-submit bundle. "
        "This is hosted-submit / develop drift — the same class as the "
        "2026-04-29 publishing release-blocker. Fix the divergence "
        "(submit.py manifest builder vs scripts/validate_submission.py "
        "schema) before landing.\n\n"
        f"Output:\n{output}"
    )
    assert "0 error(s)" in output, output


def test_hosted_bundle_with_corrupted_hash_is_rejected(tmp_path: Path) -> None:
    """Tamper detection: if the hosted manifest carries a hash that does
    not match the bundle's bytes, the develop validator must reject the
    bundle. Confirms both validators key off the same hash contract."""
    bundle_path, manifest_path, manifest = _hosted_bundle_layout(tmp_path)

    manifest["bundle_hash"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    rc, output = _run_validator(bundle_path, cwd=tmp_path)

    assert rc != 0, "validator must reject a hosted bundle with a wrong hash"
    assert "hash" in output.lower(), f"expected hash error, got:\n{output}"


def test_hosted_bundle_missing_required_schema_key_is_rejected(tmp_path: Path) -> None:
    """Schema drift detection: if the source file is missing a top-level
    schema-v2 key (`queries`, `summary`, etc.), the develop validator
    must reject. Hosted-side schema-v2 expectations must stay in lockstep
    with develop's REQUIRED_TOP_KEYS."""
    sub = importlib.import_module("benchbox.cli.commands.submit")

    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    source_path = bundle_dir / "tpch_duckdb.json"

    bad = _minimal_schema_v2_bundle()
    del bad["queries"]
    source_path.write_text(json.dumps(bad), encoding="utf-8")

    manifest = sub._build_submission_manifest(
        source_path=source_path,
        companions=[],
        result=_fake_result(),
        submitted_by="contract-test@example.invalid",
        submission_path="hosted-service",
    )
    (bundle_dir / f"{source_path.stem}.manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    rc, output = _run_validator(source_path, cwd=tmp_path)

    assert rc != 0, "validator must reject a bundle missing required schema-v2 keys"
    assert "queries" in output.lower(), f"expected `queries` error, got:\n{output}"


def test_hosted_manifest_schema_matches_pr_flow_for_required_keys(tmp_path: Path) -> None:
    """Cross-path manifest schema: the hosted-submit manifest must carry
    every key that the PR-flow manifest carries (and which the develop
    validator reads). Without this guard, a divergent change to one
    `_build_submission_manifest` call site could silently drop a field
    the validator depends on for the other path.
    """
    sub = importlib.import_module("benchbox.cli.commands.submit")

    src = tmp_path / "tpch_duckdb.json"
    src.write_text(json.dumps(_minimal_schema_v2_bundle()), encoding="utf-8")

    pr_manifest = sub._build_submission_manifest(
        source_path=src,
        companions=[],
        result=_fake_result(),
        submitted_by="x@example.invalid",
        submission_path="PR-based",
    )
    hosted_manifest = sub._build_submission_manifest(
        source_path=src,
        companions=[],
        result=_fake_result(),
        submitted_by="x@example.invalid",
        submission_path="hosted-service",
    )

    # Same key set in both paths — only `submission_path` differs in value.
    assert set(pr_manifest.keys()) == set(hosted_manifest.keys()), (
        f"hosted vs PR manifest key drift. PR={set(pr_manifest)}, hosted={set(hosted_manifest)}"
    )
    assert pr_manifest["submission_path"] == "PR-based"
    assert hosted_manifest["submission_path"] == "hosted-service"
    # Hash, bundle_file, and benchmark/platform/scale_factor are identical
    # for the same source file — the manifests differ only in metadata.
    for key in ("bundle_file", "bundle_hash", "benchmark", "platform", "scale_factor"):
        assert pr_manifest[key] == hosted_manifest[key], f"{key} drift"


def test_hosted_and_pr_manifest_built_via_dispatch_call_sites(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """w21 regression: drive each manifest through its dispatching call site
    (the hosted-service path and the PR-package path) rather than calling
    ``_build_submission_manifest`` directly with hard-coded arguments. If a
    future iteration of either dispatch mutates the manifest after
    construction or starts passing different arguments, the parity check
    below catches it; the previous direct-construction test could not."""
    from click.testing import CliRunner

    sub = importlib.import_module("benchbox.cli.commands.submit")

    src = tmp_path / "tpch_duckdb.json"
    src.write_text(json.dumps(_minimal_schema_v2_bundle()), encoding="utf-8")

    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))

    # ----- Drive the PR-package path through the CLI to capture its manifest -----
    out_dir = tmp_path / "submission"
    pr_result = CliRunner().invoke(sub.submit, [str(src), "--output", str(out_dir)])
    assert pr_result.exit_code == 0, pr_result.output
    pr_manifest_path = out_dir / "tpch_duckdb.manifest.json"
    assert pr_manifest_path.exists(), pr_result.output
    pr_manifest = json.loads(pr_manifest_path.read_text(encoding="utf-8"))

    # ----- Drive the hosted dispatch path with stubbed network calls --------
    captured_manifest: dict[str, dict] = {}

    def fake_submit_hosted_bundle(*, manifest: dict, bundle_hash: str, **_kwargs):
        captured_manifest["payload"] = manifest
        from benchbox.cli.submit_service import HostedSubmitResult, make_idempotency_key

        return HostedSubmitResult(
            status="accepted",
            idempotency_key=make_idempotency_key("https://hosted.invalid", bundle_hash),
            submission_id="fake-id",
        )

    monkeypatch.setattr(sub, "submit_hosted_bundle", fake_submit_hosted_bundle)
    monkeypatch.setattr(
        sub,
        "resolve_submission_token",
        lambda _service_url: SimpleNamespace(token="fake-token"),
    )
    monkeypatch.setattr(
        sub,
        "record_hosted_submission",
        lambda **_kwargs: tmp_path / "fake_history.json",
    )

    hosted_result = CliRunner().invoke(
        sub.submit,
        [
            str(src),
            "--service",
            "https://hosted.invalid",
            "--no-wait",
            "--visibility",
            "public",
        ],
    )
    assert hosted_result.exit_code == 0, hosted_result.output
    assert "payload" in captured_manifest, "hosted dispatch never called submit_hosted_bundle"
    hosted_manifest = captured_manifest["payload"]

    # Same key set; hosted vs PR diverges only in submission_path metadata.
    assert set(pr_manifest.keys()) == set(hosted_manifest.keys()), (
        f"hosted vs PR manifest key drift via dispatch call sites. PR={set(pr_manifest)}, hosted={set(hosted_manifest)}"
    )
    assert pr_manifest["submission_path"] == "PR-based"
    assert hosted_manifest["submission_path"] == "hosted-service"
    for key in ("bundle_file", "bundle_hash", "benchmark", "platform", "scale_factor"):
        assert pr_manifest[key] == hosted_manifest[key], f"{key} drift via dispatch call sites"
