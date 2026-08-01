from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "_project/scripts/audit_sha_check.py"
SPEC = importlib.util.spec_from_file_location("audit_sha_check", SCRIPT)
assert SPEC and SPEC.loader
audit_sha_check = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit_sha_check
SPEC.loader.exec_module(audit_sha_check)

pytestmark = [pytest.mark.unit, pytest.mark.fast]

DEVELOP_SHA = "a" * 40
CHECKED_SHA = "b" * 40
REPLAY_SHA = "c" * 40


def _audit(tmp_path: Path, fields: str, body: str) -> Path:
    path = tmp_path / "audit.md"
    path.write_text(f"---\ndevelop_sha: {DEVELOP_SHA}\n{fields}---\n# Audit\n\n{body}\n", encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _git_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit_sha_check, "run_git", lambda _args: DEVELOP_SHA)
    monkeypatch.setattr(audit_sha_check, "git_ok", lambda _args: True)


def test_audit_sha_narrative_numbers_do_not_require_measurement_provenance(tmp_path: Path) -> None:
    path = _audit(tmp_path, "", "Reviewed PR #123 on 2026-08-01; version 4 remains supported.")
    result = audit_sha_check.validate_audit(path, "origin/develop")
    assert result.measured_at_sha is None


@pytest.mark.parametrize(
    "claim",
    [
        "44 passed, 1 skipped.",
        "The corpus contains 152 bundles and 24,644 queries.",
        "Current result: 27 comments across 18 PRs.",
        "The audit covered 36 tests.",
    ],
)
def test_audit_sha_numeric_evidence_requires_measured_at_sha(tmp_path: Path, claim: str) -> None:
    path = _audit(tmp_path, "", claim)
    with pytest.raises(audit_sha_check.AuditShaError, match="measured_at_sha"):
        audit_sha_check.validate_audit(path, "origin/develop")


def test_audit_sha_rejects_mismatched_measurement_sha(tmp_path: Path) -> None:
    path = _audit(tmp_path, f"measured_at_sha: {CHECKED_SHA}\n", "44 tests passed.")
    with pytest.raises(audit_sha_check.AuditShaError, match="does not match the declared exact tree"):
        audit_sha_check.validate_audit(path, "origin/develop")


def test_audit_sha_checked_tree_can_differ_from_develop_base(tmp_path: Path) -> None:
    path = _audit(
        tmp_path,
        f"checked_sha: {CHECKED_SHA}\nmeasured_at_sha: {CHECKED_SHA}\n",
        "44 tests passed.",
    )
    result = audit_sha_check.validate_audit(path, "origin/develop")
    assert result.measured_at_sha == CHECKED_SHA


def test_audit_sha_replay_requires_scope(tmp_path: Path) -> None:
    path = _audit(
        tmp_path,
        f"measured_at_sha: {DEVELOP_SHA}\nreplay_sha: {REPLAY_SHA}\n",
        "44 tests passed.",
    )
    with pytest.raises(audit_sha_check.AuditShaError, match="replay_scope"):
        audit_sha_check.validate_audit(path, "origin/develop")


def test_audit_sha_accepts_bounded_replay_provenance(tmp_path: Path) -> None:
    path = _audit(
        tmp_path,
        f"measured_at_sha: {DEVELOP_SHA}\nreplay_sha: {REPLAY_SHA}\nreplay_scope: unit regression subset\n",
        "44 tests passed.",
    )
    result = audit_sha_check.validate_audit(path, "origin/develop")
    assert result.replay_sha == REPLAY_SHA
