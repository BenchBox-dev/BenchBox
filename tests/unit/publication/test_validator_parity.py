"""Tests for scripts/publication/validator_parity.py (A2 w4)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts/publication/validator_parity.py"


def _load_parity_module():
    spec = importlib.util.spec_from_file_location("validator_parity_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_validator_parity_script_exists() -> None:
    assert SCRIPT.is_file(), "scripts/publication/validator_parity.py must exist (A2 w4)"


def test_validator_parity_executable_and_parses_args() -> None:
    # --help should exit 0 and mention required flags
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--base-sha" in result.stdout
    assert "--merge-sha" in result.stdout
    assert "--head-sha" in result.stdout
    assert "--corpus-changed-paths" in result.stdout


def test_validator_parity_needs_base_and_merge_sha(tmp_path: Path) -> None:
    # Missing SHAs should exit 2 (usage error)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert result.returncode == 2
    assert "BASE_SHA" in result.stderr or "MERGE_SHA" in result.stderr or "HEAD_SHA" in result.stderr


def test_validator_parity_check_without_shas_is_not_ok() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
        env={
            k: v
            for k, v in __import__("os").environ.items()
            if k not in {"BASE_SHA", "MERGE_SHA", "HEAD_SHA", "PR_HEAD_SHA"}
        },
    )
    assert result.returncode != 0
    assert result.returncode == 2


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr}"
    return result.stdout.strip()


def _minimal_bundle_dict() -> dict:
    """Minimal schema-v2 bundle that benchbox validate_bundles accepts."""
    return {
        "version": "2.1",
        "run": {"id": "abc123", "timestamp": "2026-04-01T12:00:00", "total_duration_ms": 5000},
        "benchmark": {"id": "tpch", "name": "TPC-H", "scale_factor": 0.01},
        "platform": {"name": "DuckDB", "version": "1.4.3"},
        "summary": {"validation": "passed", "queries": {"total": 2, "passed": 2, "failed": 0}},
        "phases": {"validation": {"status": "PASSED"}},
        "queries": [
            {"id": "Q1", "ms": 100, "status": "SUCCESS"},
            {"id": "Q2", "ms": 200, "status": "SUCCESS"},
        ],
    }


def _init_fixture_repo(repo: Path, rel: str) -> str:
    """Init a git repo with one valid bundle commit; return that commit SHA."""
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    bundle_file = repo / rel
    bundle_file.parent.mkdir(parents=True, exist_ok=True)
    bundle_file.write_text(json.dumps(_minimal_bundle_dict()), encoding="utf-8")
    _git(repo, "add", rel)
    _git(repo, "commit", "-m", "add bundle")
    return _git(repo, "rev-parse", "HEAD")


def test_head_vs_merge_real_payloads_diverge_when_head_missing(tmp_path: Path, monkeypatch) -> None:
    """Two real payloads, no extractor mock: bundle valid at merge SHA, absent at head.

    The head run must fail closed (rc 1, "No bundles extracted") so compare
    reports divergence instead of a vacuous "Parity OK" over two zeros.
    """
    parity = _load_parity_module()
    repo = tmp_path / "fixture-repo"
    rel = "results-data/bundles/tpch_result.json"
    merge_sha = _init_fixture_repo(repo, rel)
    _git(repo, "rm", "-q", rel)
    _git(repo, "commit", "-m", "drop bundle")
    head_sha = _git(repo, "rev-parse", "HEAD")
    monkeypatch.setattr(parity, "CHECKOUT_ROOT", repo)

    merge_rc, _ = parity._run_validation_on_payload([rel], merge_sha)
    assert merge_rc == 0
    head_rc, head_msg = parity._run_validation_on_payload([rel], head_sha)
    assert head_rc == 1
    assert "No bundles extracted" in head_msg
    rc, message = parity.compare_head_merge_outcomes([rel], merge_sha, head_sha)
    assert rc == 1
    assert "diverged" in message


def test_head_vs_merge_real_payloads_agree_when_identical(tmp_path: Path, monkeypatch) -> None:
    """Two real payloads, no extractor mock: valid bundle present at both SHAs."""
    parity = _load_parity_module()
    repo = tmp_path / "fixture-repo"
    rel = "results-data/bundles/tpch_result.json"
    first_sha = _init_fixture_repo(repo, rel)
    _git(repo, "commit", "--allow-empty", "-m", "unrelated")
    second_sha = _git(repo, "rev-parse", "HEAD")
    monkeypatch.setattr(parity, "CHECKOUT_ROOT", repo)

    rc, message = parity.compare_head_merge_outcomes([rel], first_sha, second_sha)
    assert rc == 0
    assert message.startswith("Parity OK")


def test_missing_payload_at_requested_sha_fails_closed(tmp_path: Path, monkeypatch) -> None:
    """Non-empty bundle list with nothing extractable is rc 1, not a silent pass."""
    parity = _load_parity_module()
    repo = tmp_path / "fixture-repo"
    rel = "results-data/bundles/tpch_result.json"
    merge_sha = _init_fixture_repo(repo, rel)
    monkeypatch.setattr(parity, "CHECKOUT_ROOT", repo)

    rc, message = parity._run_validation_on_payload(["results-data/bundles/ghost.json"], merge_sha)
    assert rc == 1
    assert "No bundles extracted" in message


def test_validator_parity_corpus_missing_file_is_error(tmp_path: Path) -> None:
    repo = REPO_ROOT
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, check=False)
    if base.returncode != 0:
        pytest.skip("no HEAD")
    sha = base.stdout.strip()
    missing = tmp_path / "missing.txt"
    # File does not exist -> should error 1
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--base-sha",
            sha,
            "--merge-sha",
            sha,
            "--head-sha",
            sha,
            "--corpus-changed-paths",
            str(missing),
        ],
        capture_output=True,
        text=True,
        cwd=str(repo),
        check=False,
    )
    assert result.returncode == 1
    assert "CORPUS_CHANGED_PATHS_FILE missing" in result.stderr or "missing" in result.stderr.lower()


def test_validator_parity_uses_three_dot_semantics() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "BASE_SHA...MERGE_SHA" in text or "BASE_SHA...$MERGE_SHA" in text or "...MERGE_SHA" in text
    assert "git show" in text or "git cat-file" in text
    assert "git ls-tree" in text
    assert "CHANGED_MANIFESTS" in text or "changed_manifests" in text.lower()
    assert "validate_bundles" in text
    assert "compare_head_merge_outcomes" in text


def test_head_vs_merge_divergence_fails(monkeypatch) -> None:
    parity = _load_parity_module()
    calls: list[str] = []

    def fake_validate(bundle_paths, sha, require_manifest=False, allow_partial=False):
        calls.append(sha)
        # First call (merge) succeeds, second (head) fails
        if sha == "merge" * 8:
            return 0, "merge ok"
        return 1, "head fail"

    monkeypatch.setattr(parity, "_run_validation_on_payload", fake_validate)
    rc, message = parity.compare_head_merge_outcomes(
        ["results-data/bundles/example.json"],
        "merge" * 8,
        "head0" * 8,
    )
    assert rc == 1
    assert "diverged" in message
    assert calls == ["merge" * 8, "head0" * 8]


def test_head_vs_merge_both_fail(monkeypatch) -> None:
    parity = _load_parity_module()
    monkeypatch.setattr(
        parity,
        "_run_validation_on_payload",
        lambda *args, **kwargs: (1, "fail"),
    )
    rc, message = parity.compare_head_merge_outcomes([], "a" * 40, "b" * 40)
    assert rc == 1
    assert "both" in message.lower() and "failed" in message.lower()


def test_head_vs_merge_both_succeed(monkeypatch) -> None:
    parity = _load_parity_module()
    monkeypatch.setattr(
        parity,
        "_run_validation_on_payload",
        lambda *args, **kwargs: (0, "ok"),
    )
    rc, message = parity.compare_head_merge_outcomes([], "a" * 40, "b" * 40)
    assert rc == 0
    assert message.startswith("Parity OK")


def test_validate_submission_corpus_flag_exists() -> None:
    from scripts.validate_submission import _validate_corpus_changed_paths_file

    assert callable(_validate_corpus_changed_paths_file)
    # None -> continue
    assert _validate_corpus_changed_paths_file(None) is None
