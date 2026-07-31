"""Tests for the BenchBox-local agent write preflight guard."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


SCRIPT = Path("scripts/agent_write_preflight.sh")


def _run_preflight(*, primary_clone: Path, allow: bool = False) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "BENCHBOX_AGENT_PRIMARY_CLONE": str(primary_clone),
    }
    if allow:
        env["BENCHBOX_ALLOW_MAIN_CLONE_WRITE"] = "1"
    else:
        env.pop("BENCHBOX_ALLOW_MAIN_CLONE_WRITE", None)
        env.pop("ALLOW_MAIN_CLONE_WRITE", None)

    return subprocess.run(
        ["sh", str(SCRIPT)],
        cwd=Path.cwd(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_preflight_rejects_primary_clone_without_override() -> None:
    result = _run_preflight(primary_clone=Path.cwd())

    assert result.returncode == 1
    assert "Refusing BenchBox write preflight in the primary clone" in result.stderr
    assert "make worktree-claim BRANCH=fix/descriptive-slug" in result.stderr


def test_preflight_allows_explicit_primary_clone_override() -> None:
    result = _run_preflight(primary_clone=Path.cwd(), allow=True)

    assert result.returncode == 0
    assert "BenchBox write preflight OK" in result.stdout


def test_preflight_allows_non_primary_worktree() -> None:
    result = _run_preflight(primary_clone=Path.cwd().parent)

    assert result.returncode == 0
    assert "BenchBox write preflight OK" in result.stdout


def test_claude_pr_command_runs_write_preflight_before_pr_workflow() -> None:
    command = Path(".claude/commands/pr.md").read_text(encoding="utf-8")

    assert "make agent-write-preflight" in command
    assert "make worktree-claim BRANCH=<name>" in command
    assert "make worktree-add" not in command


def test_skill_sync_write_target_runs_preflight() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    target = makefile.split("\nskill-sync:", maxsplit=1)[1].split("\nskill-sync-check:", maxsplit=1)[0]

    assert "$(MAKE) -s agent-write-preflight" in target


def _init_clone(path: Path) -> Path:
    """A fresh plain clone: one worktree, no pool — i.e. what a remote agent
    session or CI runner actually looks like on disk."""
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    return path


def _run_in_clone(repo: Path, *, ephemeral: bool = False) -> subprocess.CompletedProcess[str]:
    env = {**os.environ}
    # Let the script derive the primary clone naturally from this repo.
    env.pop("BENCHBOX_AGENT_PRIMARY_CLONE", None)
    env.pop("BENCHBOX_ALLOW_MAIN_CLONE_WRITE", None)
    env.pop("ALLOW_MAIN_CLONE_WRITE", None)
    if ephemeral:
        env["BENCHBOX_EPHEMERAL_CLONE"] = "1"
    else:
        env.pop("BENCHBOX_EPHEMERAL_CLONE", None)

    return subprocess.run(
        ["sh", str(SCRIPT.resolve())],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_preflight_still_refuses_an_undeclared_plain_clone(tmp_path: Path) -> None:
    """The declaration is opt-in: absent it, behavior is exactly as before."""
    result = _run_in_clone(_init_clone(tmp_path / "BenchBox"))

    assert result.returncode == 1
    assert "Refusing BenchBox write preflight in the primary clone" in result.stderr


def test_preflight_allows_a_declared_ephemeral_clone(tmp_path: Path) -> None:
    result = _run_in_clone(_init_clone(tmp_path / "BenchBox"), ephemeral=True)

    assert result.returncode == 0
    assert "ephemeral clone" in result.stdout


def test_ephemeral_declaration_is_ignored_when_a_worktree_pool_is_present(tmp_path: Path) -> None:
    """The load-bearing safety property: on a machine running the pool this
    guard protects, declaring the clone ephemeral must NOT switch it off."""
    repo = _init_clone(tmp_path / "BenchBox")
    (tmp_path / "BenchBox.pool-01").mkdir()

    result = _run_in_clone(repo, ephemeral=True)

    assert result.returncode == 1
    assert "Refusing BenchBox write preflight in the primary clone" in result.stderr


def test_refusal_names_the_ephemeral_escape_not_only_the_broad_override(tmp_path: Path) -> None:
    """The refusal used to offer BENCHBOX_ALLOW_MAIN_CLONE_WRITE as the only way
    out, which trained agents to reach for the blanket override routinely."""
    result = _run_in_clone(_init_clone(tmp_path / "BenchBox"))

    assert "BENCHBOX_EPHEMERAL_CLONE=1" in result.stderr
    assert "ephemeral" in result.stderr
    assert "make worktree-claim" in result.stderr
