"""Exercise the cut preflight against real local Git refs and worktrees."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "release_cut_start.sh"


def git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def start(cwd: Path, version: str = "9.9.9") -> subprocess.CompletedProcess[str]:
    return subprocess.run(["sh", str(SCRIPT), version], cwd=cwd, text=True, capture_output=True, check=False)


@pytest.fixture
def cut_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    remote = tmp_path / "remote.git"
    primary = tmp_path / "primary"
    linked = tmp_path / "linked"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(remote), str(primary)], check=True, capture_output=True)
    git(primary, "config", "user.name", "Release Test")
    git(primary, "config", "user.email", "release-test@example.com")
    git(primary, "switch", "-c", "develop")
    (primary / "source.txt").write_text("initial\n", encoding="utf-8")
    git(primary, "add", "source.txt")
    git(primary, "commit", "-m", "Initial source")
    git(primary, "push", "-u", "origin", "develop")
    git(primary, "worktree", "add", "-b", "fix/release-cut", str(linked), "origin/develop")
    return remote, primary, linked


def test_accepts_exact_fetched_head_and_resumes_without_discarding_edits(cut_repo: tuple[Path, Path, Path]) -> None:
    _, primary, linked = cut_repo
    base = git(linked, "rev-parse", "HEAD")
    result = start(linked)
    assert result.returncode == 0, result.stderr
    assert git(linked, "branch", "--show-current") == "v9.9.9"
    assert git(linked, "rev-parse", "HEAD") == base

    (linked / "CHANGELOG.md").write_text("curated\n", encoding="utf-8")
    result = start(linked)
    assert result.returncode == 0, result.stderr
    assert (linked / "CHANGELOG.md").read_text(encoding="utf-8") == "curated\n"

    git(linked, "config", "user.name", "Release Test")
    git(linked, "config", "user.email", "release-test@example.com")
    git(linked, "add", "CHANGELOG.md")
    git(linked, "commit", "-m", "Release v9.9.9")
    assert git(linked, "rev-parse", "HEAD^1") == base
    result = start(linked)
    assert result.returncode != 0
    assert "already carries its release commit" in result.stderr
    assert git(primary, "branch", "--show-current") == "develop"


@pytest.mark.parametrize(
    "state", ["ahead", "behind", "dirty", "local-branch", "local-tag", "remote-branch", "remote-tag"]
)
def test_rejects_unsafe_new_cut(cut_repo: tuple[Path, Path, Path], state: str) -> None:
    _, primary, linked = cut_repo
    if state == "ahead":
        (linked / "source.txt").write_text("ahead\n", encoding="utf-8")
        git(linked, "add", "source.txt")
        git(
            linked, "-c", "user.name=Release Test", "-c", "user.email=release-test@example.com", "commit", "-m", "Ahead"
        )
    elif state == "behind":
        (primary / "source.txt").write_text("behind\n", encoding="utf-8")
        git(primary, "add", "source.txt")
        git(primary, "commit", "-m", "Advance develop")
        git(primary, "push", "origin", "develop")
    elif state == "dirty":
        (linked / "untracked.txt").write_text("dirty\n", encoding="utf-8")
    elif state == "local-branch":
        git(primary, "branch", "v9.9.9")
    elif state == "local-tag":
        git(primary, "tag", "v9.9.9")
    elif state == "remote-branch":
        git(primary, "push", "origin", "HEAD:refs/heads/v9.9.9")
    else:
        git(primary, "tag", "v9.9.9")
        git(primary, "push", "origin", "refs/tags/v9.9.9")

    result = start(linked)
    assert result.returncode != 0
    assert git(linked, "branch", "--show-current") == "fix/release-cut"


def test_rejects_primary_clone(cut_repo: tuple[Path, Path, Path]) -> None:
    _, primary, _ = cut_repo
    result = start(primary)
    assert result.returncode != 0
    assert "requires a linked worktree" in result.stderr


def test_rejects_invalid_version_before_branch_change(cut_repo: tuple[Path, Path, Path]) -> None:
    _, _, linked = cut_repo
    result = start(linked, "not-a-version")
    assert result.returncode != 0
    assert "VERSION must be X.Y.Z" in result.stderr
    assert git(linked, "branch", "--show-current") == "fix/release-cut"
