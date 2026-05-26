"""Tests for release changelog generation."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_changelog_entry.py"

spec = importlib.util.spec_from_file_location("generate_changelog_entry", SCRIPT_PATH)
assert spec is not None
generate_changelog_entry = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(generate_changelog_entry)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _commit(repo: Path, message: str, filename: str, content: str) -> None:
    path = repo / filename
    path.write_text(content, encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", message)


def test_since_ref_limits_release_changelog_to_main_delta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Release branches should summarize changes absent from main, not all reachable commits."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")

    (repo / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n\n", encoding="utf-8")
    _git(repo, "add", "CHANGELOG.md")
    _git(repo, "commit", "-m", "chore: initial")
    initial_commit = _git(repo, "rev-parse", "HEAD")

    _git(repo, "branch", "-M", "main")
    _commit(repo, "fix: main-only release hardening", "main.txt", "main\n")

    _git(repo, "checkout", "-b", "develop", initial_commit)
    _commit(repo, "feat: add broad release feature", "feature.txt", "feature\n")
    _commit(repo, "fix: repair clean install", "fix.txt", "fix\n")

    monkeypatch.setattr(generate_changelog_entry, "_summarize_changelog_with_claude", lambda *args: None)

    assert generate_changelog_entry.generate_changelog_entry(
        repo,
        version="0.3.1",
        release_date="2026-05-26",
        since_ref="main",
    )

    changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [0.3.1] - 2026-05-26" in changelog
    assert "- add broad release feature" in changelog
    assert "- repair clean install" in changelog
    assert "main-only release hardening" not in changelog
