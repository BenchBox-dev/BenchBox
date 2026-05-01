"""Regression tests for retained worktree release safety."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.integration,
]

REPO_ROOT = Path(__file__).resolve().parents[3]


def run(cmd: list[str], cwd: Path, **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=True, **kwargs)


def init_feature_repo(path: Path) -> None:
    path.mkdir()
    run(["git", "init"], path)
    run(["git", "config", "user.email", "test@example.com"], path)
    run(["git", "config", "user.name", "BenchBox Test"], path)
    (path / "README.md").write_text("test repo\n", encoding="utf-8")
    run(["git", "add", "README.md"], path)
    run(["git", "commit", "-m", "initial"], path)
    run(["git", "checkout", "-b", "feature/dirty-release"], path)


def test_worktree_release_refuses_staged_changes_before_pr_lookup(tmp_path: Path) -> None:
    repo = tmp_path / "BenchBox.pool-01"
    init_feature_repo(repo)
    (repo / "dirty.txt").write_text("do not discard\n", encoding="utf-8")
    run(["git", "add", "dirty.txt"], repo)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text("#!/bin/sh\necho gh should not be called >&2\nexit 99\n", encoding="utf-8")
    gh.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}

    result = subprocess.run(
        ["make", "-f", str(REPO_ROOT / "Makefile"), "-s", "worktree-release-locked"],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Refusing to release dirty pool worktree" in result.stdout
    assert "A  dirty.txt" in result.stdout
    assert "gh should not be called" not in result.stderr
    branch = run(["git", "branch", "--show-current"], repo).stdout.strip()
    assert branch == "feature/dirty-release"
