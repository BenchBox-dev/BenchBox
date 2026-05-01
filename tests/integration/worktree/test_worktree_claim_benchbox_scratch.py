"""Regression tests for retained worktree claim slot selection."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]


def run(cmd: list[str], cwd: Path, **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=True, **kwargs)


def init_repo(path: Path) -> None:
    path.mkdir()
    run(["git", "init"], path)
    run(["git", "config", "user.email", "test@example.com"], path)
    run(["git", "config", "user.name", "BenchBox Test"], path)
    (path / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    (path / "README.md").write_text("test repo\n", encoding="utf-8")
    run(["git", "add", ".gitignore", "README.md"], path)
    run(["git", "commit", "-m", "initial"], path)


def create_origin_with_develop(tmp_path: Path) -> Path:
    seed = tmp_path / "seed"
    origin = tmp_path / "origin.git"
    init_repo(seed)
    run(["git", "branch", "-M", "develop"], seed)
    run(["git", "init", "--bare", str(origin)], tmp_path)
    run(["git", "remote", "add", "origin", str(origin)], seed)
    run(["git", "push", "-u", "origin", "develop"], seed)
    return origin


def test_worktree_claim_ignores_untracked_benchbox_scratch(tmp_path: Path) -> None:
    origin = create_origin_with_develop(tmp_path)
    main = tmp_path / "BenchBox"
    pool_parent = tmp_path / "pool"
    pool_parent.mkdir()
    pool = pool_parent / "BenchBox.pool-01"
    run(["git", "clone", str(origin), str(main)], tmp_path)
    run(["git", "clone", str(origin), str(pool)], tmp_path)
    run(["git", "checkout", "--detach", "origin/develop"], pool)
    (pool / ".venv").mkdir()
    (pool / ".venv" / "pyvenv.cfg").write_text("home = test\n", encoding="utf-8")
    (pool / ".benchbox" / "cache").mkdir(parents=True)
    (pool / ".benchbox" / "cache" / "scratch").write_text("scratch\n", encoding="utf-8")

    result = subprocess.run(
        [
            "make",
            "-f",
            str(REPO_ROOT / "Makefile"),
            "-s",
            "worktree-claim-attempt",
            "BRANCH=feature/scratch-ok",
            "POOL_SIZE=1",
            f"WORKTREE_POOL_PARENT={pool_parent}",
        ],
        cwd=main,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert f"WORKTREE_PATH={pool.resolve()}" in result.stdout
    assert run(["git", "branch", "--show-current"], pool).stdout.strip() == "feature/scratch-ok"
    assert (pool / ".benchbox" / "cache" / "scratch").exists()


def test_worktree_claim_keeps_claim_marker_blocking(tmp_path: Path) -> None:
    origin = create_origin_with_develop(tmp_path)
    main = tmp_path / "BenchBox"
    pool_parent = tmp_path / "pool"
    pool_parent.mkdir()
    pool = pool_parent / "BenchBox.pool-01"
    run(["git", "clone", str(origin), str(main)], tmp_path)
    run(["git", "clone", str(origin), str(pool)], tmp_path)
    run(["git", "checkout", "--detach", "origin/develop"], pool)
    (pool / ".venv").mkdir()
    (pool / ".venv" / "pyvenv.cfg").write_text("home = test\n", encoding="utf-8")
    (pool / ".benchbox").mkdir()
    (pool / ".benchbox" / "claim_in_progress").write_text("pid=1\n", encoding="utf-8")

    result = subprocess.run(
        [
            "make",
            "-f",
            str(REPO_ROOT / "Makefile"),
            "-s",
            "worktree-claim-attempt",
            "BRANCH=feature/blocked",
            "POOL_SIZE=1",
            f"WORKTREE_POOL_PARENT={pool_parent}",
        ],
        cwd=main,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "WORKTREE_PATH=" not in result.stdout
    assert run(["git", "branch", "--show-current"], pool).stdout.strip() == ""
