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
