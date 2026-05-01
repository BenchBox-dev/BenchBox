"""Regression tests for retained worktree claim signal handling."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.integration,
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


def test_worktree_claim_int_trap_exits_nonzero_after_cleanup(tmp_path: Path) -> None:
    real_git = shutil.which("git")
    assert real_git is not None
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

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    git_wrapper = bin_dir / "git"
    git_wrapper.write_text(
        f"""#!/bin/sh
if [ "$1" = "-C" ] && [ "$3" = "reset" ]; then
  kill -INT "$PPID"
  exit 0
fi
exec "{real_git}" "$@"
""",
        encoding="utf-8",
    )
    git_wrapper.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}

    result = subprocess.run(
        [
            "make",
            "-f",
            str(REPO_ROOT / "Makefile"),
            "-s",
            "worktree-claim-attempt",
            "BRANCH=feature/signal-test",
            "POOL_SIZE=1",
            f"WORKTREE_POOL_PARENT={pool_parent}",
        ],
        cwd=main,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "WORKTREE_PATH=" not in result.stdout
    assert "claim of pool-01 failed; slot returned to detached origin/develop" in result.stderr
    assert not (pool / ".benchbox" / "claim_in_progress").exists()
    assert run(["git", "branch", "--show-current"], pool).stdout.strip() == ""
    assert run(["git", "branch", "--list", "feature/signal-test"], pool).stdout.strip() == ""
