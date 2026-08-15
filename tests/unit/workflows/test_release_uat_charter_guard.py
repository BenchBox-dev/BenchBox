"""Contract tests for the release workflow's UAT charter guard."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"


def _workflow() -> dict[str, Any]:
    return yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))


def _needs(job: dict[str, Any]) -> list[str]:
    needs = job.get("needs", [])
    return [needs] if isinstance(needs, str) else needs


def test_release_build_requires_the_uat_charter_guard() -> None:
    jobs = _workflow()["jobs"]

    assert "verify-uat-charter" in jobs
    assert "verify-uat-charter" in _needs(jobs["build"])
    assert "verify-tag-on-release" in _needs(jobs["verify-uat-charter"])


def test_uat_charter_guard_is_fail_closed_and_uses_committed_candidates() -> None:
    jobs = _workflow()["jobs"]
    steps = jobs["verify-uat-charter"]["steps"]
    run = next(step["run"] for step in steps if step.get("name") == "Require a committed UAT charter or pointer")

    assert "tests/uat/CHARTER.md" in run
    assert "_project/release-evidence/README.md" in run
    assert "git ls-files --error-unmatch" in run
    assert 'test -s "$path"' in run
    assert "found=0" in run
    assert 'if [ "$found" -eq 0 ]' in run
    assert "exit 1" in run


def test_canonical_uat_charter_candidates_exist_on_develop() -> None:
    assert (REPO_ROOT / "tests/uat/CHARTER.md").is_file()
    # release-cut intentionally removes the development-only _project tree;
    # the release workflow still accepts this path when it is present on
    # develop, but release-tree fast tests must not require it.
    if (REPO_ROOT / "_project" / "decisions").is_dir():
        assert (REPO_ROOT / "_project/release-evidence/README.md").is_file()
