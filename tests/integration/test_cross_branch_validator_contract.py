"""Cross-branch contract test: develop's writer must emit hashes that
the published-results validator accepts.

Background: the 2026-04-29 Codex agent-proxy dry-run surfaced a
release-blocker — develop's `benchbox submit` writer used a per-FILE
SHA-256 hash, while the validator pinned at v0.2.1 on the
`published-results` branch used a per-DIRECTORY hash. Result: every
contributor-emitted bundle would fail CI on the documented PR target
branch with `Bundle hash mismatch` and no contributor-side knob to
resolve it. Forensic at
`_project/handoffs/external-dry-run-retrospective-2026-04-29.md`.

This test exercises the writer → validator round-trip end-to-end so any
future drift between the two sides of the contract fails CI on develop
before it reaches contributors.

Vendoring: the validator is vendored at
`tests/fixtures/published_results_validator.py` rather than fetched
live via `git show origin/published-results:...` so the test stays
deterministic (no network, no branch-state assumptions) and runs in
the fast lane. The vendored copy MUST stay byte-identical to
`scripts/validate_submission.py` on develop AND to
`scripts/validate_submission.py` on `published-results`. The
`test_vendored_validator_matches_develop_script` drift guard fails CI
if step 1 (sync to develop's script) is skipped; sync to
`published-results` is operational discipline (open the parallel PR).
"""

from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[2]
VENDORED_VALIDATOR = REPO_ROOT / "tests" / "fixtures" / "published_results_validator.py"
DEVELOP_VALIDATOR = REPO_ROOT / "scripts" / "validate_submission.py"


def _fake_result() -> SimpleNamespace:
    """Mirror the unit-test stub in tests/unit/cli/commands/test_submit.py."""
    return SimpleNamespace(
        benchmark_name="tpch",
        platform="duckdb",
        scale_factor=0.01,
        total_queries=22,
        duration_seconds=12.34,
    )


def _minimal_schema_v2_bundle() -> dict:
    """Bundle JSON that satisfies all required validator schema-v2 keys.

    The submit writer copies the source file verbatim into bundle/, so
    the source must already be a valid schema-v2 bundle for the
    validator to accept it. This is the leanest payload that passes —
    any tighter and the validator's schema checks (REQUIRED_TOP_KEYS,
    queries timing) start failing for reasons unrelated to the hash
    contract.
    """
    return {
        "version": "2.0",
        "run": {
            "id": "test-run-id",
            "timestamp": "2026-04-29T00:00:00Z",
            "total_duration_ms": 12340,
        },
        "benchmark": {"id": "tpch", "scale_factor": 0.01},
        "platform": {"name": "duckdb"},
        "summary": {"queries": {"total": 22}},
        "queries": [{"id": "Q1", "ms": 100.0}],
    }


def test_writer_emits_hash_format_validator_accepts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """End-to-end contract: `benchbox submit` must produce a bundle
    that the (vendored) published-results validator accepts."""
    sub = importlib.import_module("benchbox.cli.commands.submit")

    src = tmp_path / "tpch_duckdb.json"
    src.write_text(json.dumps(_minimal_schema_v2_bundle()), encoding="utf-8")

    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))

    out_dir = tmp_path / "submission"
    result = CliRunner().invoke(sub.submit, [str(src), "--output", str(out_dir)])

    assert result.exit_code == 0, f"benchbox submit failed: {result.output}"
    bundle_path = out_dir / "bundle" / src.name
    assert bundle_path.is_file()

    proc = subprocess.run(
        [sys.executable, str(VENDORED_VALIDATOR), str(bundle_path)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    output = proc.stdout + proc.stderr

    assert proc.returncode == 0, (
        f"Vendored published-results validator rejected develop's bundle. "
        f"This is the same class of release-blocker as the 2026-04-29 dry-run. "
        f"Output:\n{output}"
    )
    assert "0 error(s), 0 warning(s)" in output, output


def test_writer_companion_hashes_validator_accepts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Companion files (.plans.json / .tuning.json) — the per-file hash
    contract covers them too via manifest.companion_hashes."""
    sub = importlib.import_module("benchbox.cli.commands.submit")

    src = tmp_path / "tpch_duckdb.json"
    src.write_text(json.dumps(_minimal_schema_v2_bundle()), encoding="utf-8")
    (tmp_path / "tpch_duckdb.plans.json").write_text('{"plans": []}', encoding="utf-8")
    (tmp_path / "tpch_duckdb.tuning.json").write_text('{"tuning": {}}', encoding="utf-8")

    monkeypatch.setattr(sub, "load_result_file", lambda *_a, **_k: (_fake_result(), {}))

    out_dir = tmp_path / "submission"
    result = CliRunner().invoke(sub.submit, [str(src), "--output", str(out_dir)])
    assert result.exit_code == 0, result.output

    bundle_path = out_dir / "bundle" / src.name

    proc = subprocess.run(
        [sys.executable, str(VENDORED_VALIDATOR), str(bundle_path)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    output = proc.stdout + proc.stderr

    assert proc.returncode == 0, f"Validator rejected bundle with companions. Output:\n{output}"
    assert "0 error(s)" in output, output


def test_validator_rejects_symlinked_bundle(tmp_path: Path) -> None:
    """Symlink defense: a bundle that resolves through a symlink must be
    rejected by the validator regardless of whether the symlink target's
    bytes happen to hash correctly. The validator runs on PR-supplied
    content; without this check, a malicious PR could redirect the hash
    computation to attacker-chosen bytes."""
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()

    real = tmp_path / "real_target.json"
    real.write_text(json.dumps(_minimal_schema_v2_bundle()), encoding="utf-8")

    # Symlink lives inside bundle_dir, points to a file outside it.
    bundle_filename = "tpch_duckdb.json"
    symlink_path = bundle_dir / bundle_filename
    symlink_path.symlink_to(real)

    # Manifest sits beside the bundle (where the validator discovers it
    # via bundle_path.parent / "submission-manifest.json"). Hash matches
    # the real target's bytes — the validator must reject *because of*
    # the symlink, not because of a hash mismatch.
    real_hash = hashlib.sha256(real.read_bytes()).hexdigest()
    manifest = {
        "bundle_file": bundle_filename,
        "bundle_hash": real_hash,
        "companion_hashes": {},
    }
    (bundle_dir / "submission-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(VENDORED_VALIDATOR), str(symlink_path)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    output = proc.stdout + proc.stderr

    assert proc.returncode != 0, f"Validator wrongly accepted a symlinked bundle. Output:\n{output}"
    assert "symlink" in output.lower(), f"Expected a symlink-specific error. Output:\n{output}"


def test_validator_surfaces_both_missing_manifest_fields(tmp_path: Path) -> None:
    """Early-return UX: a manifest missing both bundle_file and bundle_hash
    should warn about both in one pass, not just the first."""
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    bundle_path = bundle_dir / "tpch_duckdb.json"
    bundle_path.write_text(json.dumps(_minimal_schema_v2_bundle()), encoding="utf-8")
    # Manifest is intentionally empty to exercise the both-fields-missing path.
    # Sits beside the bundle where the validator discovers it.
    (bundle_dir / "submission-manifest.json").write_text("{}", encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(VENDORED_VALIDATOR), str(bundle_path)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    output = proc.stdout + proc.stderr

    # Both fields are missing — both warnings should surface in one pass.
    assert "bundle_file" in output, output
    assert "bundle_hash" in output, output


def test_vendored_validator_matches_develop_script() -> None:
    """Drift guard: vendored fixture MUST stay byte-identical to
    `scripts/validate_submission.py`. If you changed one, change both
    AND open a parallel PR onto `published-results`."""
    vendored = VENDORED_VALIDATOR.read_bytes()
    develop = DEVELOP_VALIDATOR.read_bytes()
    assert vendored == develop, (
        "Vendored published-results validator has drifted from "
        "scripts/validate_submission.py on develop. Re-sync the fixture "
        "AND open a PR onto `published-results` with the same change. "
        "See the docstring at the top of this file for the resync workflow."
    )


def test_validator_prefers_per_bundle_manifest_over_legacy(tmp_path: Path) -> None:
    """Per-bundle manifest precedence: when both ``<stem>.manifest.json`` and
    legacy ``submission-manifest.json`` are present, the per-bundle file
    must win. The hosted-submit CLI emits per-bundle manifests exclusively;
    if a future refactor flips precedence so legacy beats per-bundle, hosted
    bundles mirrored into the PR corpus would fail with confusing errors.
    """
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    bundle_filename = "tpch_duckdb.json"
    bundle_path = bundle_dir / bundle_filename
    bundle_path.write_text(json.dumps(_minimal_schema_v2_bundle()), encoding="utf-8")

    actual_hash = hashlib.sha256(bundle_path.read_bytes()).hexdigest()

    per_bundle_manifest = {
        "bundle_file": bundle_filename,
        "bundle_hash": actual_hash,
        "companion_hashes": {},
    }
    legacy_manifest = {
        "bundle_file": bundle_filename,
        "bundle_hash": "0" * 64,  # Wrong hash — would fail if validator picked legacy.
        "companion_hashes": {},
    }
    (bundle_dir / "tpch_duckdb.manifest.json").write_text(json.dumps(per_bundle_manifest), encoding="utf-8")
    (bundle_dir / "submission-manifest.json").write_text(json.dumps(legacy_manifest), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(VENDORED_VALIDATOR), str(bundle_path)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    output = proc.stdout + proc.stderr

    assert proc.returncode == 0, f"Validator must accept bundle when per-bundle manifest matches. Output:\n{output}"
    assert "Bundle hash mismatch" not in output, output


def test_validator_skips_per_bundle_manifest_during_discovery(tmp_path: Path) -> None:
    """Discovery skip: ``*.manifest.json`` files must not be discovered as
    bundles. Without this skip, an explicit-path validation that includes
    the per-bundle manifest fails with "JSON object" or hash errors and the
    published-results CI workflow falsely rejects valid PRs."""
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    bundle_filename = "tpch_duckdb.json"
    bundle_path = bundle_dir / bundle_filename
    bundle_path.write_text(json.dumps(_minimal_schema_v2_bundle()), encoding="utf-8")

    actual_hash = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    manifest = {
        "bundle_file": bundle_filename,
        "bundle_hash": actual_hash,
        "companion_hashes": {},
    }
    manifest_path = bundle_dir / "tpch_duckdb.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    # Pass BOTH paths explicitly, mirroring how the published-results
    # workflow may pass changed files.
    proc = subprocess.run(
        [sys.executable, str(VENDORED_VALIDATOR), str(bundle_path), str(manifest_path)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    output = proc.stdout + proc.stderr

    assert proc.returncode == 0, f"Validator must skip explicit-path *.manifest.json files. Output:\n{output}"
    # Validate exactly one bundle was processed even though two paths were passed.
    assert "Validated 1 bundle(s)" in output or "1 bundle" in output, output
