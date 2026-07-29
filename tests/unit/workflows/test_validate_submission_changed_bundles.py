"""Regression tests for companion-only submission workflow changes."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "validate-submission.yml"


def _changed_bundle_discovery_script() -> str:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    step = next(step for step in workflow["jobs"]["validate"]["steps"] if step.get("id") == "changed")
    run = step["run"]
    start = run.index("CHANGED=$(git diff")
    end = run.index('if [ -z "$CHANGED" ]')
    return (
        run[start:end].replace("${{ github.event.pull_request.base.sha }}", "$BASE_SHA") + 'printf "%s\\n" "$CHANGED"\n'
    )


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_applied_only_change_discovers_paired_primary_bundle(tmp_path: Path) -> None:
    """An applied-ledger-only edit must still invoke primary-bundle validation."""
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.invalid")

    primary = tmp_path / "results-data" / "bundles" / "result.json"
    primary.parent.mkdir(parents=True)
    primary.write_text("{}\n", encoding="utf-8")
    _git(tmp_path, "add", str(primary.relative_to(tmp_path)))
    _git(tmp_path, "commit", "--quiet", "-m", "base")
    base_sha = _git(tmp_path, "rev-parse", "HEAD")

    applied = primary.with_name("result.applied.json")
    applied.write_text('{"status": "passed"}\n', encoding="utf-8")
    _git(tmp_path, "add", str(applied.relative_to(tmp_path)))
    _git(tmp_path, "commit", "--quiet", "-m", "applied")

    env = os.environ.copy()
    env["BASE_SHA"] = base_sha
    result = subprocess.run(
        ["bash", "-c", _changed_bundle_discovery_script()],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines() == ["results-data/bundles/result.json"]


def test_applied_companion_derivation_is_deletion_aware() -> None:
    """The workflow must inspect an existing primary when its companion is removed."""
    script = _changed_bundle_discovery_script()
    assert "--diff-filter=ACMRD" in script
    assert "CHANGED_APPLIED" in script
    assert 'bundle="${applied%.applied.json}.json"' in script
    assert 'git cat-file -e "HEAD:${bundle}"' in script


def test_applied_companion_rename_discovers_the_source_primary_bundle(tmp_path: Path) -> None:
    """A companion rename must validate the source primary bundle still in HEAD."""
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.invalid")

    primary = tmp_path / "results-data" / "bundles" / "result.json"
    primary.parent.mkdir(parents=True)
    primary.write_text("{}\n", encoding="utf-8")
    applied = primary.with_name("result.applied.json")
    applied.write_text('{"status": "passed"}\n', encoding="utf-8")
    _git(tmp_path, "add", str(primary.relative_to(tmp_path)), str(applied.relative_to(tmp_path)))
    _git(tmp_path, "commit", "--quiet", "-m", "base")
    base_sha = _git(tmp_path, "rev-parse", "HEAD")

    renamed = applied.with_name("renamed.applied.json")
    applied.rename(renamed)
    _git(tmp_path, "add", "-u", str(applied.relative_to(tmp_path)))
    _git(tmp_path, "add", str(renamed.relative_to(tmp_path)))
    _git(tmp_path, "commit", "--quiet", "-m", "rename-applied")

    env = os.environ.copy()
    env["BASE_SHA"] = base_sha
    result = subprocess.run(
        ["bash", "-c", _changed_bundle_discovery_script()],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines() == ["results-data/bundles/result.json"]
