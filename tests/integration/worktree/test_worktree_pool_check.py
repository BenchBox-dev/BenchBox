"""Regression tests for `make worktree-pool-check` invariant assertions.

Verifies the contract documented in the recipe: exit non-zero if any slot
is missing, aborted, or there are extras beyond POOL_SIZE; exit zero
otherwise.
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


def setup_pool(tmp_path: Path, num_slots: int) -> tuple[Path, Path]:
    """Create a main clone + `num_slots` pool worktrees on detached develop."""
    real_git = shutil.which("git")
    assert real_git is not None
    origin = create_origin_with_develop(tmp_path)
    main = tmp_path / "BenchBox"
    pool_parent = tmp_path / "pool"
    pool_parent.mkdir()
    run(["git", "clone", str(origin), str(main)], tmp_path)
    for i in range(1, num_slots + 1):
        slot = pool_parent / f"BenchBox.pool-{i:02d}"
        run(["git", "clone", str(origin), str(slot)], tmp_path)
        run(["git", "checkout", "--detach", "origin/develop"], slot)
    return main, pool_parent


def invoke_check(main: Path, pool_parent: Path, pool_size: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "make",
            "-f",
            str(REPO_ROOT / "Makefile"),
            "-s",
            "worktree-pool-check",
            f"POOL_SIZE={pool_size}",
            f"WORKTREE_POOL_PARENT={pool_parent}",
        ],
        cwd=main,
        env={**os.environ},
        text=True,
        capture_output=True,
        check=False,
    )


def test_pool_check_passes_when_all_slots_present_and_clean(tmp_path: Path) -> None:
    main, pool_parent = setup_pool(tmp_path, num_slots=2)
    result = invoke_check(main, pool_parent, pool_size=2)
    assert result.returncode == 0, result.stderr
    assert "Pool invariant check OK" in result.stdout


def test_pool_check_fails_when_slot_missing(tmp_path: Path) -> None:
    main, pool_parent = setup_pool(tmp_path, num_slots=1)
    result = invoke_check(main, pool_parent, pool_size=2)
    assert result.returncode != 0
    assert "missing" in result.stderr
    assert "pool-02" in result.stderr


def test_pool_check_fails_when_claim_in_progress_marker_present(tmp_path: Path) -> None:
    main, pool_parent = setup_pool(tmp_path, num_slots=2)
    marker = pool_parent / "BenchBox.pool-01" / ".benchbox" / "claim_in_progress"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("pid=99999 started=2026-05-02T00:00:00Z branch=feature/dead\n", encoding="utf-8")
    result = invoke_check(main, pool_parent, pool_size=2)
    assert result.returncode != 0
    assert "aborted" in result.stderr
    assert "pool-01" in result.stderr


def test_pool_check_fails_when_extra_slot_beyond_pool_size(tmp_path: Path) -> None:
    main, pool_parent = setup_pool(tmp_path, num_slots=3)
    # POOL_SIZE=2 but pool-03 exists → extra slot.
    result = invoke_check(main, pool_parent, pool_size=2)
    assert result.returncode != 0
    assert "Extra pool slots beyond POOL_SIZE" in result.stderr
    assert "BenchBox.pool-03" in result.stderr
