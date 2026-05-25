"""End-to-end round trip: `benchbox submit` → validate_submission.py.

Reproduces the workflow that lives across two scripts and one CI
pipeline: package a bundle into the submission directory, copy the
bundle + manifest into a `results-data/bundles/` style directory that
already contains other bundles, then run the validator that CI runs on
each PR. The directory-already-has-other-bundles part is the load-bearing
case — a hash algorithm that includes the directory contents will fail
here even though the actual submission is valid.

See `_project/DONE/main/planning/fix-submission-hash-mismatch-vs-validator-directory-scope.yaml`
for context.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.resource_heavy,
]

_FAKE_BUNDLE = {
    "version": "2.0",
    "run": {
        "id": "fake-run-1",
        "timestamp": "2026-04-27T00:00:00Z",
        "total_duration_ms": 100,
    },
    "benchmark": {"id": "tpch", "scale_factor": 0.01},
    "platform": {"name": "duckdb"},
    "summary": {"power_score": 1.0, "geomean_ms": 1.0, "total_duration_s": 0.1, "validation": "passed"},
    "queries": [
        {"id": 1, "ms": 1.0},
        {"id": 6, "ms": 1.0},
    ],
}


def _write_payload(path: Path, name: str, payload: dict) -> Path:
    target = path / f"{name}.json"
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def _write_bundle(path: Path, name: str, marker: str) -> Path:
    """Write a deterministic dummy bundle whose contents differ by `marker`."""
    bundle = {**_FAKE_BUNDLE}
    bundle["run"] = {**_FAKE_BUNDLE["run"], "id": f"run-{marker}"}
    return _write_payload(path, name, bundle)


def _run_validator(bundle_paths: list[Path]) -> subprocess.CompletedProcess[str]:
    """Invoke scripts/validate_submission.py the way CI does."""
    repo_root = Path(__file__).resolve().parents[2]
    cmd = [
        sys.executable,
        str(repo_root / "scripts" / "validate_submission.py"),
        *[str(p) for p in bundle_paths],
    ]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


@pytest.fixture
def populated_corpus(tmp_path: Path) -> Path:
    """results-data/bundles/-style directory with several pre-existing bundles."""
    bundles_dir = tmp_path / "results-data" / "bundles"
    bundles_dir.mkdir(parents=True)
    # Three pre-existing bundles in the directory mimic the published-results
    # state at PR time. Hash algorithms that include the directory contents
    # will diverge here.
    _write_bundle(bundles_dir, "tpch_sf001_duckdb_existing", "existing-1")
    _write_bundle(bundles_dir, "ssb_sf01_clickhouse_existing", "existing-2")
    _write_bundle(bundles_dir, "tpch_sf01_polars_existing", "existing-3")
    return bundles_dir


def _package_via_submit(bundle_path: Path, output_dir: Path) -> Path:
    """Run `benchbox submit` to produce a manifest. Returns the manifest path."""
    repo_root = Path(__file__).resolve().parents[2]
    # Invoke via the click command directly (not the console script) so the
    # test does not depend on the entry point being on PATH.
    from click.testing import CliRunner

    from benchbox.cli.commands.submit import submit

    runner = CliRunner()
    result = runner.invoke(
        submit,
        [str(bundle_path), "--output", str(output_dir)],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, f"benchbox submit failed: {result.output}"
    manifest = output_dir / f"{bundle_path.stem}.manifest.json"
    assert manifest.is_file(), f"manifest missing from {output_dir}"
    # repo_root is referenced by _run_validator below; keep it accessible.
    _ = repo_root
    return manifest


def test_round_trip_validates_clean_submission(tmp_path: Path, populated_corpus: Path) -> None:
    """Package a bundle, drop it next to existing bundles, validate: must pass."""
    # 1. Generate a fresh bundle outside the corpus.
    source_dir = tmp_path / "fresh"
    source_dir.mkdir()
    bundle = _write_bundle(source_dir, "tpch_sf001_duckdb_new", "new-clean")

    # 2. Package via `benchbox submit`.
    out_dir = tmp_path / "submission"
    manifest_src = _package_via_submit(bundle, out_dir)

    # 3. Copy bundle + manifest into the populated corpus.
    submitted_bundle = out_dir / "bundle" / bundle.name
    target_bundle = populated_corpus / bundle.name
    target_manifest = populated_corpus / manifest_src.name
    shutil.copy2(submitted_bundle, target_bundle)
    shutil.copy2(manifest_src, target_manifest)

    # 4. Run the CI validator and confirm it passes.
    proc = _run_validator([target_bundle])
    assert proc.returncode == 0, (
        f"validator should accept an unmodified submission, "
        f"but exited {proc.returncode}.\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert "FAIL" not in proc.stdout, proc.stdout


def test_round_trip_rejects_tampered_bundle(tmp_path: Path, populated_corpus: Path) -> None:
    """Bundle mutated after the manifest hash is computed must be rejected."""
    source_dir = tmp_path / "fresh"
    source_dir.mkdir()
    bundle = _write_bundle(source_dir, "tpch_sf001_duckdb_tamper", "tamper")

    out_dir = tmp_path / "submission"
    manifest_src = _package_via_submit(bundle, out_dir)

    submitted_bundle = out_dir / "bundle" / bundle.name
    target_bundle = populated_corpus / bundle.name
    target_manifest = populated_corpus / manifest_src.name
    shutil.copy2(submitted_bundle, target_bundle)
    shutil.copy2(manifest_src, target_manifest)

    # Mutate the deposited bundle: flip a timing value.
    payload = json.loads(target_bundle.read_text(encoding="utf-8"))
    payload["queries"][0]["ms"] = 99.9
    target_bundle.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    proc = _run_validator([target_bundle])
    assert proc.returncode != 0, (
        f"validator must reject a tampered bundle but exited 0.\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    # The error must name the offending file and indicate a hash mismatch.
    assert "hash mismatch" in proc.stdout.lower(), proc.stdout
    assert bundle.name in proc.stdout, proc.stdout


def test_validator_accepts_forward_numeric_schema_v2_family(tmp_path: Path) -> None:
    """Public submissions accept future numeric 2.x versions by policy."""
    source_dir = tmp_path / "fresh"
    source_dir.mkdir()
    bundle = _write_bundle(source_dir, "tpch_sf001_duckdb_future_v2", "future-v2")
    payload = json.loads(bundle.read_text(encoding="utf-8"))
    payload["version"] = "2.99"
    bundle.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    proc = _run_validator([bundle])

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "FAIL" not in proc.stdout, proc.stdout


def test_validator_rejects_malformed_schema_v2_family(tmp_path: Path) -> None:
    """Malformed versions should not pass just because they start with ``2.``."""
    source_dir = tmp_path / "fresh"
    source_dir.mkdir()
    bundle = _write_bundle(source_dir, "tpch_sf001_duckdb_malformed_v2", "malformed-v2")
    payload = json.loads(bundle.read_text(encoding="utf-8"))
    payload["version"] = "2.x"
    bundle.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    proc = _run_validator([bundle])

    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "public submission schema policy" in proc.stdout
    assert "numeric schema version family 2.x" in proc.stdout


@pytest.mark.parametrize("validation_status", ["not_run", "uncertain"])
def test_validator_rejects_non_clean_public_validation_status(tmp_path: Path, validation_status: str) -> None:
    source_dir = tmp_path / "fresh"
    source_dir.mkdir()
    payload = {**_FAKE_BUNDLE, "summary": {**_FAKE_BUNDLE["summary"], "validation": validation_status}}
    bundle = _write_payload(source_dir, f"tpch_sf001_duckdb_{validation_status}", payload)

    proc = _run_validator([bundle])

    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "summary.validation must be 'passed'" in proc.stdout


def test_validator_rejects_missing_public_validation_status(tmp_path: Path) -> None:
    source_dir = tmp_path / "fresh"
    source_dir.mkdir()
    summary = {**_FAKE_BUNDLE["summary"]}
    summary.pop("validation")
    payload = {**_FAKE_BUNDLE, "summary": summary}
    bundle = _write_payload(source_dir, "tpch_sf001_duckdb_missing_validation", payload)

    proc = _run_validator([bundle])

    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "summary.validation is required" in proc.stdout


def test_validator_rejects_translation_fallback_public_submission(tmp_path: Path) -> None:
    source_dir = tmp_path / "fresh"
    source_dir.mkdir()
    payload = {
        **_FAKE_BUNDLE,
        "execution": {"mode": "sql", "translation": {"status": "fallback", "strict_mode": False}},
    }
    bundle = _write_payload(source_dir, "tpch_sf001_duckdb_translation_fallback", payload)

    proc = _run_validator([bundle])

    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "execution.translation.status='fallback'" in proc.stdout
