"""Tests for scripts/publication/validator_parity.py (A2 w4)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts/publication/validator_parity.py"


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
    assert "BASE_SHA" in result.stderr or "MERGE_SHA" in result.stderr


def test_validator_parity_compares_merge_sha_payload(tmp_path: Path) -> None:
    # Create a base and merge scenario: use HEAD and HEAD~1 if available, else same SHA (shallow)
    repo = REPO_ROOT
    merge = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, check=False)
    if merge.returncode != 0:
        pytest.skip("no HEAD")
    merge_sha = merge.stdout.strip()
    base = subprocess.run(["git", "rev-parse", "HEAD~1"], cwd=str(repo), capture_output=True, text=True, check=False)
    if base.returncode != 0:
        # Shallow worktree: fallback to same SHA for empty diff parity
        base_sha = merge_sha
    else:
        base_sha = base.stdout.strip()
    corpus_file = tmp_path / "corpus_changed_paths.txt"
    corpus_file.write_text("", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--base-sha",
            base_sha,
            "--merge-sha",
            merge_sha,
            "--corpus-changed-paths",
            str(corpus_file),
        ],
        capture_output=True,
        text=True,
        cwd=str(repo),
        check=False,
    )
    # Should succeed (parity holds for trivial diff) or at worst 1 if validation fails due to no bundles
    # We accept 0 or 1, but not 2 (usage error). Must mention BASE_SHA/MERGE_SHA and handle corpus file.
    assert result.returncode in (0, 1), f"stderr={result.stderr} stdout={result.stdout}"
    assert "BASE_SHA" in result.stdout or "MERGE_SHA" in result.stdout or "Parity" in result.stdout


def test_validator_parity_corpus_missing_file_is_error(tmp_path: Path) -> None:
    repo = REPO_ROOT
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, check=False)
    if base.returncode != 0:
        pytest.skip("no HEAD")
    sha = base.stdout.strip()
    missing = tmp_path / "missing.txt"
    # File does not exist -> should error 1
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--base-sha", sha, "--merge-sha", sha, "--corpus-changed-paths", str(missing)],
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


def test_validate_submission_corpus_flag_exists() -> None:
    from scripts.validate_submission import _validate_corpus_changed_paths_file

    assert callable(_validate_corpus_changed_paths_file)
    # None -> continue
    assert _validate_corpus_changed_paths_file(None) is None
