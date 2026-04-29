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
