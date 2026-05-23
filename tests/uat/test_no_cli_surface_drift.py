"""Guard that UAT follow-up work does not change the public BenchBox CLI surface."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.fast

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWED_INTERNAL_CLI_FILES = {
    "benchbox/cli/benchmarks.py",
    "benchbox/cli/commands/convert.py",
    "benchbox/cli/commands/run.py",
    "benchbox/cli/commands/submit.py",
    "benchbox/cli/commands/visualize.py",
    "benchbox/cli/help.py",
    "benchbox/cli/orchestrator.py",
}
FORBIDDEN_CLI_SURFACE_SNIPPETS = ("@click.option", "@click.command", "@click.group")
FORBIDDEN_CLI_SURFACE_DEFS = {
    "benchbox/cli/commands/convert.py": "def convert(",
    "benchbox/cli/commands/run.py": "def run(",
    "benchbox/cli/commands/submit.py": "def submit(",
    "benchbox/cli/commands/visualize.py": "def visualize(",
}


def test_uat_did_not_modify_benchbox_cli_surface():
    base = _verified_base_ref()
    changed = set(_git("diff", "--name-only", base, "--", "benchbox/cli/").stdout.splitlines())
    unexpected = changed - ALLOWED_INTERNAL_CLI_FILES

    assert not unexpected, f"Unexpected benchbox CLI file changes: {sorted(unexpected)}"

    forbidden = []
    for path in sorted(ALLOWED_INTERNAL_CLI_FILES):
        diff = _git("diff", "--unified=0", base, "--", path).stdout
        changed_lines = [
            line for line in diff.splitlines() if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        ]
        forbidden_def = FORBIDDEN_CLI_SURFACE_DEFS.get(path)
        forbidden.extend(
            line
            for line in changed_lines
            if any(snippet in line for snippet in FORBIDDEN_CLI_SURFACE_SNIPPETS)
            or (forbidden_def is not None and line[1:].lstrip().startswith(forbidden_def))
        )
    assert not forbidden, f"Unexpected CLI surface changes: {forbidden}"


def _verified_base_ref() -> str:
    inside = _git("rev-parse", "--is-inside-work-tree", check=False)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        pytest.skip("CLI surface drift guard requires a git worktree")

    base = os.environ.get("BENCHBOX_BASE_REF", "origin/develop")
    verified = _git("rev-parse", "--verify", f"{base}^{{commit}}", check=False)
    if verified.returncode != 0:
        pytest.skip(f"CLI surface drift guard base ref {base!r} is not available")
    return base


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed with {result.returncode}: {result.stderr.strip() or result.stdout.strip()}"
        )
    return result
