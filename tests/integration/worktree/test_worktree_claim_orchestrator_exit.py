"""Regression test for worktree-claim orchestrator exit-status path.

When `worktree-claim-attempt` succeeds on the first try, the
`worktree-claim-locked` orchestrator must exit 0 cleanly and must NOT
fall through to the auto-sweep retry branch. The bug class is "make
recipe runs each `@` line in its own subshell, so `if ... then exit 0`
exits the subshell but make still walks to the next line"; the fix is
chaining the recipe into a single shell with line continuations.
"""

from __future__ import annotations

import os
import shutil
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


def test_worktree_claim_orchestrator_first_attempt_success_exits_zero(tmp_path: Path) -> None:
    """Successful first-pass claim must exit 0 without running auto-sweep."""
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

    # The orchestrator recursively invokes $(MAKE) without -f, so the
    # Makefile must be discoverable from cwd. Symlink the real Makefile
    # and the scripts/ directory it depends on into the temp main clone.
    (main / "Makefile").symlink_to(REPO_ROOT / "Makefile")
    (main / "scripts").symlink_to(REPO_ROOT / "scripts")

    result = subprocess.run(
        [
            "make",
            "-s",
            "worktree-claim-locked",
            "BRANCH=feature/orchestrator-exit",
            "POOL_SIZE=1",
            f"WORKTREE_POOL_PARENT={pool_parent}",
        ],
        cwd=main,
        env={**os.environ},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, (
        f"orchestrator should exit 0 on first-pass success.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "WORKTREE_PATH=" in result.stdout
    assert "No free pool worktree on first pass" not in result.stderr, (
        "auto-sweep retry path must not fire after a successful first attempt"
    )
    assert "Still no free pool worktree available" not in result.stderr
    assert run(["git", "branch", "--show-current"], pool).stdout.strip() == "feature/orchestrator-exit"
